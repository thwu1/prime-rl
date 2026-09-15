Build a Rust CLI at `/app/` producing `/app/target/release/fst-engine`.

The tool implements a compact, ordered key-value store. Input data is tab-separated (`<key>\t<value>`) with UTF-8 string keys and non-negative u64 integer values, in strict lexicographic byte order.

Reference datasets at `/app/data/` document expected behaviors and compaction targets. Examine them before beginning.

Subcommands:

`build <input> <output>` — Ingest sorted TSV input and write a compact binary representation. Exit code 1 on out-of-order or duplicate keys.

`contains <fst> <key>` — Print `true` or `false`.

`get <fst> <key>` — Print the u64 value, or `NOT_FOUND`.

`range <fst> [--ge <key>] [--le <key>]` — Print matching entries as `<key>\t<value>` lines, sorted. Omitted bounds mean unbounded.

`fuzzy <fst> <query> <max_dist>` — Print entries within byte-level Levenshtein distance `max_dist` of `query`, as `<key>\t<value>` lines, sorted.

`prefix <fst> <prefix>` — Print entries whose keys begin with `<prefix>`, as `<key>\t<value>` lines, sorted. An empty prefix returns all entries.

`merge <fst1> <fst2> <output>` — Combine two built files into one. The result contains every key from either input; overlapping keys have their values summed. The output must exhibit the same structural compaction as a freshly built file.

`stats <fst>` — Print JSON to stdout: `{"num_keys": <int>, "num_states": <int>, "num_transitions": <int>, "fst_size_bytes": <int>}`.

Constraints:

- The internal representation must be structurally compact — tests enforce strict upper bounds on `num_states` for known datasets. Consult `/app/data/reference.json` for compaction targets and edge-case specifications.
- All enumeration output (`range`, `fuzzy`, `prefix`) must be in lexicographic byte order.
- Binary format is implementation-defined but must round-trip correctly.
- Empty inputs (zero keys) are valid and must be handled.
