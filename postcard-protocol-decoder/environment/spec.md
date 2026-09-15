# Postcard Wire Format Specification (v1.0)

## Overview

Postcard is a non-self-describing binary serialization format for the Serde data
model. Both serializer and deserializer must share a common schema to interpret
the binary representation.

## Varint Encoding (Unsigned LEB128)

Unsigned integers wider than 8 bits are encoded as variable-length integers using
LEB128 encoding:

- Each byte uses 7 data bits (bits 0-6) and 1 continuation bit (bit 7)
- Continuation bit = 1: more bytes follow; 0: this is the last byte
- Least significant group first (little-endian byte order within the varint)

Types encoded as varints: `u16`, `u32`, `u64`, `u128`

Maximum encoded lengths:

| Type | Native bytes | Max varint bytes |
|------|-------------|-----------------|
| u16  | 2           | 3               |
| u32  | 4           | 5               |
| u64  | 8           | 10              |
| u128 | 16          | 19              |

**`u8` and `i8` are single raw bytes, NOT varint-encoded.**

## Signed Integer Encoding (Zigzag + Varint)

Signed integers use zigzag encoding before varint encoding. Zigzag encoding
places the sign bit in the least significant position, so small-magnitude values
(positive or negative) use fewer bytes.

Mapping: `0 -> 0, -1 -> 1, 1 -> 2, -2 -> 3, 2 -> 4, -3 -> 5, 3 -> 6, ...`

Encoding formula:  `z = (n << 1) ^ (n >> (bits - 1))`  (arithmetic right shift)

Decoding formula:  `n = (z >>> 1) ^ -(z & 1)`  (logical/unsigned right shift on z)

The zigzag value `z` is then encoded as an unsigned varint.

Types: `i16`, `i32`, `i64`, `i128`

## Fixed-Width Types

| Type | Size    | Encoding                                      |
|------|---------|-----------------------------------------------|
| bool | 1 byte  | `0x00` = false, `0x01` = true                 |
| u8   | 1 byte  | raw unsigned byte                             |
| i8   | 1 byte  | raw signed byte (two's complement)            |
| f32  | 4 bytes | IEEE 754 binary32, encoded as little-endian   |
| f64  | 8 bytes | IEEE 754 binary64, encoded as little-endian   |

Note: `f32` and `f64` are NOT varint-encoded. They are always their fixed size.

## Variable-Length Types

### string
Encoded as: `varint(byte_length)` followed by UTF-8 bytes.

### byte array
Encoded as: `varint(length)` followed by raw bytes.

## Composite Types

### struct
Fields are encoded in definition order (top to bottom). No field names, no field
count, and **no end-of-struct marker** are encoded on the wire. The decoder must
know the exact field list from the schema.

A struct `{ a: u16, b: i32, c: string }` encodes as:
`encode(a) || encode(b) || encode(c)` with nothing else.

### tuple
Elements are encoded in definition order (left to right). Since tuples have a
**known element count from the schema**, no length prefix is encoded on the wire.

Example: `(u8, u8, u8)` with value `(1, 4, 2)` encodes as `[0x01, 0x04, 0x02]`.

### seq (sequence / Vec)
Encoded as: `varint(element_count)` followed by each element encoded in order.

Example: `Vec<u16>` with value `[1, 257]` encodes as:
`[0x02, 0x01, 0x81, 0x02]`
(count=2, then varint(1)=0x01, then varint(257)=0x81 0x02)

### map
Encoded as: `varint(entry_count)` followed by `(key, value)` pairs, each pair
encoded as a tuple of `(key_type, value_type)`.

### option
- `None`: single byte `0x00`
- `Some(value)`: byte `0x01` followed by the encoded inner value

## Enums (Tagged Unions)

All enum variants begin with a `varint(u32)` discriminant. Variants are indexed
from 0 in their definition order.

### Unit variant
Discriminant only, no additional data.
Example: `enum { A, B, C }` value `B` encodes as `varint(1)`.

### Newtype variant
Discriminant followed by the encoded inner value.
Example: `enum { X(String) }` value `X("hi")` encodes as `varint(0) || encode("hi")`.

### Struct variant
Discriminant followed by the struct's fields in definition order. No field names
or count on the wire -- just the discriminant then each field value.

## COBS Framing (Consistent Overhead Byte Stuffing)

COBS transforms a payload so it contains no `0x00` bytes, allowing `0x00` to
serve as an unambiguous frame delimiter.

### Encoding algorithm
1. Process input left to right, tracking runs of non-zero bytes.
2. Before each run, write a code byte equal to `run_length + 1`.
3. Then write the non-zero bytes of the run.
4. A zero byte in the input ends the current run (the zero is represented
   implicitly by the code byte, not written explicitly).
5. If a run reaches exactly 254 non-zero bytes, write code `0xFF`, write the
   254 bytes, and start a new run (no implicit zero follows `0xFF`).
6. After the COBS-encoded data, write a `0x00` delimiter byte.

### Decoding algorithm
1. Read code byte `N`.
2. Copy the next `N - 1` bytes to output.
3. If `N < 0xFF` and more data remains in the frame, append `0x00` to output.
4. Repeat until all bytes in the frame are consumed.

## CRC-8 Frame Integrity

Each postcard-rpc frame includes a CRC-8 checksum for error detection. The
checksum uses:

- Polynomial: `0x31` (x^8 + x^5 + x^4 + 1)
- Initial value: `0x00`
- No input/output reflection
- No final XOR

Algorithm (pseudocode):
```
crc = 0x00
for each byte in data:
    crc = crc XOR byte
    for 8 iterations:
        if (crc & 0x80):
            crc = (crc << 1) XOR 0x31
        else:
            crc = crc << 1
        crc = crc AND 0xFF
return crc
```

The CRC is computed over the entire frame payload (key + sequence number + body)
and appended as a single byte before COBS encoding.

## postcard-rpc Frame Structure

Before COBS encoding, each frame contains (in order):
1. **Key**: 8 raw bytes identifying the message type
2. **Sequence number**: unsigned varint
3. **Body**: message struct fields encoded per the schema
4. **CRC-8**: 1 byte — checksum of bytes 1 through 3 (key + seqno + body)

The complete frame is then COBS-encoded and terminated with a `0x00` delimiter.
