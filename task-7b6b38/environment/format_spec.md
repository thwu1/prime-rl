
# QFormat v1.1 — Quantized Model Binary Format Specification

## Overview

This document specifies the binary formats for weight, scale, and zero-point
files used by a multi-layer neural network with INT4 group-quantized weights.
The model uses asymmetric per-group quantization with unsigned 4-bit integers
(values 0–15).

## Model Configuration

Model architecture, per-layer quantization parameters, and calibration metadata
are stored in an SQLite database (`calibration.db`) within the model directory.
There is no JSON metadata file. Query the database to determine layer
dimensions, quantization parameters, weight container types, activation
functions, and any calibration corrections that must be applied.

## Inference Pipeline

Layers are applied sequentially (layer 0 first). Each linear layer computes:

    output = input @ W_dequantized.T

followed by the per-layer activation function specified in the database:
- `relu`: max(0, x)
- `gelu`: GELU with tanh approximation:
  `0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))`
- `none`: identity (no activation)

## Dequantization Formula

For each weight element at position `[row, col]`:

    group_index = col // group_size
    float_value = scale[row, group_index] * (quant_value[row, col] - zero_point[row, group_index])

## Weight Storage Containers

Weight data may be stored in different container formats as indicated by the
`weight_container` field in the database:

- **`raw`**: Weight data stored directly in a `.qweight` binary file (format below).
- **`elf`**: Weight data embedded as a named section in an ELF relocatable
  object file (`.o`). The section name is specified in the layer's `notes` field
  in the database. The section contains the same binary format as a `.qweight`
  file. Use binary tools (e.g., `objcopy`, `readelf`) to extract the data.

## Quantized Weight Binary Format

### Header (12 bytes)

| Offset | Size | Type   | Description               |
|--------|------|--------|---------------------------|
| 0      | 4    | uint32 | num_rows (= out_features) |
| 4      | 4    | uint32 | num_cols (= in_features)  |
| 8      | 4    | uint32 | group_size                |

### Data

Row-major array of uint32 values, each containing 8 packed INT4 weight values.
- uint32 values per row: `num_cols / 8`
- Total data bytes: `num_rows * (num_cols / 8) * 4`

### Packing Methods

Three weight packing methods are supported. The `packing_mode` field selects
which method is used. **The mapping from mode number (0, 1, 2) to method
(A, B, C) is implementation-defined and must be determined empirically.**
Use the diagnostic data at `/app/known_weights/` to resolve the mapping.

**Method A — Sequential Packing:**

Values at column offsets 0–7 within each packed uint32 are stored sequentially:

| Bit Range | Value Index |
|-----------|-------------|
| [3:0]     | 0           |
| [7:4]     | 1           |
| [11:8]    | 2           |
| [15:12]   | 3           |
| [19:16]   | 4           |
| [23:20]   | 5           |
| [27:24]   | 6           |
| [31:28]   | 7           |

**Method B — Even-Odd Interleaved Packing:**

Even-indexed values occupy the lower 16 bits; odd-indexed values occupy the
upper 16 bits:

| Bit Range | Value Index | Category     |
|-----------|-------------|--------------|
| [3:0]     | 0           | even (lower) |
| [7:4]     | 2           | even (lower) |
| [11:8]    | 4           | even (lower) |
| [15:12]   | 6           | even (lower) |
| [19:16]   | 1           | odd (upper)  |
| [23:20]   | 3           | odd (upper)  |
| [27:24]   | 5           | odd (upper)  |
| [31:28]   | 7           | odd (upper)  |

**Method C — Bit-Plane Transposed Packing:**

The 32-bit word is divided into four byte-sized regions, one per bit-plane.
Each byte holds one complete bit-plane across all 8 values. Bit-planes are
ordered from least significant to most significant. Within each byte,
individual bits correspond to value indices. Use diagnostic reference data
to verify your implementation of this method.

## Scale Factor Files: layer_N.scales

### Header (8 bytes)

| Offset | Size | Type   | Description        |
|--------|------|--------|--------------------|
| 0      | 4    | uint32 | num_rows           |
| 4      | 4    | uint32 | num_groups_per_row |

### Data

Encoding depends on `scale_dtype` in the database:
- `"float32"`: 4-byte IEEE 754 single-precision per scale
- `"float16"`: 2-byte IEEE 754 half-precision per scale

Layout: row-major, `scales[row][group]`.

**Important:** Scale files may contain corrupted values from the export
process. Consult the database for calibration notes and corrections.

## Zero-Point Files: layer_N.zeros

### Header (8 bytes)

| Offset | Size | Type   | Description        |
|--------|------|--------|--------------------|
| 0      | 4    | uint32 | num_rows           |
| 4      | 4    | uint32 | num_groups_per_row |

### Data

Row-major uint32 values, each containing up to 8 packed INT4 zero-point values
using **sequential packing** (Method A). Zero-points always use sequential
packing regardless of the layer's weight `packing_mode`.
- uint32 values per row: `ceil(num_groups_per_row / 8)`
- Unused positions in the last uint32 are zero-padded.

## General Notes

- All multi-byte values are stored in **little-endian** byte order.
- Weight values are unsigned 4-bit integers in range [0, 15].
- Zero-point values are unsigned 4-bit integers in range [0, 15].
