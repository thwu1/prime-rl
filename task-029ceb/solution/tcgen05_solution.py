
"""
tcgen05 Shared Memory Layout and Descriptor Encoding Library.

Implements NVIDIA Blackwell (sm100) tcgen05 shared memory layout
computations, swizzle address mapping, and descriptor encoding
for matrix multiply operations.
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SWIZZLE_NONE = "NONE"
SWIZZLE_32B = "32B"
SWIZZLE_64B = "64B"
SWIZZLE_128B = "128B"

CHUNK_WIDTHS = {
    SWIZZLE_NONE: 16,
    SWIZZLE_32B: 32,
    SWIZZLE_64B: 64,
    SWIZZLE_128B: 128,
}

SWIZZLE_CODES = {
    SWIZZLE_NONE: 0,
    SWIZZLE_128B: 2,
}

ACC_DTYPE_CODES = {
    "FP16": 0,
    "FP32": 1,
    "S32": 2,
}

AB_DTYPE_CODES = {
    "FP16": 0,
    "BF16": 1,
    "TF32": 2,
    "FP8_E4M3": 3,
    "FP8_E5M2": 4,
    "S8": 5,
    "U8": 6,
}


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def compute_physical_offset(row, col_bytes, tile_height, swizzle_mode):
    chunk = CHUNK_WIDTHS[swizzle_mode]
    n_units = chunk // 16
    mask = n_units - 1

    chunk_idx = col_bytes // chunk
    col_in_chunk = col_bytes % chunk
    unit_16b = col_in_chunk // 16
    byte_in_unit = col_in_chunk % 16

    swizzled_unit = unit_16b ^ (row & mask)

    return (chunk_idx * tile_height * chunk
            + row * chunk
            + swizzled_unit * 16
            + byte_in_unit)


def compute_logical_coords(physical_offset, tile_height, tile_width_bytes, swizzle_mode):
    chunk = CHUNK_WIDTHS[swizzle_mode]
    n_units = chunk // 16
    mask = n_units - 1

    chunk_stride = tile_height * chunk
    chunk_idx = physical_offset // chunk_stride
    remainder = physical_offset % chunk_stride

    row = remainder // chunk
    col_in_row = remainder % chunk
    phys_unit = col_in_row // 16
    byte_in_unit = col_in_row % 16

    logical_unit = phys_unit ^ (row & mask)

    col_bytes = chunk_idx * chunk + logical_unit * 16 + byte_in_unit
    return (row, col_bytes)


def encode_smem_descriptor(base_addr, tile_height, swizzle_mode):
    chunk = CHUNK_WIDTHS[swizzle_mode]
    swizzle_code = SWIZZLE_CODES[swizzle_mode]

    addr_enc = (base_addr >> 4) & 0x3FFF

    sbo = 8 * chunk
    sbo_enc = (sbo >> 4) & 0x3FFF

    desc = addr_enc | (sbo_enc << 32) | (1 << 46)

    if swizzle_mode == SWIZZLE_NONE:
        lbo = tile_height * 16
        lbo_enc = (lbo >> 4) & 0x3FFF
        desc |= (lbo_enc << 16)

    if swizzle_code != 0:
        desc |= (swizzle_code << 61)

    return desc


def encode_instruction_descriptor(acc_dtype, a_dtype, b_dtype, mma_m, mma_n):
    return ((ACC_DTYPE_CODES[acc_dtype] << 4)
            | (AB_DTYPE_CODES[a_dtype] << 7)
            | (AB_DTYPE_CODES[b_dtype] << 10)
            | ((mma_n >> 3) << 17)
            | ((mma_m >> 4) << 24))


def compute_tma_params(M, K, block_m, block_k, elem_bytes, swizzle_mode):
    chunk = CHUNK_WIDTHS[swizzle_mode]
    inner_elems = chunk // elem_bytes

    return {
        "globalDim": [inner_elems, M, K // inner_elems],
        "globalStrides": [K * elem_bytes, chunk],
        "boxDim": [inner_elems, block_m, block_k // inner_elems],
    }


def rearrange_tile(data, tile_height, tile_width_bytes, swizzle_mode):
    n = tile_height * tile_width_bytes
    assert len(data) == n
    out = bytearray(n)
    for r in range(tile_height):
        for c in range(tile_width_bytes):
            p = compute_physical_offset(r, c, tile_height, swizzle_mode)
            out[p] = data[r * tile_width_bytes + c]
    return bytes(out)
