# tcgen05 Shared Memory Layout and Descriptor Specification

## Overview

NVIDIA Blackwell (sm100) GPUs use `tcgen05.mma` PTX instructions for Tensor Core matrix
multiply-accumulate. These instructions require input matrices A and B to reside in shared
memory in a specific layout determined by the **swizzle mode**. This document specifies:

1. The shared memory layout transformation (logical to physical byte mapping)
2. Shared memory descriptor encoding (64-bit)
3. Instruction descriptor encoding (32-bit)
4. TMA (Tensor Memory Accelerator) 3D parameter computation

## 1. Core Matrix and Shared Memory Layout

### 1.1 Core Matrix

The fundamental data unit for tcgen05 is the **core matrix**: an 8-row by 16-byte tile.
For BF16 data (2 bytes/element) this holds 8x8 = 64 elements; for FP32 (4 bytes/element)
it holds 8x4 = 32 elements.

### 1.2 Swizzle Modes and Chunk Width

Each swizzle mode defines a **chunk width** (the width of a contiguous tile strip):

| Swizzle Mode | Chunk Width (bytes) | 16B Units per Chunk | XOR Mask |
|-------------|--------------------:|--------------------:|---------:|
| NONE        | 16                  | 1                   | 0        |
| 32B         | 32                  | 2                   | 1        |
| 64B         | 64                  | 4                   | 3        |
| 128B        | 128                 | 8                   | 7        |

The XOR mask equals `(chunk_width / 16) - 1`.

### 1.3 Logical-to-Physical Address Mapping

A logical tile of height H rows and width W bytes is divided into vertical strips of
`chunk_width` bytes. Each strip `[H, chunk_width]` occupies `H * chunk_width` contiguous
bytes, and strips are laid out sequentially in shared memory.

Within each strip row (of `chunk_width` bytes), the constituent 16-byte units are
**permuted** by XOR-ing with the row index:

    swizzled_unit = logical_unit XOR (row AND mask)

The complete mapping from logical position `(row, col_bytes)` to physical byte offset:

    chunk_idx    = col_bytes / chunk_width          (integer division)
    col_in_chunk = col_bytes mod chunk_width
    unit_16B     = col_in_chunk / 16
    byte_in_unit = col_in_chunk mod 16
    mask         = (chunk_width / 16) - 1

    swizzled_unit = unit_16B XOR (row AND mask)

    physical_offset = chunk_idx * H * chunk_width
                    + row * chunk_width
                    + swizzled_unit * 16
                    + byte_in_unit

For SWIZZLE_NONE (mask=0), the XOR is identity and each 16-byte column of the tile
becomes a contiguous `[H, 16]` slab.

### 1.4 Inverse Mapping

Since XOR is its own inverse, recovering logical coordinates from a physical offset is:

    chunk_stride = H * chunk_width
    chunk_idx    = physical_offset / chunk_stride
    remainder    = physical_offset mod chunk_stride
    row          = remainder / chunk_width
    col_in_row   = remainder mod chunk_width
    phys_unit    = col_in_row / 16
    byte_in_unit = col_in_row mod 16

    logical_unit = phys_unit XOR (row AND mask)
    col_bytes    = chunk_idx * chunk_width + logical_unit * 16 + byte_in_unit

## 2. Shared Memory Descriptor (64-bit)

The shared memory descriptor for `tcgen05.mma` uses the following bit layout:

| Bits   | Width | Field   | Meaning |
|--------|------:|---------|---------|
| 13:0   | 14    | ADDR    | Base shared-memory address >> 4 |
| 15:14  | 2     | -       | Reserved (0) |
| 29:16  | 14    | LBO     | Leading Byte Offset >> 4 |
| 31:30  | 2     | -       | Reserved (0) |
| 45:32  | 14    | SBO     | Stride Byte Offset >> 4 |
| 46     | 1     | FLAG    | Must be 1 |
| 60:47  | 14    | -       | Reserved (0) |
| 63:61  | 3     | SWIZZLE | Swizzle mode code |

