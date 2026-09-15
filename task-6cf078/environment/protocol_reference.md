# Protocol Reference

## COBS (Consistent Overhead Byte Stuffing)

COBS transforms a message so that it contains no zero bytes, allowing `0x00` to serve as an unambiguous frame delimiter on a serial link.

### Encoding Algorithm

The input message is processed sequentially. The output is a series of "code groups":

1. Scan forward from the current position for the next `0x00` byte (or end of message).
2. Let `N` = the number of non-zero bytes found before the `0x00` or end.
3. If `N < 254`: write code byte `N + 1`, then copy the `N` data bytes. The `0x00` that terminated this group is implicit (it will be reconstructed during decoding). If this is the last group (hit end of message rather than a `0x00`), the implicit zero is suppressed.
4. If `N == 254`: write code byte `0xFF`, then copy the 254 data bytes. No implicit zero follows a `0xFF` code — the block was simply too long to encode an implicit zero.
5. If the block of non-zero bytes exceeds 254, emit a `0xFF`-coded group of 254 bytes and continue.

### Decoding Algorithm

Given COBS-encoded data (with the trailing `0x00` delimiter already stripped):

1. Read the next byte as the code `C`.
2. Copy `C - 1` bytes from input to output.
3. If `C < 0xFF` **and** there is more input remaining: append a `0x00` to output.
4. Repeat from step 1 until input is exhausted.

If a `0x00` byte is encountered within the encoded data (not at a delimiter boundary), the frame is invalid.

### Test Vectors

| Original Data (hex)             | COBS Encoded (hex)             |
|----------------------------------|-------------------------------|
| `00`                             | `01 01`                       |
| `00 00`                          | `01 01 01`                    |
| `11 22 00 33`                    | `03 11 22 02 33`              |
| `11 22 33 44`                    | `05 11 22 33 44`              |
| `11 00 00 00`                    | `02 11 01 01 01`              |

---

## Postcard Varint Encoding (LEB128)

Integers larger than 8 bits are encoded using a variable-length format based on LEB128:

- Each encoded byte carries **7 data bits** (bits 0–6) and **1 continuation bit** (bit 7).
- **Continuation bit = 1**: more bytes follow.
- **Continuation bit = 0**: this is the final byte.
- Byte order is **little-endian**: the first byte holds the least significant 7 bits.

### Encoding procedure (unsigned)

```
while value > 0x7F:
    emit byte: (value & 0x7F) | 0x80
    value >>= 7
emit byte: value & 0x7F
```

### Decoding procedure

```
result = 0, shift = 0
for each byte (up to max_bytes for the type):
    result |= (byte & 0x7F) << shift
    shift += 7
    if (byte & 0x80) == 0:
        return result
error: varint exceeds maximum encoded length
```

### Maximum encoded lengths

| Type | Max varint bytes |
|------|-----------------|
| u16  | 3               |
| i16  | 3               |
| u32  | 5               |
| i32  | 5               |
| u64  | 10              |
| i64  | 10              |

### Examples (u16)

| Decimal | Varint bytes (hex) |
|--------:|--------------------|
| 0       | `00`               |
| 127     | `7F`               |
| 128     | `80 01`            |
| 16383   | `FF 7F`            |
| 16384   | `80 80 01`         |
| 65535   | `FF FF 03`         |

---

## Zigzag Encoding for Signed Integers

Signed integers use **zigzag encoding** before varint encoding. This maps small-magnitude signed values to small unsigned values:

| Signed | Zigzag (unsigned) |
|-------:|------------------:|
| 0      | 0                 |
| -1     | 1                 |
| 1      | 2                 |
| -2     | 3                 |
| 2      | 4                 |

### Formulas

**Encode** (signed → unsigned):
- `n >= 0`: `zigzag = 2 * n`
- `n < 0`: `zigzag = -2 * n - 1`

**Decode** (unsigned → signed):
- `original = (zigzag >> 1) ^ -(zigzag & 1)`

The unsigned zigzag value is then varint-encoded normally.

### Examples (i16)

| Signed | Zigzag | Varint bytes (hex) |
|-------:|-------:|---------------------|
| 0      | 0      | `00`                |
| -1     | 1      | `01`                |
| 1      | 2      | `02`                |
| -64    | 127    | `7F`                |
| 64     | 128    | `80 01`             |
| -32768 | 65535  | `FF FF 03`          |

---

## Postcard Struct Encoding

Struct fields are encoded **in declaration order**, with no field names, no separators, and no length prefix. The decoder must know the schema to parse the data.

## Postcard Enum Encoding (Unit Variants)

The enum discriminant is encoded as a `varint(u32)`. Unit variants (with no associated data) consist solely of the discriminant — no additional bytes follow.

## Postcard Seq Encoding

A `seq` (variable-length sequence) is prefixed by a `varint(usize)` encoding the element count, followed by that many individually encoded elements.
