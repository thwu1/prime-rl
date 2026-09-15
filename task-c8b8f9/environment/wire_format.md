# Postcard Wire Format Reference

This document describes how the postcard serialization format encodes data types to binary.

## Varint Encoded Integers

Integers larger than 8 bits are encoded as variable-length integers (varints). Each byte uses:
- **Bit 7 (MSB)**: Continuation flag. `1` = more bytes follow; `0` = this is the last byte.
- **Bits 0-6**: 7 data bits.

Data is encoded in **little-endian** order: the first byte contains the least significant 7 data bits.

### Unsigned Integer Encoding

Examples for `u16`:

| Decimal | Varint Encoded       | Length |
|--------:|:---------------------|:-------|
| 0       | `[0x00]`             | 1      |
| 127     | `[0x7F]`             | 1      |
| 128     | `[0x80, 0x01]`       | 2      |
| 16383   | `[0xFF, 0x7F]`       | 2      |
| 16384   | `[0x80, 0x80, 0x01]` | 3      |
| 65535   | `[0xFF, 0xFF, 0x03]` | 3      |

### Signed Integer Encoding (Zigzag)

Signed integers are first **zigzag encoded** before varint encoding. Zigzag encoding moves the sign bit to the least significant position:

```
zigzag(n) = (n << 1) ^ (n >> (bits - 1))    // encoding
original  = (z >> 1) ^ -(z & 1)              // decoding
```

Examples for `i16`:

| Decimal | Zigzag (unsigned) | Varint Encoded       |
|--------:|------------------:|:---------------------|
| 0       | 0                 | `[0x00]`             |
| -1      | 1                 | `[0x01]`             |
| 1       | 2                 | `[0x02]`             |
| -15     | 29                | `[0x1D]`             |
| 64      | 128               | `[0x80, 0x01]`       |
| -32768  | 65535             | `[0xFF, 0xFF, 0x03]` |

### Maximum Varint Encoded Length

The maximum number of bytes a varint can occupy is determined by the type width:

```
max_bytes = ceil(type_bits / 7)
```

| Type   | Type Bytes | Max Varint Bytes |
|:-------|:-----------|:-----------------|
| `u16`  | 2          | 3                |
| `i16`  | 2          | 3                |
| `u32`  | 4          | 5                |
| `i32`  | 4          | 5                |
| `u64`  | 8          | 10               |
| `i64`  | 8          | 10               |
| `u128` | 16         | 19               |
| `i128` | 16         | 19               |

A varint that exceeds the maximum encoded length for its type is **invalid**.

## Non-Varint Types

### `u8` / `i8`
Single byte. `i8` uses two's complement. No varint encoding.

### `bool`
Single byte: `0x00` = false, `0x01` = true. All other values are **invalid**.

### `f32`
Bitwise convert to `u32`, encode as 4 bytes in **little-endian** order. NOT varint encoded.

### `f64`
Bitwise convert to `u64`, encode as 8 bytes in **little-endian** order. NOT varint encoded.

### `string`
Encoded as: `varint(length)` followed by `length` UTF-8 bytes. The length is encoded as `varint(usize)` (on a 64-bit platform, max 10 varint bytes; values practically fit in fewer).

### `byte_array` / `seq<T>`
Encoded as: `varint(count)` followed by `count` encoded elements.

### `option<T>`
- `None`: single byte `0x00`
- `Some(value)`: byte `0x01` followed by the encoded value

### `struct`
Fields encoded in definition order. No length prefix, no field names on the wire.

### Tagged Union (enum)
Encoded as: `varint(u32)` discriminant, followed by the variant's fields (encoded as a struct).

## COBS Framing

Consistent Overhead Byte Stuffing (COBS) transforms data so that `0x00` bytes never appear, allowing `0x00` to serve as a frame delimiter.

### Encoding
1. Start with a **code byte** (placeholder).
2. Walk through data bytes:
   - Non-zero byte: copy to output; increment code counter.
   - Zero byte: write the current code counter into the code byte position; start a new code byte; reset counter to 1.
   - If counter reaches 255 (0xFF) without a zero: write 0xFF as the code byte; start a new code byte; reset counter to 1 (this does NOT imply a trailing zero).
3. Write the final code counter.

### Decoding
1. Read a **code byte** `c`.
2. Copy the next `c - 1` bytes to output.
3. If `c < 0xFF` and more data remains, append a `0x00` byte.
4. Repeat from step 1 until all data is consumed.
5. (The last block does NOT append a trailing zero when data is exhausted.)

### Stream Format
Messages are COBS-encoded and separated by `0x00` sentinel bytes:
```
[COBS(msg0)] 0x00 [COBS(msg1)] 0x00 ... [COBS(msgN)] 0x00
```
