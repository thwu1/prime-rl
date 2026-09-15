Implement a **parametric Levenshtein DFA** system for fuzzy dictionary lookup. The system must precompute a query-independent parametric automaton for max edit distances D=1 and D=2 using the Schulz-Mihov approach, then use it to efficiently evaluate candidate strings against arbitrary queries.

## Environment

- `/app/reference.py` — Naive edit distance function (correctness oracle)
- `/app/dictionary.txt` — Word list (~20K entries)
- `/app/queries.json` — List of objects with `"query"` (string) and `"max_distance"` (1 or 2)

## Deliverables

Create **`/app/parametric_dfa.py`** with a `LevenshteinParametricDFA` class:

- Constructor takes `max_distance` (int). Precomputes the parametric DFA: NFA states are `(offset, remaining_budget)` pairs; states are simplified via the "implies" relation where `(o1,d1)` implies `(o2,d2)` when `d1 >= d2` and `d1 - d2 >= |o1 - o2|`; transitions are abstracted through characteristic vectors of width `3D+1`; state sets are normalized by shifting the minimum offset to zero; reachable parametric states are discovered via powerset construction.
- `eval(query, candidate)` returns `(match: bool, distance: int)` using the precomputed parametric transitions with runtime characteristic vectors derived from the query. Distance is `-1` when not matching.
- `num_states()` returns count of non-dead parametric states in the DFA.
- Must agree with `/app/reference.py` on all inputs within the supported max distance.

Create **`/app/run_queries.py`** to process all queries and write:

- `/app/output/results.json`:
  ```json
  {"query_results": [{"query": "...", "max_distance": 2, "matches": [{"word": "...", "distance": 0}, ...]}]}
  ```
  Matches sorted by `(distance, word)`.

- `/app/output/dfa_stats.json`:
  ```json
  {"d1_parametric_states": <int>, "d2_parametric_states": <int>}
  ```