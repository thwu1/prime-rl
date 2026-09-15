# Blackwell tcgen05 Shared Memory Concepts

## Core Matrix

The fundamental data unit for `tcgen05.mma` tensor core operations is the **core matrix**: a tile of 8 rows by 16 bytes. All shared memory data layouts for `tcgen05` are organized around these 128-byte units.

## Shared Memory Tile Organization

A logical tile (e.g., the A or B operand of a matrix multiply) has dimensions `[tile_height, tile_width_bytes]`. In shared memory, this tile is organized into **strips** — vertical slabs whose width is determined by the swizzle mode.

Each strip of shape `[tile_height, strip_width]` is stored as a contiguous block in memory. Strips are laid out sequentially: the first strip occupies the lowest addresses, the second strip follows immediately after, and so on.

Within a strip, data is stored row by row. Each row of a strip contains one or more 16-byte units. These units may be **rearranged** within the row according to the swizzle pattern. The rearrangement is deterministic, invertible, and depends on the row's position within a repeating cycle whose period matches the number of units per strip.

## Swizzle Modes

Four swizzle modes are available, each defining a different strip width:

| Mode | Strip Width |
|------|------------|
| NONE | 16 bytes (1 unit, no rearrangement) |
| 32B  | 32 bytes (2 units per row) |
| 64B  | 64 bytes (4 units per row) |
| 128B | 128 bytes (8 units per row) |

For SWIZZLE_NONE, each strip is a single 16-byte column, so no within-row rearrangement occurs. For the other modes, units within each row are permuted based on the row index, ensuring that successive rows access different memory banks.

## Shared Memory Descriptor (64-bit)

The `tcgen05.mma` instruction locates its A and B operands in shared memory via a 64-bit **shared memory descriptor**. This descriptor packs several fields:

- **Base address**: identifies where the tile starts in shared memory
- **Leading byte offset (LBO)**: stride information for navigating between the two 16-byte columns that form one 32-byte MMA K-slice. For non-swizzled layouts where columns are in separate strips, this encodes the inter-strip distance. For swizzled layouts where columns are adjacent within the strip, this field is zero.
- **Stride byte offset (SBO)**: distance from one 8-row core-matrix group to the next within the same strip/chunk
- **Flag bit**: must be set to 1
- **Swizzle code**: identifies the active swizzle mode

Byte quantities stored in the descriptor are right-shifted by 4 bits (equivalent to dividing by 16) before being placed into 14-bit fields.

## Instruction Descriptor (32-bit)

A 32-bit **instruction descriptor** specifies the MMA operation's data types and dimensions. It encodes:

- The accumulator data type (e.g., FP32, FP16, S32)
- The A-operand element type (e.g., FP16, BF16, S8)
- The B-operand element type
- The MMA tile dimensions M and N (where M is encoded as M/16 and N as N/8)

## TMA (Tensor Memory Accelerator) Parameters

The Tensor Memory Accelerator can transfer tiles from global memory directly into the core-matrix shared memory layout using a 3D tensor map. The key parameters are:

- **globalDim**: 3-element array describing the tensor's dimensions in PTX order (innermost/fastest-varying first)
- **globalStrides**: 2-element array of byte strides (the innermost dimension's stride is implicit)
- **boxDim**: 3-element array specifying the transfer tile shape

The 3D mapping reshapes a 2D K-major global matrix `[M, K]` to match the strip-based shared memory organization. The innermost dimension corresponds to elements within one strip width; the middle dimension corresponds to rows; the outermost dimension indexes strips across the K dimension.
