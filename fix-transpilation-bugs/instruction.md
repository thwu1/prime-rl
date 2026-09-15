`/app/c_src/record_processor.c` is the reference C implementation of a multi-stage data processing pipeline. It parses pipe-delimited records and produces a formatted analysis report covering per-category aggregation, rolling hashes, polynomial fingerprints, zigzag/varint compact serialization with delta encoding, and big-endian byte operations. Its output is correct by definition.

`/app/rust_src/src/main.rs` is an automated transpilation of this program. It compiles and runs without errors, but its output diverges from the C reference. The transpiler introduced multiple semantic bugs spanning different subsystems — some are subtle constant or operator errors, others involve structurally missing processing stages. The bugs interact through shared state (hashing, aggregation, serialization), making root-cause analysis non-trivial. Test input is at `/app/data/input.txt`.

**Deliverable 1**: Fix the Rust code so it produces byte-identical output to the C reference on any valid input. Build with `gcc -O2` for C and `cargo build --release` in `/app/rust_src/` for Rust.

**Deliverable 2**: Write `/app/transpilation_audit.json` — a JSON array where each element documents one distinct bug. Required fields per entry:
- `"location"`: affected Rust function or code region
- `"root_cause"`: why the transpiler produced this specific error (what C/Rust semantic distinction was mishandled)
- `"severity"`: `"critical"`, `"major"`, or `"minor"` — based on how many output sections the bug corrupts when present in isolation
- `"fix_description"`: concise summary of the fix applied