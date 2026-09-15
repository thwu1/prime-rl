# Sensor Protocol Wire Format Notes

Collected from firmware team preliminary documentation. Some details
may be approximate — verify against actual device behavior when possible.

## COBS (Consistent Overhead Byte Stuffing) Framing

COBS removes all 0x00 bytes from a payload so that 0x00 can serve
as an unambiguous frame delimiter.

### Encoding
1. Split data at each 0x00 into segments of non-zero bytes.
2. Precede each segment with a code byte = segment\_length + 1.
3. Special: if a segment is exactly 254 non-zero bytes, code = 0xFF
   and no implicit zero follows.
4. Frames are separated by 0x00 on the wire.

### Decoding
1. Read code byte N.
2. Copy next (N - 1) bytes to output.
3. If N < 0xFF and more data remains, append 0x00.
4. Repeat.

## Varint (Unsigned LEB128)

Unsigned integers wider than 8 bits (u16, u32, u64) use LEB128:
- 7 data bits per byte (bits 0–6), continuation bit 7
- Continuation = 1 means more bytes follow; 0 means last byte
- Least significant group first

u8 and i8 are single raw bytes, NOT varint encoded.

Example: 300 → [0xAC, 0x02]

## Signed Integer Encoding

Signed integers (i16, i32, i64) use zigzag mapping before varint:

    0 → 0,  -1 → 1,  1 → 2,  -2 → 3,  2 → 4 ...

Encoding:  z = (n << 1) ^ (n >> (bits-1))
Decoding:  n = (z >> 1) ^ (z & 1)

Example: -15 → zigzag 29 → varint [0x1D]

## Fixed-Width Types

| Type | Size    | Encoding                          |
|------|---------|-----------------------------------|
| bool | 1 byte  | 0x00 = false, 0x01 = true         |
| u8   | 1 byte  | raw unsigned byte                 |
| i8   | 1 byte  | two's complement                  |
| f32  | 4 bytes | IEEE 754 binary32, big-endian     |
| f64  | 8 bytes | IEEE 754 binary64, big-endian     |

## Variable-Length Types

- **string**: varint(byte\_length) followed by UTF-8 bytes
- **byte array**: varint(length) followed by raw bytes

## Composite Types

- **struct**: fields in definition order, no length prefix, no field tags
- **tuple**: varint(element\_count) followed by elements in order
- **option**: 0x00 = None; 0x01 followed by encoded inner value = Some
- **seq**: varint(element\_count) followed by encoded elements
- **map**: varint(entry\_count) followed by (key, value) pairs

## Enums (Tagged Unions)

All enum variants start with a varint discriminant (0-indexed in
definition order). What follows depends on the variant kind:
- Unit variant: discriminant only
- Newtype variant: discriminant + encoded inner value
- Struct variant: discriminant + fields in definition order

## postcard-rpc Message Frame

After COBS decoding, each frame contains:
1. **Key**: 8 raw bytes identifying the message type
2. **Sequence number**: varint-encoded u32
3. **Body**: fields encoded per the schema
