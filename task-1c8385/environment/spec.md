# BFloat16 Floating-Point Arithmetic Specification

## Format

bfloat16 is a 16-bit floating-point format with the following layout (MSB first):

| Field | Bits | Width |
|-------|------|-------|
| Sign (S) | 15 | 1 |
| Biased exponent (E) | 14-7 | 8 |
| Trailing significand / mantissa (T) | 6-0 | 7 |

- Exponent bias: **127**
- Precision (p): **8** (7 stored mantissa bits + 1 implicit hidden bit)

## Value Encoding

| Exponent (E) | Mantissa (T) | Interpretation |
|---|---|---|
| 0 | 0 | **Zero**: `(-1)^S * 0` (signed zero) |
| 0 | != 0 | **Subnormal**: `(-1)^S * T * 2^(-133)` |
| 1..254 | any | **Normal**: `(-1)^S * (128 + T) * 2^(E - 134)` |
| 255 | 0 | **Infinity**: `(-1)^S * Inf` |
| 255 | != 0 | **NaN** (canonical quiet NaN raw value: `0x7FC0`) |

### Key Constants (hex raw values)

| Name | Hex | Value |
|------|-----|-------|
| +0 | 0x0000 | positive zero |
| -0 | 0x8000 | negative zero |
| +Inf | 0x7F80 | positive infinity |
| -Inf | 0xFF80 | negative infinity |
| qNaN | 0x7FC0 | canonical quiet NaN |
| max normal | 0x7F7F | (255/128) * 2^127 |
| min normal | 0x0080 | 2^(-126) |
| min subnormal | 0x0001 | 2^(-133) |
| max subnormal | 0x007F | 127 * 2^(-133) |

## Rounding Modes

Five IEEE 754 rounding modes must be supported, identified by string keys:

- **"RNE"**: Round to nearest, ties to even (default). If the value is exactly halfway between two representable numbers, choose the one whose least significant mantissa bit is 0.
- **"RNA"**: Round to nearest, ties away from zero. If exactly halfway, choose the one with larger magnitude.
- **"RZ"**: Round toward zero. Always truncate magnitude (never round away from zero).
- **"RU"**: Round toward +infinity. Positive inexact results round up; negative inexact results truncate.
- **"RD"**: Round toward -infinity. Negative inexact results round up in magnitude; positive inexact results truncate.

## Operation Semantics

### Addition (`bf16_add(a, b, rm)`)

Special-value rules (checked in order):
1. If either operand is NaN: return canonical NaN (`0x7FC0`)
2. Inf + Inf (same sign): return that Inf
3. Inf + (-Inf): return NaN
4. Inf + finite: return that Inf
5. Both zero: same sign -> that zero; opposite signs -> +0 (or -0 under RD)
6. One zero: return the other operand
7. Otherwise: compute the exact sum of the two values, then round to bfloat16 using the specified rounding mode
8. If the exact result is zero (cancellation): return +0 (or -0 under RD)

### Multiplication (`bf16_mul(a, b, rm)`)

The sign of the result is always `sign_a XOR sign_b` (for non-NaN results).

Special-value rules (checked in order):
1. If either operand is NaN: return canonical NaN
2. Inf * 0: return NaN
3. Inf * nonzero-finite: return signed Inf
4. Zero * finite: return signed zero
5. Otherwise: compute the exact product, then round to bfloat16

### Overflow

When the rounded result would exceed the maximum finite bfloat16 value:
- **RNE, RNA**: return signed infinity
- **RZ**: return signed max-finite (clamp)
- **RU**: positive overflow -> +Inf, negative overflow -> -max-finite
- **RD**: positive overflow -> +max-finite, negative overflow -> -Inf

### Underflow

When the result magnitude is below the minimum normal:
- Use subnormal encoding if representable
- Apply rounding rules to decide between zero and minimum subnormal for values below minimum subnormal
