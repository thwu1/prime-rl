`/app/lz4_block.c` implements LZ4 block format compression and decompression per the specification at `/app/spec.md`. The implementation compiles with `make -C /app` producing `/app/lz4c`.

Fix the implementation and extend it to satisfy all of the following:

**Self-roundtrip correctness**: For any valid input, `./lz4c roundtrip <file>` must exit 0, confirming that compress-then-decompress reproduces the original byte-for-byte. This must hold for empty inputs, inputs under 13 bytes, English text, random bytes, and highly repetitive data including single-byte runs.

**Reference interoperability**: Output from `lz4_block_compress()` must be decompressable by the reference LZ4 library (`lz4.block.decompress(data, uncompressed_size=N)` from Python `lz4` package). Conversely, data compressed by `lz4.block.compress(data, store_size=False)` must be correctly decompressed by `lz4_block_decompress()`. Both directions must produce byte-identical results.

**Compression ratio**: Achieve >= 2x on English prose (~4 KB), >= 5x on a 4-byte pattern repeated 1000 times, and >= 10x on a single-byte run of 4000 bytes.

**Block analysis command**: Implement `/app/lz4c analyze <compressed_file>` which parses a compressed file (4-byte LE original size header followed by a raw LZ4 block) and writes a single-line JSON object to stdout with exactly these integer-valued fields:

- `original_size`: declared original size from the file header
- `compressed_size`: raw block size (file size minus 4)
- `num_sequences`: count of token sequences parsed from the block
- `total_literal_bytes`: sum of literal lengths across all sequences
- `total_match_bytes`: sum of match lengths (each including minmatch) across all sequences; `total_literal_bytes + total_match_bytes` must equal `original_size`
- `max_offset`: largest offset value (0 if no matches)
- `max_match_length`: largest match length including minmatch (0 if no matches)
- `num_overlap_matches`: count of matches where offset < match_length

Exit 0 for valid blocks, non-zero for malformed blocks (truncated input, zero offset, decoded size mismatch). For a file containing only the 4-byte header with `original_size=0` and no block data, all fields must be 0.

**Edge cases**: Empty input, inputs under 13 bytes (literal-only encoding), overlap matches where offset < match_length, and very long matches requiring multiple continuation bytes.

File format: `/app/lz4c compress <in> <out>` writes a 4-byte little-endian original size header followed by a raw LZ4 compressed block. `/app/lz4c decompress <in> <out>` reads the same format.

Interface in `/app/lz4_block.h`:
- `int lz4_block_compress(const uint8_t* src, uint8_t* dst, int src_size, int dst_capacity)` — returns compressed byte count, or 0 on failure
- `int lz4_block_decompress(const uint8_t* src, uint8_t* dst, int src_size, int dst_capacity)` — returns decompressed byte count, or negative on error
- `int lz4_compress_bound(int input_size)` — upper bound on compressed output size

The reference specification is at `/app/spec.md`. The Python `lz4` package can be installed with `pip3 install lz4`.
