# NUMDATA1 Binary Format Specification

## File Layout

| Offset | Size    | Description                                        |
|--------|---------|----------------------------------------------------|
| 0      | 8       | Magic bytes: ASCII `NUMDATA1`                      |
| 8      | 4       | Record count N (uint32, little-endian)             |
| 12     | varies  | N sequential records, no inter-record padding      |

## Record Types

Each record starts with a 1-byte unsigned type tag, immediately followed by the
type-specific payload. There is no alignment padding between records.

### Type 0x01 — Raw IEEE 754 binary64

**Payload**: 8 bytes representing an IEEE 754 binary64 (double-precision)
floating-point value in **little-endian** byte order.

### Type 0x02 — Decimal ASCII String

**Payload**: a 2-byte string length L (uint16, little-endian), followed by
exactly L bytes of ASCII text. No null terminator is present.

The text encodes a decimal floating-point number using standard syntax:
an optional sign (`+` or `-`), a sequence of decimal digits with an optional
decimal point, and an optional exponent part (`e` or `E`, optional sign,
decimal digits). Examples: `3.14`, `-0.001`, `1.23e-10`, `1E10`, `0.0`, `-0.0`.

### Type 0x03 — Base64-Encoded binary64

**Payload**: a 2-byte encoded length L (uint16, little-endian), followed by L
bytes of standard Base64 text (RFC 4648 alphabet `A-Za-z0-9+/` with `=`
padding).

Decoding the Base64 text always yields exactly 8 bytes, which represent an
IEEE 754 binary64 value in **little-endian** byte order.

### Type 0x04 — Hexadecimal Floating-Point String

**Payload**: a 2-byte string length L (uint16, little-endian), followed by L
bytes of ASCII text in C99 hexadecimal floating-point format. No null
terminator.

Format: `[sign] 0x hex_digits . hex_digits p [sign] decimal_exponent`

Examples: `0x1.921fb54442d18p+1` (pi), `-0x1.0p+0` (-1.0), `0x0.0p+0` (0.0).

### Type 0x05 — Scaled Integer (Fixed-Point)

**Payload**: 9 bytes total.

| Sub-field | Bytes | Encoding                                           |
|-----------|-------|----------------------------------------------------|
| mantissa  | 8     | Signed 64-bit integer, **big-endian** two's complement |
| scale     | 1     | Unsigned 8-bit integer                             |

The represented floating-point value is computed as:

    value = mantissa * 10^(-scale)

using IEEE 754 binary64 arithmetic (i.e., convert the integer mantissa to
`double`, compute `pow(10.0, -scale)` as a `double`, and multiply).

For example, mantissa = 314159 with scale = 5 yields 3.14159.

**Important**: the mantissa field uses **big-endian** byte order, which differs
from the little-endian convention used by all other multi-byte integer fields
in this format.
