A partial DEFLATE/zlib decompressor is provided at `/app/src/main.rs`. Complete the implementation and fix any defects so that the `zinflate` binary correctly decompresses both zlib-wrapped (RFC 1950) and raw DEFLATE (RFC 1951) streams.

**Binary interface:**

```
/app/target/release/zinflate [--raw] <input_file> [output_file]
```

- Without `--raw`: expects zlib-wrapped input (CMF/FLG header, Adler-32 trailer).
- With `--raw`: expects raw DEFLATE (no wrapper or checksum).
- No file arguments: reads stdin, writes stdout.
- Non-zero exit code and stderr message on any decompression error.

**Required decompression capabilities:**

- Stored blocks (BTYPE=00) with LEN/NLEN integrity check
- Fixed Huffman coded blocks (BTYPE=01) per RFC 1951 §3.2.6
- Dynamic Huffman coded blocks (BTYPE=10) per RFC 1951 §3.2.7, including the full code-length alphabet with all run-length encoding symbols
- LZ77 back-references with correct length/distance resolution using the standard base/extra-bit tables, including overlapping copies where distance is less than length
- Zlib wrapper: CMF/FLG header validation and Adler-32 checksum verification of the decompressed data

**Constraints:**

- All modifications confined to `/app/src/main.rs`
- No changes to `Cargo.toml`; no external crate dependencies
- Binary name must remain `zinflate`
- Build: `cd /app && cargo build --release`

**Verification:** Decompressed output must be byte-identical to Python's `zlib.decompress(data)` for zlib input and `zlib.decompress(data, -15)` for raw DEFLATE, across all block types including: empty payloads, single bytes, highly repetitive data, inputs with large back-reference distances, natural-language text at maximum compression, and multi-kilobyte inputs with diverse byte distributions.
