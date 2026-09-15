# Binary Protocol Specification

This document describes the two-layer binary protocol used to encode the telemetry messages in `telemetry.bin`.

## Layer 1: COBS Framing (Consistent Overhead Byte Stuffing)

COBS eliminates all `0x00` bytes from the encoded data so that `0x00` can serve as an unambiguous frame delimiter. The binary stream consists of COBS-encoded frames separated by `0x00` delimiter bytes.

### COBS Encoding Algorithm

COBS replaces each run of non-zero bytes (plus any following zero byte) with a *code byte* followed by the non-zero bytes. The code byte indicates the distance to the next zero (or to the next code byte if the run reaches 254 non-zero bytes).

**Encoding:**

1. Maintain a pointer `code_idx` to the position of the current code byte (initially the first output byte), and a counter `code = 1`.
2. For each input byte:
   - If the byte is `0x00`: write `code` at position `code_idx`. Set `code_idx` to the current output position, write a placeholder `0x00`, reset `code = 1`.
   - If the byte is non-zero: append it to the output, increment `code`. If `code` reaches `0xFF` (255): write `code` at `code_idx`, set `code_idx` to the current output position, write placeholder, reset `code = 1`.
3. After processing all input bytes: write `code` at position `code_idx`.

**Decoding:**

1. Read a code byte `C`.
2. Copy the next `C - 1` bytes to the output.
3. If `C < 0xFF` and more encoded data remains, append a `0x00` to the output.
4. Repeat from step 1 until no more encoded bytes remain.
5. Important: after the final code byte and its data bytes, do NOT append a trailing `0x00`.

**Frame structure in the stream:** `[COBS-encoded-data][0x00][COBS-encoded-data][0x00]...`

Split the byte stream on `0x00` delimiters. Each non-empty segment is a COBS-encoded frame. Decode each to recover the raw message bytes.

---

## Layer 2: Postcard Wire Format

Postcard is a compact binary serialization format. It encodes data without self-describing metadata — the decoder must know the schema in advance.

### Variable-Length Integers (varint)

Integers larger than 1 byte are encoded using a variable-length scheme (LEB128):

- Each encoded byte uses 7 data bits (bits 0–6) and 1 continuation bit (bit 7, the MSB).
- Continuation bit `1` means more bytes follow; `0` means this is the last byte.
- Bytes are ordered least-significant first (little-endian).

**Encoding unsigned integer `N`:**
```
while N > 0x7F:
    emit (N & 0x7F) | 0x80
    N >>= 7
emit N & 0x7F
```
Special case: `0` is encoded as `[0x00]`.

**Maximum encoded lengths:**

| Type  | Max varint bytes |
|-------|-----------------|
| u16   | 3               |
| u32   | 5               |
| u64   | 10              |
| u128  | 19              |

Varints that exceed the maximum encoded length for their type, or that encode a value exceeding the type's range, are invalid.

**Examples (u16):**

| Value | Encoded          |
|------:|:-----------------|
| 0     | `[0x00]`         |
| 127   | `[0x7F]`         |
| 128   | `[0x80, 0x01]`   |
| 16383 | `[0xFF, 0x7F]`   |
| 65535 | `[0xFF, 0xFF, 0x03]` |

### Signed Integer Encoding (Zigzag + varint)

Signed integers are first zigzag-encoded to map small-magnitude values to small unsigned values, then varint-encoded.

**Zigzag encoding:**
```
zigzag(n) = (n << 1) ^ (n >> (bit_width - 1))
```
where the right shift is an *arithmetic* (sign-extending) shift.

**Zigzag decoding:**
```
original = (zigzag >>> 1) ^ -(zigzag & 1)
```
where `>>>` is an unsigned/logical right shift.

| Signed value | Zigzag value |
|-------------:|:-------------|
| 0            | 0            |
| -1           | 1            |
| 1            | 2            |
| -2           | 3            |
| 2            | 4            |

The zigzag-encoded value is then encoded as an unsigned varint.

### Type Encodings

| Type     | Encoding |
|----------|----------|
| `bool`   | Single byte: `0x00` = false, `0x01` = true |
| `u8`     | Single byte, raw value |
| `i8`     | Single byte, two's complement |
| `u16`    | `varint(u16)` |
| `u32`    | `varint(u32)` |
| `u64`    | `varint(u64)` |
| `i16`    | zigzag then `varint` |
| `i32`    | zigzag then `varint` |
| `f32`    | 4 bytes, IEEE 754, little-endian (NOT varint) |
| `f64`    | 8 bytes, IEEE 754, little-endian (NOT varint) |
| `string` | `varint(length)` followed by UTF-8 bytes |
| `option` | `0x00` for None; `0x01` followed by encoded value for Some |
| `seq`    | `varint(count)` followed by `count` encoded elements |

### Struct Encoding

Struct fields are encoded sequentially in definition order. No field names or count are on the wire.

### Tagged Union (Enum) Encoding

A tagged union is encoded as:
1. `varint(u32)` discriminant identifying the variant
2. The struct encoding of the variant's fields

---

## Schema File (`schema.json`)

The schema defines the message type as a tagged union with named variants. Each variant has a discriminant (integer) and a list of typed fields. Complex types use nested objects:

- `{"seq": "i32"}` — a sequence of `i32` values
- `{"option": "u16"}` — an optional `u16` value
