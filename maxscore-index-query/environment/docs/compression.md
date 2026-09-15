# Frequency Encoding

The `.freqs` file uses Variable Byte (VByte) encoding for all integer values,
unlike the `.docs` file which uses fixed-width 32-bit little-endian integers.

## VByte Format

Each integer is encoded using one or more bytes:
- 7 bits of data per byte (bits 0-6)
- Bit 7 (MSB) is the continuation flag:
  - `0` = more bytes follow
  - `1` = this is the final byte
- Bytes are ordered least-significant-first

### Examples

| Value | VByte bytes (hex) |
|-------|-------------------|
| 5     | 85                |
| 127   | FF                |
| 128   | 00 81             |
| 300   | 2C 82             |

### Decoding

    value = 0
    shift = 0
    repeat:
        byte = read_next_byte()
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            return value
        shift += 7

## File Structure

The `.freqs` file contains VByte-encoded length-prefixed sequences,
one per posting list:

    [vbyte(length_0), vbyte(freq_0_0), ..., vbyte(freq_0_{length_0-1})]
    [vbyte(length_1), vbyte(freq_1_0), ...]
    ...

Each sequence is aligned 1:1 with the corresponding `.docs` posting list.
