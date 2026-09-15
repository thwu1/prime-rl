"""
tcgen05 Shared Memory Layout and Descriptor Encoding Library.

Implement the functions below to compute NVIDIA Blackwell (sm100)
tcgen05 shared memory layouts, address swizzling, and descriptor
encoding for matrix multiply operations.

Reference data is distributed across multiple sources:
  - /app/concepts.md         — architectural background
  - /app/vectors.db          — SQLite database with address mapping vectors
                               (use JOINs on swizzle_modes to resolve mode IDs)
  - /app/descriptors/        — raw binary packed descriptor files + manifest.csv
  - /app/hw_config_dump.json — nested hardware config with TMA test cases
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SWIZZLE_NONE = "NONE"
SWIZZLE_32B = "32B"
SWIZZLE_64B = "64B"
SWIZZLE_128B = "128B"

# Strip widths in bytes for each swizzle mode
CHUNK_WIDTHS = {
    SWIZZLE_NONE: 16,
    SWIZZLE_32B: 32,
    SWIZZLE_64B: 64,
    SWIZZLE_128B: 128,
}

# Accumulator data-type codes for the instruction descriptor
ACC_DTYPE_CODES = {
    "FP16": 0,
    "FP32": 1,
    "S32": 2,
}

# A/B operand data-type codes for the instruction descriptor
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
# Functions to implement
# ---------------------------------------------------------------------------

def compute_physical_offset(row, col_bytes, tile_height, swizzle_mode):
    """Map logical (row, col_bytes) to physical byte offset in shared memory.

    Returns an integer byte offset.
    """
    raise NotImplementedError


def compute_logical_coords(physical_offset, tile_height,
                           tile_width_bytes, swizzle_mode):
    """Inverse of compute_physical_offset.

    Returns a (row, col_bytes) tuple.
    """
    raise NotImplementedError


def encode_smem_descriptor(base_addr, tile_height, swizzle_mode):
    """Encode the 64-bit shared memory descriptor for tcgen05.mma.

    Only SWIZZLE_NONE and SWIZZLE_128B need to be supported.
    Returns a 64-bit integer.
    """
    raise NotImplementedError


def encode_instruction_descriptor(acc_dtype, a_dtype, b_dtype,
                                  mma_m, mma_n):
    """Encode the 32-bit instruction descriptor for tcgen05.mma.

    Returns a 32-bit integer.
    """
    raise NotImplementedError


def compute_tma_params(M, K, block_m, block_k, elem_bytes, swizzle_mode):
    """Compute 3D TMA tensor-map parameters for tcgen05 layout.

    Returns a dict with keys 'globalDim' (list of 3 ints),
    'globalStrides' (list of 2 ints in bytes), and
    'boxDim' (list of 3 ints). All in PTX ordering.
    """
    raise NotImplementedError


def rearrange_tile(data, tile_height, tile_width_bytes, swizzle_mode):
    """Rearrange a row-major logical tile to tcgen05 physical layout.

    Returns a bytes object of the same length as data.
    """
    raise NotImplementedError
