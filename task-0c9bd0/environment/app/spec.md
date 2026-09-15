# FP8_E4M3 Format Specification

## Format

- 8 bits total: `[sign:1][exponent:4][mantissa:3]`
- Exponent bias: 7
- Precision: 4 (3 stored mantissa bits + 1 hidden bit)

## Bit Layout (MSB to LSB)

```
S EEEE MMM
```

- **S** (bit 7): sign bit
- **E** (bits 6-3): biased exponent field, 4 bits
- **M** (bits 2-0): trailing mantissa (significand) field, 3 bits

Raw byte: `raw = (S << 7) | (E << 3) | M`

## Value Interpretation

### Normal numbers (E in [1, 14])

```
value = (-1)^S * 2^(E - 7) * (1 + M/8)
```

### Subnormal numbers (E = 0, M != 0)

```
value = (-1)^S * 2^(-6) * (M/8)
```

The hidden bit is 0 instead of 1. This provides gradual underflow:
the gap between zero and the smallest normal is filled with evenly
spaced subnormal values.

### Zero (E = 0, M = 0)

- `+0.0` when S=0 (raw = 0x00)
- `-0.0` when S=1 (raw = 0x80)

### Infinity (E = 15, M = 0)

- `+Inf` when S=0 (raw = 0x78)
- `-Inf` when S=1 (raw = 0xF8)

### NaN (E = 15, M != 0)

Any non-zero mantissa with all exponent bits set.
Canonical qNaN: raw = 0x79.

## Key Values

| Description | Raw (hex) | Decimal Value |
|---|---|---|
| +0 | 0x00 | 0.0 |
| -0 | 0x80 | -0.0 |
| Smallest positive subnormal | 0x01 | 1/512 = 0.001953125 |
| Largest positive subnormal | 0x07 | 7/512 = 0.013671875 |
| Smallest positive normal | 0x08 | 1/64 = 0.015625 |
| 1.0 | 0x38 | 1.0 |
| Largest positive normal | 0x77 | 240.0 |
| +Infinity | 0x78 | +Inf |
| Canonical NaN | 0x79 | NaN |

## Rounding Modes

- **RNE**: Round to nearest, ties to even (default IEEE 754 mode)
- **RNA**: Round to nearest, ties away from zero
- **RU**: Round toward +Infinity
- **RD**: Round toward -Infinity
- **RZ**: Round toward zero (truncation)

### Overflow Behavior by Rounding Mode

When the exact result exceeds the largest representable finite value:

| Mode | Positive overflow | Negative overflow |
|---|---|---|
| RNE | +Inf | -Inf |
| RNA | +Inf | -Inf |
| RU | +Inf | -max_normal |
| RD | +max_normal | -Inf |
| RZ | +max_normal | -max_normal |

Note: RZ can never produce infinity from overflow. RU cannot produce
-Inf from overflow. RD cannot produce +Inf from overflow.

## Required API

### `FP8(raw: int)`
Construct from raw 8-bit integer representation.

### `FP8.from_real(value: float, rounding: str = 'RNE') -> FP8`
Convert a Python float to FP8 with the specified rounding mode.
Must handle NaN, Inf, signed zeros, overflow, and underflow.

### `FP8.to_real() -> float`
Convert FP8 to Python float. Must preserve signed zero semantics.

### `fp8_add(a: FP8, b: FP8, rounding: str = 'RNE') -> FP8`
IEEE 754 compliant addition.

### `fp8_mul(a: FP8, b: FP8, rounding: str = 'RNE') -> FP8`
IEEE 754 compliant multiplication.

### `fp8_fma(a: FP8, b: FP8, c: FP8, rounding: str = 'RNE') -> FP8`
Fused multiply-add: computes `a * b + c` with a **single** rounding
step at the end. The intermediate product `a * b` must be kept at
full precision before addition with `c`.

### `fp8_classify(a: FP8) -> str`
Returns one of: `'normal'`, `'subnormal'`, `'zero'`, `'infinity'`, `'nan'`

### `fp8_compare(a: FP8, b: FP8) -> Optional[int]`
Returns `-1` (a < b), `0` (a == b), `1` (a > b), or `None` (unordered).
`+0.0` and `-0.0` compare as equal. Any comparison involving NaN is unordered.

## IEEE 754 Compliance Requirements

- **NaN propagation**: any operation with a NaN operand produces NaN
- **Infinity arithmetic**: Inf + (-Inf) = NaN; Inf + Inf = Inf; Inf + finite = Inf
- **Signed zero rules**: `x - x = +0` in all rounding modes except RD where `x - x = -0`
- **Zero addition**: `(+0) + (-0) = +0` except under RD where it equals `-0`
- **Gradual underflow**: subnormals fill the gap between zero and smallest normal
- **Invalid operations**: `0 * Inf = NaN`
- **FMA semantics**: single rounding means FMA can produce different results from separate mul-then-add
