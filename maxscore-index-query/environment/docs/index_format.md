# Binary Inverted Index Format

This index uses the PISA binary collection format with modified frequency encoding.
Document IDs and sizes use 32-bit unsigned little-endian integers.
See `/app/docs/compression.md` for the frequency file encoding.

## Files

- **.docs**: Starts with a singleton header sequence `[1, N]` where N is the
  document count. Then one length-prefixed binary sequence per term listing
  sorted document IDs. All values are fixed-width uint32 LE.
- **.freqs**: One length-prefixed sequence per term with occurrence counts,
  aligned 1:1 with .docs postings. No header sequence. Encoded using
  Variable Byte compression — see `/app/docs/compression.md`.
- **.sizes**: Single binary sequence `[N, size_0, ..., size_{N-1}]`
  where N is the document count. All values are fixed-width uint32 LE.

## Metadata

Term lexicon and document identifiers are stored in `/app/metadata.db` (SQLite).
Scoring parameters are also in the metadata store.
