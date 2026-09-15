Build a CLI tool at `/app/` that compiles to `/app/target/release/fst-tool` via `cargo build --release`. Use only the provided `/app/Cargo.toml`; no external crate dependencies.

The tool maps byte-string keys to `u64` values using a compact indexed data structure. Reference datasets in `/app/data/` specify the compression bounds, value retrieval semantics, and approximate matching behavior the implementation must satisfy.

## CLI

**`fst-tool build <input> <output>`** — Construct the data structure from `<input>`, a file of tab-separated `key\tvalue` lines (keys in strict lexicographic order; values: unsigned 64-bit integers). Write binary to `<output>`.

**`fst-tool contains <fst> <key>`** — Print `true` or `false`.

**`fst-tool get <fst> <key>`** — Print the `u64` value, or `NOT_FOUND`.

**`fst-tool keys <fst> [--prefix <p>] [--ge <lo>] [--le <hi>]`** — Print `key\tvalue` pairs matching all filters, one per line, in lexicographic order. No filters: all entries.

**`fst-tool fuzzy <fst> <query> <distance>`** — Print entries within the given byte-level edit distance (single-byte insertions, deletions, substitutions each cost 1) as `key\tvalue\tdistance` lines, sorted by key.

**`fst-tool info <fst>`** — Print exactly two lines: `keys: <N>` then `nodes: <N>`.

## Constraints

- Node counts reported by `info` must satisfy the upper bounds in `/app/data/compression_spec.txt`.
- All keys must be retrievable with their exact original values despite structural compression. `/app/data/value_semantics.txt` demonstrates required behavior.
- `/app/data/edit_distance_examples.txt` specifies approximate matching semantics.
- Empty-string keys, zero-valued outputs, and keys that are prefixes of other keys must all be correctly handled.
- Binary format is implementation-defined but must round-trip correctly.
- All output to stdout. No trailing whitespace. Exit 0 on success, nonzero on error.

Source files go under `/app/src/`.
