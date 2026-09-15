Three independent implementations of RFC 8949 Section 4.2.1 Core Deterministic CBOR encoding are at `/app/encoders/{alpha,beta,gamma}.py`. Each reads hex-encoded CBOR from stdin (one data item per line) and writes the deterministic encoding as hex to stdout. Each implementation contains exactly two conformance violations against Section 4.2.1. No two implementations share the same pair of violations.

Specification excerpts are at `/app/rfc_notes/deterministic.md`. Hex-encoded and raw binary CBOR test inputs are in `/app/corpus/` (use `xxd -p` to convert `.cbor` files to hex for piping to encoders).

**Produce two deliverables:**

1. `/app/conformance_report.json` — JSON object keyed by encoder name (`alpha`, `beta`, `gamma`). Each value is an object mapping requirement IDs to verdicts (`"pass"` or `"fail"`). The requirement IDs are:

   - `preferred_int_args` — integer/length/tag arguments use shortest encoding
   - `preferred_float_nan` — all NaN values canonicalized to half-precision quiet NaN (0xf97e00)
   - `preferred_float_neg_zero` — negative zero sign bit preserved through precision reduction
   - `preferred_float_shortest` — floats use shortest IEEE 754 binary encoding that preserves value
   - `no_indefinite_length` — no indefinite-length items in output
   - `map_key_ordering` — map keys sorted by bytewise lexicographic order of their deterministic encodings

2. `/app/reference_normalizer.py` — A fully correct CBOR deterministic normalizer satisfying all Section 4.2.1 requirements. Same interface: hex stdin, hex stdout, one item per line. Must use only the Python standard library.