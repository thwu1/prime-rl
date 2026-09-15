The Stockfish chess engine source is at `/app/stockfish/`. A working binary must exist at `/app/stockfish/src/stockfish`.

Create `/app/tt_codec.py` — a Python module that faithfully reimplements the transposition table (TT) subsystem as defined in `src/tt.cpp`, `src/tt.h`, `src/search.cpp`, and `src/types.h`. Every constant, encoding, and behavioral detail must be derived from the C++ source and match it exactly.

The module must export these constants (values derived from source):

`DEPTH_NONE`, `DEPTH_UNSEARCHED`, `MAX_PLY`, `BOUND_NONE`, `BOUND_UPPER`, `BOUND_LOWER`, `BOUND_EXACT`, `GENERATION_BITS`, `GENERATION_MASK`, `BOUND_SHIFT`, `BOUND_MASK`, `PV_SHIFT`, `PV_MASK`, `CLUSTER_SIZE`, `VALUE_NONE`, `VALUE_INFINITE`, `VALUE_MATE`, `VALUE_MATE_IN_MAX_PLY`, `VALUE_MATED_IN_MAX_PLY`, `VALUE_TB`, `VALUE_TB_WIN_IN_MAX_PLY`, `VALUE_TB_LOSS_IN_MAX_PLY`

The module must export these functions:

- `pack_gen_bound(generation, bound, is_pv) -> int`
- `unpack_gen_bound(gen_bound8) -> tuple[int, int, bool]`
- `encode_depth(depth) -> int`
- `decode_depth(depth8) -> int`
- `relative_age(current_generation, gen_bound8) -> int`
- `encode_entry(key64, depth, is_pv, bound, move16, value, eval_value, generation) -> bytes` — 10-byte packed binary
- `decode_entry(data: bytes) -> dict` with keys: `key16`, `depth`, `depth8`, `is_pv`, `bound`, `generation`, `gen_bound8`, `move16`, `value`, `eval_value`
- `cluster_index(key64, cluster_count) -> int`
- `should_replace(existing, new_key64, new_depth, new_bound, new_is_pv, current_generation) -> bool` — `existing` has keys `key16`, `depth8`, `gen_bound8`
- `select_victim(entries, current_generation) -> int` — returns eviction index 0–2
- `apply_secondary_aging(entry) -> bool` — mutates in place
- `value_to_tt(v, ply) -> int`
- `value_from_tt(v, ply, r50c) -> int`
- `empty_entry() -> dict` — keys: `key16`, `depth8`, `gen_bound8`, `move16`, `value`, `eval_value`
- `simulate_tt_probe(cluster, key64, current_generation) -> tuple[bool, dict | None, int]` — returns `(hit, data_dict_or_None, write_index)`
- `simulate_tt_store(cluster, key64, value, is_pv, bound, depth, move16, eval_value, current_generation) -> None` — mutates cluster in-place
- `hashfull(clusters, current_generation, max_age) -> int` — per-mille occupancy estimate

```
```