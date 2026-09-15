# defmt Wire Format Specification

This document describes the binary wire format used by the `defmt` logging framework.

## 1. Frame Structure

Each binary log frame has the following layout:

```
[frame_index: u16 LE] [timestamp_args...] [message_args...]
```

- **frame_index**: A 16-bit little-endian unsigned integer indexing into the string table. This identifies the top-level format string and log level.
- **timestamp_args**: If the string table includes a timestamp entry, the timestamp's format string arguments are decoded next (before the message arguments).
- **message_args**: The arguments for the message format string, decoded according to the format string's parameter types.

## 2. String Table

The string table maps integer indices to entries. Each entry has:

- **tag**: Identifies the entry type and log level. Tags with associated log levels:
  - `Trace` → `TRACE`, `Debug` → `DEBUG`, `Info` → `INFO`, `Warn` → `WARN`, `Error` → `ERROR`
  - Other tags (`Derived`, `Prim`, `Write`, `Str`, `Println`, `Timestamp`) are non-level entries used for nested formats, primitives, interned strings, etc.
- **format**: The format string for this entry.

An optional **timestamp** entry provides a format string whose arguments appear at the start of every frame (after the frame index).

## 3. Output Format

The decoded output for each frame is:

```
[timestamp_formatted ] [LEVEL ] message_formatted
```

- If a timestamp is defined, its formatted value is printed first, followed by a space.
- If the frame's tag has an associated level, the level name (e.g., `INFO`) is printed, followed by a space.
- The formatted message follows.

## 4. Format String Syntax

Format strings contain literal text interspersed with format parameters enclosed in `{` and `}`:

```
param := '{' [ argument ] [ '=' type ] [ ':' hint ] '}'
argument := integer           // explicit argument index
type := <see Type Specifiers>
hint := [ zero_pad ] [ '#' ] hint_type
zero_pad := '0' digits        // e.g., '04' means zero-pad to width 4
hint_type := 'x' | 'X' | 'b' | 'o' | 'a' | '?' | 'us' | 'ms'
           | 'iso8601ms' | 'iso8601us' | 'iso8601s'
```

### Escaped Braces

`{{` in a format string produces a literal `{` in the output. `}}` produces a literal `}`.

### Argument Index Assignment

- Parameters without an explicit index are assigned indices sequentially starting from 0, in order of appearance.
- Parameters WITH an explicit index do NOT advance the auto-index counter.
- Multiple parameters may reference the same argument index; the argument data is read only once.

### Default Type

When no `=type` is specified (e.g., `{:b}` or `{}`), the default type is `?` (Format).

## 5. Type Specifiers and Binary Encoding

Arguments are serialized in the order of their indices (index 0 first, then index 1, etc.), NOT in the order they appear in the format string. Each unique argument index corresponds to exactly one read from the binary data.

