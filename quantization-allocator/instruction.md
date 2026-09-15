A mixed dense/MoE transformer model's quantization profiling data is distributed across three data stores:

- **`/app/model.db`** (SQLite): Contains `modules` (id, layer_idx, module_type, numel, measurement_group), `architecture` (key-value metadata including `weight_budget`), and `dag_edges` (src_module_id, dst_module_id, propagation_coeff) encoding a directed acyclic graph of how quantization error propagates between connected modules through the network.

- **`/app/measurements/`** (Apache Parquet files): Per-module-type measurement data split across `attention.parquet`, `mlp.parquet`, `router.parquet`, and `expert.parquet`. Each contains columns: module_id, option_idx, total_bits, error, bpw, config_desc.

- **`/app/constraints.toml`** (TOML): Deployment constraints including the global weight budget, layer group minimum bits-per-weight thresholds (with `start_layer`, `end_layer`, `min_bpw`), and per-module precision pins (`module_id`, `required_min_bpw`).

## Effective Error

Each module's **effective error** is computed recursively through the DAG: a module's effective error equals its own quantization error (from the selected option) plus the weighted sum of its direct predecessors' *effective* errors, using the `propagation_coeff` values from `dag_edges` as weights. Modules with no predecessors have effective error equal to their own raw error. For any module that has predecessors, its effective error must be greater than or equal to its raw error.

## Task

Produce `/app/strategy.json` — a quantization strategy assigning exactly one option to every module. The strategy must:

- Satisfy all constraints from `constraints.toml`: total bits within the weight budget, each module's bpw meeting its layer group's `min_bpw` threshold, and pinned modules meeting their `required_min_bpw`
- Minimize the maximum effective error across all modules — the solution's max effective error must be within **15%** of the optimal achievable value under the given constraints and budget
- Fully utilize the bit budget: no single-module upgrade to a lower-error option should be possible within the remaining budget

## Output

`/app/strategy.json` must be valid JSON with the following exact structure:

```json
{
  "assignments": [
    {"module_id": 0, "option_idx": 5},
    {"module_id": 1, "option_idx": 3}
  ],
  "total_bits": <int>,
  "weight_budget": <int>,
  "max_effective_error": <float>,
  "max_raw_error": <float>
}
```

- `assignments`: one entry per module, ordered by ascending `module_id`, each with `module_id` (int) and `option_idx` (int) referencing a valid option from the Parquet measurements
- `total_bits`: the sum of `total_bits` for all assigned options — must match the actual computed sum (tolerance < 1000)
- `weight_budget`: the budget value from the database
- `max_effective_error`: the maximum effective error across all modules computed via recursive DAG propagation — must match the actual computed value (tolerance < 1e-8)
- `max_raw_error`: the maximum raw quantization error among assigned options — must match the actual computed value (tolerance < 1e-8)