All byte quantities are encoded by right-shifting 4 bits (dividing by 16) and masking
to 14 bits.

### 2.1 LBO (Leading Byte Offset)

LBO is the byte distance between the first and second 16-byte columns that together
form one 32-byte MMA K-stride.

- **SWIZZLE_NONE**: `LBO = tile_height * 16` (the two columns reside in
  separate strips, each `H * 16` bytes long). Encode as `(LBO >> 4) & 0x3FFF`.
- **Swizzled modes**: LBO is implicitly 16 bytes (columns are adjacent within
  a chunk row). Set the LBO field to 0.

### 2.2 SBO (Stride Byte Offset)

SBO is the byte distance from the first 8-row group to the next:

    SBO = 8 * chunk_width

Encode as `(SBO >> 4) & 0x3FFF`.

### 2.3 Swizzle Code

| Mode | Code (bits 63:61) |
|------|------------------:|
| NONE | 0                 |
| 128B | 2                 |

(Only NONE and 128B are specified for this task.)

### 2.4 Assembly

    descriptor = ADDR_enc
               | (LBO_enc << 16)        (NONE only; omit for swizzled)
               | (SBO_enc << 32)
               | (1 << 46)
               | (swizzle_code << 61)

## 3. Instruction Descriptor (32-bit)

The 32-bit instruction descriptor (`idesc`) for `tcgen05.mma`:

| Bits   | Width | Field       | Meaning |
|--------|------:|-------------|---------|
| 3:0    | 4     | -           | Reserved (0) |
| 6:4    | 3     | ACC_DTYPE   | Accumulator data type |
| 9:7    | 3     | A_DTYPE     | A matrix element type |
| 12:10  | 3     | B_DTYPE     | B matrix element type |
| 16:13  | 4     | -           | Reserved (0) |
| 23:17  | 7     | MMA_N_ENC   | MMA_N / 8 |
| 31:24  | 8     | MMA_M_ENC   | MMA_M / 16 |

### 3.1 Data-Type Codes

**Accumulator** (ACC_DTYPE): FP16 = 0, FP32 = 1, S32 = 2

**A/B operands** (A_DTYPE, B_DTYPE): FP16 = 0, BF16 = 1, TF32 = 2, FP8_E4M3 = 3,
FP8_E5M2 = 4, S8 = 5, U8 = 6

### 3.2 Assembly

    idesc = (acc_code  << 4)
          | (a_code   << 7)
          | (b_code   << 10)
          | ((mma_n >> 3) << 17)
          | ((mma_m >> 4) << 24)

## 4. TMA 3D Parameters

To load a tile from global memory into the core-matrix shared-memory layout, a 3D TMA
transfer is used. A K-major global matrix `[M, K]` (K contiguous) is reshaped for the
transfer. All dimension arrays use **PTX ordering** (innermost / fastest-varying dimension
first; stride of the first dimension is implicit and equals one element width).

Let `chunk_elems = chunk_width / elem_bytes` (elements per chunk width).

    globalDim    = [chunk_elems,  M,  K / chunk_elems]
    globalStrides = [K * elem_bytes,  chunk_width]        (2 values, in bytes)
    boxDim       = [chunk_elems,  BLOCK_M,  BLOCK_K / chunk_elems]

Where:
- `elem_bytes` = bytes per element (e.g. 2 for BF16, 4 for FP32)
- `chunk_width` = swizzle-mode chunk width in bytes
- `BLOCK_M`, `BLOCK_K` = tile dimensions in elements

The TMA tensor map is encoded on the host via `cuTensorMapEncodeTiled`, setting the
swizzle mode to `CU_TENSOR_MAP_SWIZZLE_NONE` or `CU_TENSOR_MAP_SWIZZLE_128B`
accordingly.
