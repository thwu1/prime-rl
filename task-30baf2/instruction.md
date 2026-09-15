## Starting state

- `/app/mask_base.py` — `AttentionMask` abstract base class with `verify(seq_len)` consistency checker
- `/app/masks.py` — Four mask implementations: `CausalMask`, `SlidingWindowMask`, `ChunkwiseMask`, `PrefixLMMask`
- `/app/reference.py` — Naive O(T²) masked attention reference (`naive_masked_attention`)
- `/app/engine.py` — Stub: implement `tiled_attention` here
- `/app/compound_masks.py` — Stub: implement `IntersectionMask` and `LocalGlobalMask` here
- `/app/analysis_schema.json` — JSON Schema specification for the profiling report
- `/app/db_schema.sql` — SQL DDL for the benchmark database
- `/app/run_checks.py` — Diagnostic sweep tool

## Deliverables

### `/app/engine.py`

Implement `tiled_attention(q, k, v, mask_obj, lens=None, tile_q=32, tile_k=32)`:

- Inputs: `q`, `k`, `v` are `(B, H, T, D)` numpy float64 arrays; `mask_obj` is an `AttentionMask`; `lens` is an optional `(B,)` int array of per-batch sequence lengths.
- Returns: `(output, lse)` — `output` is `(B, H, T, D)` float64, `lse` is `(B, H, T)` float64.
- Must produce results matching `naive_masked_attention` within atol=1e-10 across all provided mask types, arbitrary tile sizes (including non-power-of-2), and sequence configurations.
- Must NOT materialize the full T×T score matrix.
- Must leverage `mask_obj.k_full_range_for_q_tile()` to skip unnecessary `mask()` invocations. Specifically: `FullMask` must result in zero `mask()` calls; `CausalMask` must result in fewer `mask()` calls than the total number of tile pairs.
- Must handle variable-length sequences (`lens` — positions beyond `lens[b]` produce zero output), fully-masked query rows (output zero, LSE = -inf), and T=1 edge cases.

### `/app/compound_masks.py`

Implement two `AttentionMask` subclasses (stubs and docstrings provided):

- **`IntersectionMask(mask_a, mask_b)`**: Attends where both sub-masks attend. All four abstract methods (`mask`, `q_range_for_k`, `k_range_for_q`, `k_full_range_for_q_tile`) must be implemented correctly. Must pass `verify(seq_len)` for all tested configurations.
- **`LocalGlobalMask(window_size, n_global)`**: Attends to keys within `window_size` distance OR keys among the first `n_global` positions. All four abstract methods must be implemented correctly. `k_full_range_for_q_tile` must return the largest correct contiguous fully-unmasked range. Must pass `verify(seq_len)`.

Both compound masks must produce correct results when used with the tiled engine.

### `/app/analysis.json`

Profiling report conforming to the JSON Schema at `/app/analysis_schema.json`. Must contain real profiling measurements, not hardcoded values. `FullMask` must report zero mask calls; `CausalMask` must report a positive count.

### `/app/benchmarks.db`

SQLite database conforming to the DDL at `/app/db_schema.sql`. Populate the `benchmark_runs` table by timing `tiled_attention` against `naive_masked_attention` across at least 5 distinct mask types and at least 3 shape/tile configurations per mask type. Populate `mask_call_counts` with mask invocation statistics for at least 5 mask types. All benchmark runs must pass correctness checks. The database must be queryable via the `sqlite3` CLI.