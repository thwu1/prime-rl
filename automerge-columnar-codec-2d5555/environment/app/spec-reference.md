# Automerge Binary Document Format — Specification Reference

This document contains relevant excerpts from the Automerge binary format
specification for implementing the columnar encoding codec.

## Variable-Length Integers

### uLEB (Unsigned LEB128)

uLEB is an unsigned little endian base 128 value. To encode a uLEB, represent
the number in binary and pad it with leading zeros so that it has a length which
is a multiple of 7. Take each group of 7 bytes from least-significant to
most-significant and output them in bytes — the first bit of every byte is 1
except for the last byte which is 0.

- Unsigned ints 0–127 are stored as one byte: `0b00000000` – `0b01111111`
- Unsigned ints 128–16383 are stored as two bytes: `0b10000000 0b00000001` – `0b11111111 0b01111111`

Unsigned integers must not exceed 64 bits. Implementations must generate the
shortest possible uLEB encodings, and should reject documents with overly long
encodings.

### LEB (Signed LEB128)

LEB is a signed variant of little endian base 128. To encode an LEB, represent
the number in two's complement, and sign-extend it so that it has a length which
is a multiple of seven. If the number is negative the padding will be of 1-bits
and if the number is positive the padding will be 0-bits.

- 0 is one byte: `0b00000000`
- Ints from 1 to 63 are one byte: `0b00000001` – `0b00111111`
- Ints from -1 to -64 are one byte: `0b01111111` – `0b01000000`
- Ints from 64 to 8191 are two bytes: `0b11000000 0b00000000` – `0b11111111 0b00111111`
- Ints from -65 to -8192 are two bytes: `0b10111111 0b01111111` – `0b10000000 0b01000000`

Signed integers must not exceed 64 bits. Implementations must generate the
shortest possible LEB for a given integer, and should reject documents with
overly long encodings.

## Run Length Encoding

Many columns use run length encoding to compress repeated values. Such columns
are encoded as repeated pairs of the form `(length, value)`.

`length` is a signed LEB:

- If `length` is **positive**, then `value` is a single instance of the value
  which occurs `length` times.
- If `length` is **0** then this pair represents a null value and `value` is the
  **uLEB** encoding of the number of times null occurs.
- If `length` is **negative** then `value` is a literal run and the absolute
  value of `length` is the number of items in the literal run. That is to say,
  there is no compression.

**Example:** Encoding the array of uLEBs `[0, 0, 0, null, null, 1, 2, 3]`
produces the bytes `0x03 0x00 0x00 0x02 0x7d 0x01 0x02 0x03`.

## Column Types

### Group Column (type 0)

A run length encoded list of 64-bit uLEBs that specifies how many values should
be read from the subsequent grouped columns per change or operation.

**Example:** Five changes with `[0, 1, 2, 2, 2]` dependencies each would encode
as `0x7e 0x00 0x01 0x03 0x02`.

### Actor Column (type 1)

Uses run length encoding to compress a list of uLEBs representing an index into
an array of actor IDs.

### uLEB Column (type 2)

Uses run length encoding to compress a list of 64-bit uLEBs.

### Delta Column (type 3)

Uses run length encoding to compress a list of 64-bit LEBs (signed).

**The sequence is assumed to start from zero**, so if you wanted to encode the
list `[3, 4, 5, 6, 9, 7, 8]` you would first calculate the list of deltas
`[+3, +1, +1, +1, +3, -2, +1]`, and then run length encode the resulting
signed LEBs to get the bytes `0x7f 0x03 0x03 0x01 0x7d 0x03 0x7e 0x01`.

### Boolean Column (type 4)

Encodes a list of booleans. The column contains sequences of 64-bit uLEB
integers which represent the lengths of alternating sequences of false/true.
**The initial value of the column is always false.**

**Example:** Encoding `[true, true, false, false, false]` produces a list of
lengths `[0, 2, 3]`, encoded as `0x00 0x02 0x03`.

### String Column (type 5)

Uses run length encoding to compress a list of length-prefixed UTF-8 strings.
Each string is encoded as a 64-bit uLEB length followed by that many literal
bytes.

**Example:** Encoding `["a", "", null, "boo", "boo"]` produces
`0x7e 0x01 0x61 0x00 0x00 0x01 0x02 0x03 0x62 0x6f 0x6f`.

### Value Metadata Column (type 6)

Always paired with a value column with the same ID. The metadata column is a
run length encoded list of 64-bit uLEBs that defines the type and length of
each value in the value column.

These integers are laid out like so:

- **The lower four bits encode the type of the value**
- **The higher bits encode the length of the value**

Type codes:

| Value | Type            | Representation                          |
|-------|-----------------|-----------------------------------------|
| 0     | Null            | Not present (length = 0)                |
| 1     | False           | Not present (length = 0)                |
| 2     | True            | Not present (length = 0)                |
| 3     | Unsigned int    | 64-bit uLEB (length = 1..10)            |
| 4     | Signed int      | 64-bit LEB (length = 1..10)             |
| 5     | IEEE754 float   | 64-bit LE float (length = 8)            |
| 6     | UTF-8 string    | UTF-8 bytes (length = 0..2^60)          |
| 7     | Bytes           | Arbitrary bytes (length = 0..2^60)      |
| 8     | Counter         | 64-bit LEB (length = 1..10)             |
| 9     | Timestamp       | 64-bit LEB (length = 1..10)             |

### Value Column (type 7)

Contains raw values. The type and length of each value is determined by the
value metadata column with the same column ID.

## Column Specification

Column specifications are a 32-bit uLEB interpreted as a bitfield:

- **The least significant three bits** encode the column type (0–7)
- **The 4th least significant bit** is `1` if the column is DEFLATE compressed
  and `0` otherwise
- **The remaining bits** are the column ID

## Chunks

### Structure

| Field          | Byte Length      | Description                     |
|----------------|------------------|---------------------------------|
| Magic bytes    | 4                | `[0x85, 0x6f, 0x4a, 0x83]`     |
| Checksum       | 4                | Validates chunk integrity       |
| Chunk type     | 1                | Type of this chunk              |
| Chunk length   | Variable (uLEB)  | Length of chunk contents        |
| Chunk contents | Variable         | The actual bytes for the chunk  |

**The checksum is the first four bytes of the SHA-256 hash of the concatenation
of the chunk type, chunk length and chunk contents fields.**

### Chunk Types

| Value | Type                     |
|-------|--------------------------|
| 0x00  | Document chunk           |
| 0x01  | Change chunk             |
| 0x02  | Compressed change chunk  |

### Empty Document

A document with no changes consists of `0x00 0x00 0x00 0x00` as the counts of
actors, heads, change columns and operation columns are all zero. With the chunk
header, this gives a file consisting of the following bytes:

```
0x85 0x6f 0x4a 0x83 0xb8 0x1a 0x95 0x44 0x00 0x04 0x00 0x00 0x00 0x00
```
