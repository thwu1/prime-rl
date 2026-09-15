`/app/levenshtein_dfa.py` contains stubs for a fuzzy string matching library. Reference binary index files in `/app/data/` pair JSON doc-ID lists (`.json`) with their binary-encoded forms (`.bin`) in an undocumented format. A dictionary is at `/app/dictionary.txt` and a query workload at `/app/queries.txt`. `xxd` and `hyperfine` are available.

Produce these three artifacts:

## `/app/levenshtein_dfa.py`

Complete implementation of every class and function in the stub:

- `ParametricDFA(max_distance)`: Reusable fuzzy matching automaton. A single instance must produce correct results for any number of `build_dfa(query)` calls on different query strings.
- `ConcreteDFA` (returned by `build_dfa(query)`):
  - `initial_state` (int): the start state
  - `step(state, char) -> int | None`: state transition; `None` means dead/sink state
  - `is_match(state) -> bool`: whether the state is accepting
  - `distance(state) -> int`: minimum Levenshtein distance at an accepting state; `-1` if non-accepting
  - Correctness requirement: must accept exactly the strings within `max_distance` standard Levenshtein edits of the query (insertions, deletions, substitutions each cost 1). Must be correct for both `max_distance=1` and `max_distance=2`.
- `FuzzySearcher(words)`: `.search(parametric_dfa, query)` returns a sorted `list` of `(word, distance)` tuples for all dictionary words within the automaton's edit distance of the query. Each `distance` value must equal the true Levenshtein distance. Results must be sorted lexicographically.
- `bitpack_postings(doc_ids)` / `unpack_postings(data)`: Compress and decompress sorted integer doc-ID lists. `bitpack_postings([])` returns `b""`, `unpack_postings(b"")` returns `[]`. The output of `bitpack_postings` must be byte-identical to the reference `.bin` files in `/app/data/` when given the corresponding JSON input. Round-trip correctness is required: `unpack_postings(bitpack_postings(ids)) == ids` for any sorted list of non-negative integers. The format must achieve compression relative to raw 4-byte-per-integer storage.

## `/app/format_spec.txt`

Specification of the binary posting list format used by the `.bin` files in `/app/data/`, determined from analysis of the binary/JSON reference pairs. Must document byte ordering, encoding scheme, block structure, and header layout. Minimum 200 characters.

## `/app/benchmark_report.json`

Performance comparison of the fuzzy search implementation against naive brute-force pairwise edit-distance computation over the dictionary and query workload, measured using `hyperfine`. Required JSON fields:

- `dfa_mean_ms` (float, > 0): mean search time in milliseconds
- `naive_mean_ms` (float, > 0): mean naive brute-force time in milliseconds
- `speedup_factor` (float, > 1.0): ratio of naive to search time
- `recommendation` (string, >= 30 characters): evidence-based assessment of the preferred approach