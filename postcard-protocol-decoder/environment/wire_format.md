# Postcard Wire Format Reference

## Varint Encoding (Unsigned)

Unsigned integers (u16, u32, u64) use unsigned LEB128 variable-length encoding:
- Each byte uses 7 data bits (bits 0-6) and 1 continuation bit (bit 7, MSB)
- Continuation bit = 1: more bytes follow; = 0: this is the last byte
- Least significant 7 bits come first (little-endian byte order)
- u8 and i8 are NOT varint-encoded; they use a single raw byte

Example: 300 (0x012C) encodes as [0xAC, 0x02]:
  Byte 0: 300 & 0x7F = 0x2C, set continuation → 0x2C | 0x80 = 0xAC
  Byte 1: 300 >> 7 = 2, no continuation → 0x02

Maximum varint lengths: u16 → 3 bytes, u32 → 5 bytes, u64 → 10 bytes.

## Signed Integer Encoding (Zigzag + Varint)

Signed integers (i16, i32, i64) use zigzag encoding before unsigned varint:
- Zigzag maps: 0→0, -1→1, 1→2, -2→3, 2→4, ...
- Formula: positive n → 2n, negative n → 2|n| − 1
- The zigzag result is then encoded as an unsigned varint

Example: -15 → zigzag(−15) = 29 → varint(29) = [0x1D]

## Fixed-Size Types

| Type | Wire size | Encoding |
|------|-----------|----------|
| bool | 1 byte    | 0x00 = false, 0x01 = true |
| u8   | 1 byte    | Raw unsigned byte |
| i8   | 1 byte    | Two's complement |
| f32  | 4 bytes   | IEEE 754 binary32, little-endian |
| f64  | 8 bytes   | IEEE 754 binary64, little-endian |

## Variable-Length Types

- **string**: varint(length_in_bytes) followed by UTF-8 encoded bytes
- **byte array**: varint(length) followed by raw bytes

## Composite Types

- **struct**: Fields encoded in definition order. No length prefix, no field names on wire.
- **tuple**: Elements encoded in order. No length prefix (count is known from schema).
- **option**: 0x00 for None. 0x01 followed by the encoded inner value for Some.
- **seq** (variable-length array): varint(element_count) followed by encoded elements.
- **map**: varint(entry_count) followed by (key, value) pairs, each encoded as a tuple.

## Tagged Unions (Enums)

All enum variants begin with a varint(u32) discriminant (0-indexed in variant definition order):

- **unit_variant**: Discriminant only (no additional data).
- **newtype_variant**: Discriminant followed by the encoded inner value.
- **struct_variant**: Discriminant followed by struct fields encoded in definition order.

## COBS (Consistent Overhead Byte Stuffing) Framing

COBS transforms data so that 0x00 never appears, allowing 0x00 to serve as a frame delimiter.

### Encoding
1. Data is conceptually split at each 0x00 byte into segments of non-zero bytes.
2. Each segment is preceded by a code byte equal to (segment_length + 1).
3. Special case: if a segment is exactly 254 non-zero bytes, code = 0xFF and NO implicit zero follows.
4. Encoded frames are separated by 0x00 delimiter bytes.

### Decoding
1. Read code byte N.
2. Copy the next (N − 1) bytes to output.
3. If N < 0xFF AND more encoded data remains, append a 0x00 to output.
4. Repeat until all encoded bytes are consumed.

### Example
Original:  [0x01, 0x02, 0x00, 0x03]
Encoded:   [0x03, 0x01, 0x02, 0x02, 0x03]
On wire:   [0x03, 0x01, 0x02, 0x02, 0x03, 0x00]  (with delimiter)

## postcard-rpc Message Frame Layout

After COBS decoding, each frame contains:
1. **Key**: 8 raw bytes identifying the message type
2. **Sequence number**: varint(u32)
3. **Body**: Postcard-encoded message fields per the schema
