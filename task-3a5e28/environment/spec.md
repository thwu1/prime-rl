# defmt Wire Format Specification

## Overview

defmt (deferred formatting) is a compact binary logging framework for resource-constrained embedded systems. Log messages are encoded as minimal binary frames on-device, with format strings stored in a separate string table. This document describes the binary wire format used to decode these frames on the host side.

## String Table

The string table (`string_table.json`) maps numeric indices to entries. Each entry has:

- **tag**: The entry type. Log-level tags (`Info`, `Debug`, `Warn`, `Error`, `Trace`) produce top-level log frames. `Derived` entries are referenced by nested Format arguments. `Timestamp` defines the global timestamp format.
- **string**: A format string containing literal text and parameter placeholders.

## Frame Structure (Raw Encoding)

Frames are concatenated back-to-back with no delimiters or length prefixes. The decoder must consume exactly the right number of bytes per frame based on the format string's type information.

Each frame consists of:

1. **Frame index** — `u16` little-endian. Looks up the format string and tag in the string table.
2. **Timestamp arguments** — Decoded according to the timestamp entry's format string (if a timestamp entry exists).
3. **Message arguments** — Decoded according to the looked-up format string.

Arguments are read in order of their **argument index** (0, 1, 2, ...), not in order of appearance in the format string. Each unique argument index is read exactly once from the wire.

## Format String Syntax

Format strings contain literal text intermixed with parameter placeholders enclosed in `{` `}`:

```
{[index][=type][:hint]}
```

- **index** (optional): Explicit argument index (integer). If omitted, indices are assigned sequentially starting from 0.
- **type** (optional, after `=`): Specifies the wire type. Defaults to `?` (Format) if omitted.
- **hint** (optional, after `:`): Display formatting hint.

Escaped braces: `{{` produces literal `{`, `}}` produces literal `}`.

Parameters with the same explicit index share one wire value (read once, used at each occurrence).

### Supported Types

| Type Specifier | Description | Wire Size (bytes) | Byte Order |
|---|---|---|---|
| `u8` | Unsigned 8-bit | 1 | — |
| `u16` | Unsigned 16-bit | 2 | Little-endian |
| `u32` | Unsigned 32-bit | 4 | Little-endian |
| `u64` | Unsigned 64-bit | 8 | Little-endian |
| `i8` | Signed 8-bit | 1 | — |
| `i16` | Signed 16-bit (two's complement) | 2 | Little-endian |
| `i32` | Signed 32-bit (two's complement) | 4 | Little-endian |
| `f32` | IEEE 754 float | 4 | Little-endian |
| `bool` | Boolean | 1 | 0=false, 1=true |
| `char` | Unicode scalar value | 4 | Little-endian (as u32) |
| `str` | UTF-8 string | 4 (length as u32 LE) + N bytes | — |
| `[u8]` | Byte slice | 4 (length as u32 LE) + N bytes | — |
| `?` | Nested Format (see below) | Variable | — |
| `start..end` | Bitfield (see below) | Depends on range | — |

### Nested Format (`{=?}`)

When the type is `?`:
1. Read a `u16` LE index from the wire.
2. Look up the format string for that index in the string table.
3. Recursively decode arguments according to that nested format string.
4. The result is the fully formatted text of the nested type.

### Bitfields (`{index=start..end:hint}`)

Bitfield parameters extract a range of bits `[start, end)` from an integer argument (LSB = bit 0).

Multiple bitfield parameters sharing the same argument index are backed by a single wire value. To determine what to read:
1. Across all bitfield parameters for the same argument index, find the maximum `end` value.
2. Choose the smallest integer type that fits: end ≤ 8 → u8, end ≤ 16 → u16, end ≤ 32 → u32, end ≤ 64 → u64.
3. Read that integer type once from the wire.

To extract bits `[start, end)` from value `V`:
```
result = (V >> start) & ((1 << (end - start)) - 1)
```

## Display Hints

Display hints follow `:` in the parameter specifier and control output formatting:

| Hint | Applies To | Output |
|---|---|---|
| *(none)* | integers | Decimal |
| `x` | integers | Lowercase hex (no prefix) |
| `X` | integers | Uppercase hex (no prefix) |
| `#x` | integers | Lowercase hex with `0x` prefix |
| `#0Nx` | integers | `0x`-prefixed hex, zero-padded to N total characters |
| `b` | integers | Binary (no prefix) |
| `#b` | integers | Binary with `0b` prefix |
| `a` | `[u8]` | ASCII byte string (see below) |
| `x` | `[u8]` | Hex byte list `[hh, hh, ...]` |
| `us` | integers | Microsecond timestamp (see below) |

### Microsecond Timestamp (`us`)

Formats an integer as `{seconds}.{microseconds:06}` where:
- `seconds = value / 1_000_000`
- `microseconds = value % 1_000_000` (zero-padded to 6 digits)

### Hex/Binary Zero-Padding

`#0Nx` means: format in hex with `0x` prefix, zero-padded so the **total** output width (including `0x`) is at least N characters. Same pattern applies to `#0Nb` and `0Nx` (without prefix).

### ASCII Byte String Display (`a` hint on `[u8]`)

Formats as a Rust byte string literal `b"..."`:
- Printable ASCII graphic characters (0x21–0x7E, excluding `"` and `\`) → literal character
- Space (0x20) → literal space
- Tab (0x09) → `\t`
- Newline (0x0A) → `\n`
- Carriage return (0x0D) → `\r`
- Double quote (0x22) → `\"`
- Backslash (0x5C) → `\\`
- All other bytes → `\xNN` (lowercase hex, always 2 hex digits)

### Hex Display on `[u8]` Slices

Each byte is formatted individually with the hex hint, separated by `, `, enclosed in `[` `]`. Example: `[de, ad, be, ef]`.

## Float Formatting

`f32` values are formatted using the shortest decimal representation that uniquely identifies the original float value (equivalent to Rust's `ryu` library). For values that are exact decimal fractions (e.g., 1.5, 0.25), this produces the short form.

## Output Format

Each decoded frame produces one output line:

```
{timestamp} {LEVEL} {message}
```

- **timestamp**: Formatted according to the timestamp entry's format string and hints.
- **LEVEL**: Uppercase level name derived from the entry's tag: `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`.
- **message**: The fully formatted message with all arguments interpolated.

Only entries with log-level tags (Trace/Debug/Info/Warn/Error) produce output lines. `Derived` entries are internal types referenced by nested Format arguments.
