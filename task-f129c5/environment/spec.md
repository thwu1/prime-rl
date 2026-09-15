# ALP Compression Specification

## Overview

ALP (Adaptive Lossless floating-Point Compression) encodes IEEE 754 double-precision
floating-point values as integers by finding multiplier/divisor exponent pairs that
minimize information loss. Values that cannot be losslessly encoded are stored as
"patches" (exceptions). The scheme is inspired by the ALP paper by Afroozeh et al.

## Constants

- `CHUNK_SIZE = 1024` — values per chunk for patch indexing
- `MAX_E = 18` — maximum exponent for f64 (since 10^18 < 2^63)
- `FACT[e] = 10.0 ** e` for e in [0, 18] — encoding multipliers (precomputed as f64)
- `FRAC[f] = 10.0 ** (-f)` for f in [0, 18] — decoding multipliers (precomputed as f64)
- `I64_MAX = 2^63 - 1`, `I64_MIN = -2^63` — signed 64-bit integer bounds

**Important**: `FRAC[f]` is computed as `10.0 ** (-f)`, NOT as `1.0 / (10.0 ** f)`.
The decode step uses multiplication by `FRAC[f]`, NOT division by `FACT[f]`.

## Algorithm

### 1. Exponent Pair Discovery

Given input values:

1. Collect all values that are not `None`, not `NaN`, and not `±Inf` into a list called `candidates`.
2. If `candidates` is empty, use `(e, f) = (0, 0)`.
3. Otherwise, sample up to 32 evenly-spaced values from `candidates`:
   - If `len(candidates) <= 32`, use all of them as the sample.
   - Otherwise: compute `step = len(candidates) / 32`, and take
     `candidates[int(i * step)]` for `i` in `0..31`.
4. For each pair `(e, f)` where `0 <= f <= e <= 18`, iterating in order
   `e = 0, 1, ..., 18` and for each `e`, `f = 0, 1, ..., e`:
   - Count how many sample values are exceptions (see Section 2).
5. Choose the first `(e, f)` pair with the minimum exception count.
   The iteration order ensures that ties are broken by smallest `e`,
   then smallest `f`.

### 2. Exception Check

A value `v` is an **exception** for exponents `(e, f)` if ANY of:

- `v` is `NaN` or `±Inf`
- The product `v * FACT[e]` is not finite
- `round(v * FACT[e])` falls outside `[I64_MIN, I64_MAX]`
- `v` is not bitwise-equal to `round(v * FACT[e]) * FRAC[f]`

**Bitwise equality** means `struct.pack('<d', a) == struct.pack('<d', b)`.
This distinguishes `0.0` from `-0.0` and handles `NaN` correctly.

Note: `-0.0` is always an exception because the encoding loses the sign
(integer `0` decodes to `+0.0`).

### 3. Encoding

For each value at index `i`:

- If value is `None` (null): record `i` in the null index set; store `0` as the
  encoded integer placeholder.
- If value is an exception: record `(i, original_value)` as a patch (sorted by
  index); store `0` as the encoded integer placeholder.
- Otherwise: `encoded_int[i] = round(value * FACT[e])`.

### 4. Frame-of-Reference (FOR)

- `for_base = min(encoded_int[i])` over all indices `i` that are neither null
  nor patched.
- If no such indices exist: `for_base = 0`.
- For non-null, non-patch index `i`: `for_adjusted[i] = encoded_int[i] - for_base`.
- For null/patch index `i`: `for_adjusted[i] = 0`.

All `for_adjusted` values are guaranteed non-negative.

### 5. Bit Width

- `bit_width = max(for_adjusted).bit_length()` (Python `int.bit_length()` method)
- If the maximum is `0` (constant column or all patches/nulls): `bit_width = 0`.

### 6. Bit-Packing

Pack the `for_adjusted` values into a byte array:

- Each value uses exactly `bit_width` bits.
- Values are written sequentially; within each value, bit 0 (LSB) is written
  first.
- Bits fill bytes from bit 0 (LSB) upward. When a byte is full, continue into
  the next byte.
- Total bytes: `ceil(num_values * bit_width / 8)`.
- If `bit_width == 0`, this section has zero bytes.

### 7. Chunk Offsets

- `num_chunks = ceil(num_values / CHUNK_SIZE)`.
- The `chunk_offsets` array has `num_chunks + 1` entries.
- `chunk_offsets[0] = 0`.
- `chunk_offsets[k]` = total number of patches in chunks `0` through `k-1`.
- A patch at index `i` belongs to chunk `i // CHUNK_SIZE`.

### 8. Null Bitmap

- Present only if any value is `None`.
- Size: `ceil(num_values / 8)` bytes.
- Bit `i` of byte `i // 8` is set (1) if value at index `i` is null.
- Bit position within each byte: `i % 8` (bit 0 = LSB).

## Binary Format

The compressed output is a single byte sequence with this layout:

```
[Header: 32 bytes]
[Null bitmap: 0 or ceil(N/8) bytes]
[Bit-packed integers: ceil(N * bit_width / 8) bytes]
[Patches: num_patches * 16 bytes]
[Chunk offsets: (num_chunks + 1) * 4 bytes]
```

### Header (32 bytes, all little-endian)

| Offset | Size | Type   | Field                               |
|--------|------|--------|-------------------------------------|
| 0      | 4    | bytes  | Magic: `b"ALP1"`                    |
| 4      | 8    | u64 LE | `num_values`                        |
| 12     | 1    | u8     | `e` (encoding exponent)             |
| 13     | 1    | u8     | `f` (decoding exponent)             |
| 14     | 1    | u8     | `bit_width`                         |
| 15     | 8    | i64 LE | `for_base` (signed)                 |
| 23     | 4    | u32 LE | `num_patches`                       |
| 27     | 2    | u16 LE | `num_chunks`                        |
| 29     | 1    | u8     | `flags` (bit 0 = has_nulls)         |
| 30     | 2    | bytes  | reserved (must be `0x0000`)         |

### Null Bitmap

Present only if flag bit 0 (`has_nulls`) is set.
`ceil(num_values / 8)` bytes. Bit `i` of byte `i // 8` equals
`(byte >> (i % 8)) & 1`. A set bit means the value at that index is null.

### Bit-Packed Integers

`num_values` values, each `bit_width` bits wide, packed LSB-first into bytes.
If `bit_width` is 0, this section is empty (0 bytes).

### Patches

`num_patches` entries, each 16 bytes:
- 8 bytes: index (`u64 LE`)
- 8 bytes: value (`f64 LE`, raw IEEE 754 representation)

Patches are sorted by index in ascending order.

### Chunk Offsets

`num_chunks + 1` entries, each 4 bytes (`u32 LE`).
Entry `k` is the cumulative count of patches in chunks 0 through k-1.

## Decoding

1. Parse the 32-byte header.
2. Read the null bitmap (if present) to identify null positions.
3. Unpack bit-packed integers into `for_adjusted` values.
4. Read patches into an index-to-value map.
5. For each position `i` from 0 to `num_values - 1`:
   - If null: output `None`
   - If patched: output the stored patch value
   - Otherwise: output `(for_adjusted[i] + for_base) * FRAC[f]`

## API

```python
def alp_compress(values: list[float | None]) -> bytes:
    """Compress f64 values to ALP binary format."""

def alp_decompress(data: bytes) -> list[float | None]:
    """Decompress ALP binary data to original values."""
```

The module must be importable as:
```python
from alp import alp_compress, alp_decompress
```
