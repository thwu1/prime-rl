# DBN File Header

Each `.bin` feed file begins with a variable-length metadata header followed
by the record payload.

## Structure

The header starts with a 3-byte ASCII magic string `DBN` followed by a
single-byte format version number (u8).

A length-prefixed UTF-8 dataset name identifies the source venue. The byte
length of the name is stored as an unsigned 16-bit little-endian integer (u16)
immediately before the name bytes.

Following the dataset name are fixed-width fields in order:
- Record count: unsigned 32-bit (u32) — total number of records in the payload
- Start timestamp: unsigned 64-bit (u64) — nanoseconds since epoch
- End timestamp: unsigned 64-bit (u64) — nanoseconds since epoch
- Compression mode: unsigned 8-bit (u8) — 0 = uncompressed, 1 = zstandard
- Schema identifier: unsigned 8-bit (u8) — matches the record type rtype value
- Two reserved bytes (zero-filled)

## Compression

If the compression mode byte is 1, the entire record payload after the header
is compressed using the Zstandard algorithm. The header itself is never
compressed.

## Byte Order

All multi-byte integer fields in the header use little-endian byte order,
consistent with record fields.