| Type | Encoding | Size |
|------|----------|------|
| `u8` | unsigned 8-bit | 1 byte |
| `u16` | unsigned 16-bit LE | 2 bytes |
| `u32` | unsigned 32-bit LE | 4 bytes |
| `u64` | unsigned 64-bit LE | 8 bytes |
| `u128` | unsigned 128-bit LE | 16 bytes |
| `i8` | signed 8-bit (two's complement) | 1 byte |
| `i16` | signed 16-bit LE | 2 bytes |
| `i32` | signed 32-bit LE | 4 bytes |
| `i64` | signed 64-bit LE | 8 bytes |
| `i128` | signed 128-bit LE | 16 bytes |
| `bool` | `0x00` = false, `0x01` = true | 1 byte |
| `char` | Unicode code point as u32 LE | 4 bytes |
| `str` | u32 LE length + UTF-8 bytes | 4 + N bytes |
| `[u8]` | u32 LE length + raw bytes | 4 + N bytes |
| `?` (Format) | u16 LE sub-index + recursive args | variable |
| `[?]` (FormatSlice) | u32 LE count + count × (u16 LE index + recursive args) | variable |
| `__internal_FormatSequence` | repeated (u16 LE index + args) until index = 0 | variable |
| `N..M` (BitField) | see Bitfield section | variable |

### Format (`?`)

Reads a u16 LE sub-index from the binary data, looks up the corresponding format string in the string table, then recursively decodes arguments for that format string from the remaining binary data.

### FormatSlice (`[?]`)

Reads a u32 LE element count, then for each element: reads a u16 LE format index and recursively decodes that format's arguments. Output: elements are formatted individually, joined with `", "`, and enclosed in `[` and `]`.

### FormatSequence (`__internal_FormatSequence`)

Reads pairs of (u16 LE format index + recursive args) until a u16 LE index of `0` is encountered (the terminator). The terminator index `0` is NOT decoded as an element. Output: elements are formatted and concatenated directly (no separator, no brackets).

## 6. Bitfield Encoding

Bitfield parameters use the type syntax `start..end` where `start` and `end` are bit positions (0-indexed, `start` inclusive, `end` exclusive).

Multiple parameters may share the same argument index with different bit ranges. The binary data for a bitfield argument is read as follows:

1. Compute the overall bit range across all parameters sharing the same index:
   - `min_bit` = minimum start across all bitfield ranges for this index
   - `max_bit` = maximum end across all bitfield ranges for this index
2. Compute the byte range:
   - `min_byte` = `min_bit // 8`
   - `max_byte` = `(max_bit - 1) // 8`
3. Read `(max_byte - min_byte + 1)` bytes from the binary data.
4. Interpret the bytes as a little-endian unsigned integer.
5. Shift the value left by `(min_byte * 8)` bits to place it at the correct position in a 128-bit value.

To extract bits for a specific range `start..end` from the 128-bit value `x`:

```
left_zeroes = 128 - end
right_zeroes = left_zeroes + start
extracted = (x << left_zeroes) >> right_zeroes
```

(All operations are in unsigned 128-bit arithmetic with overflow truncation.)

## 7. Display Hints

Display hints control how values are formatted in the output.

### Hint Parsing

A hint string after `:` is parsed as:
1. Optional zero-pad: literal `0` followed by one or more digits (e.g., `04` means width 4)
2. Optional alternate flag: `#`
3. Hint type: the remaining string

### Unsigned Integer Formatting

| Hint | Format | Example (value=42) |
|------|--------|--------------------|
| (none) | decimal | `42` |
| `x` | lowercase hex | `2a` |
| `X` | uppercase hex | `2A` |
| `#x` | alt lowercase hex | `0x2a` |
| `#X` | alt uppercase hex | `0x2A` |
| `b` | binary | `101010` |
| `#b` | alt binary | `0b101010` |
| `o` | octal | `52` |
| `#o` | alt octal | `0o52` |

**Note on alternate hex**: The prefix is always lowercase `0x`, even for uppercase hex (`#X`). Only the hex digits change case.

**Zero-padding**: The zero_pad value specifies the minimum total width of the output (including any prefix for alternate forms). Values shorter than this width are left-padded with `0`.

Examples with zero_pad=4:
- `{=u8:04x}` with value 5 → `0005`
- `{=u8:#06x}` with value 5 → `0x0005`

**NoHint with zero-pad**: `{=u8:03}` with value 5 → `005` (decimal, width 3)

### Signed Integer Formatting

For hex, binary, and octal hints on signed integers, the value is displayed using its two's complement unsigned representation at the type's bit width:

- `i8` → 8-bit, `i16` → 16-bit, `i32` → 32-bit, `i64` → 64-bit, `i128` → 128-bit

Example: `{=i16:#x}` with value -1 → `0xffff`

For decimal (no hint), signed integers display with a minus sign: `-1`.

### Timestamp Hints

| Hint | Semantics | Example |
|------|-----------|---------|
| `us` | Value is microseconds. Display as `seconds.micros` where micros is zero-padded to 6 digits | `1500000` → `1.500000` |
| `ms` | Value is milliseconds. Display as `seconds.millis` where millis is zero-padded to 3 digits | `1500` → `1.500` |
| `iso8601ms` | Value is milliseconds since Unix epoch. Display as ISO 8601 with 3-digit fractional seconds | `1618910624804` → `2021-04-20T09:23:44.804Z` |
| `iso8601us` | Value is microseconds since Unix epoch. Display as ISO 8601 with 6-digit fractional seconds | |
| `iso8601s` | Value is seconds since Unix epoch. Display as ISO 8601 with no fractional part | |

### Byte Slice Display Hints

When a byte slice (`[u8]`) has a display hint:

- **Hex/Binary/Octal**: Each byte is formatted individually with the hint, joined by `", "`, enclosed in `[` and `]`. Example: `{=[u8]:x}` with `[171, 205]` → `[ab, cd]`
- **No hint**: Default debug format: `[171, 205]`

### Debug Hint (`?`)

The `?` hint means "use the parent format's hint." When a parameter has hint `?`:
- If the parameter is a value type (u8, u16, etc.), format it using the hint inherited from the enclosing format's parameter.
- If no parent hint exists, format as decimal (default).

### Hint Propagation Through Nested Formats

When a `Format` (`?`) argument is encountered:
- The effective hint of the current parameter becomes the `parent_hint` for the nested format's arguments.
- Inside the nested format, parameters with hint `?` (Debug) will use this propagated parent hint.

Example:
- Outer: `"x={:b}"` — parameter has type=Format, hint=binary
- Inner: `"S {{ x: {=u8:?} }}"` — u8 parameter has hint=Debug
- The Debug hint causes the u8 to be formatted with the parent's binary hint
- Result: `x=S { x: 101010 }` (42 in binary)

### Bool Formatting

`true` or `false` (lowercase).

### Char Formatting

The Unicode character itself (e.g., `💜`).

### String Formatting

The string value is inserted directly. With hint `?` (Debug), the string is quoted: `"value"`.
