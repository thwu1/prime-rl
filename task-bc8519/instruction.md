Build a static performance analyzer for tiled matrix multiplication kernel configurations on a target GPU.

## Environment

- `/app/gpu_specs.db` — SQLite database with hardware specifications for multiple GPU models and kernel resource profiles. Contains multiple tables; explore the schema to locate the parameters relevant to the target GPU and kernel type.
- `/app/triton_matmul.py` — Reference Triton tiled matmul kernel implementation. Study how configuration parameters (tile sizes, warp count, pipeline stages, group size) determine resource consumption and memory access patterns.
- `/app/gpu_arch_notes.md` — Architecture documentation covering SM resource scheduling, register allocation, and cache-aware tile ordering.
- `/app/search_space.json` — Configuration parameter ranges to enumerate.
- `/app/workloads.json` — Target GPU identifier and matrix dimensions (fp16).
- `/app/output_schema.json` — Required output structure and tiebreaker conventions.

## Task

Enumerate all configurations from the search space. For each configuration-workload pair on the target GPU specified in `workloads.json`:

1. Determine hardware feasibility based on SM resource constraints.
2. Compute GPU occupancy and effective arithmetic intensity accounting for cache reuse from tile grouping.
3. Score each valid configuration as `occupancy * effective_ai`.

Produce `/app/results.json` containing per-workload analysis (valid configuration count, best configuration by score, Pareto frontier on occupancy vs. effective_ai) and the overall best configuration by geometric mean of scores across all workloads. Follow the format specified in `/app/output_schema.json`.