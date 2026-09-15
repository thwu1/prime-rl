A numerical optimization library at `/app/polar_decomp/` implements Newton-Schulz iterations for polar decomposition — the orthogonalization step used in ML optimizers like Muon. It provides a reference implementation (`standard_ns.py`) and a Gram-based variant (`gram_ns.py`) that should produce identical results but currently does not. Supporting modules handle coefficient definitions, eigenvalue stability simulation, and restart position optimization.

A SQLite database at `/app/workloads.db` stores evaluation scenarios and empty result tables. The schema is documented in `/app/schema.sql`.

Deliver the following outcomes:

- **Correct library**: The Gram variant must match the standard variant for all matrix shapes (wide, square, tall), batch dimensions, coefficient sets, and restart schedules. All public APIs across every module must work without error.

- **Populated database**: The `evaluations` table must contain exactly one row per valid combination of workload, coefficient set (`CLASSICAL` and `YOU` from `coefficients.py`), and restart count (0 through each workload's `max_restarts`). Each row's `restart_positions` must be globally optimal — minimizing `stability_metric` among all possible position subsets of that cardinality. The `recommendations` table must contain the single best configuration per workload.

- **`/app/report.json`**: workload names mapped to `{"coefficient_set", "num_restarts", "restart_positions", "stability_metric"}`, consistent with the recommendations table.

- **`/app/convergence_analysis.json`**: a comparative evaluation of the two coefficient sets. For each workload, simulate eigenvalue evolution with zero perturbation and no restarts using the corrected library. Report the 0-based iteration index at which all simulated singular values first reach within `1e-3` of 1.0, or `null` if not achieved within available iterations. Structure: workload names mapped to `{"CLASSICAL_converge_iter", "YOU_converge_iter", "recommended_set"}`. The `recommended_set` is whichever converges in fewer iterations; if tied or both null, prefer whichever achieves the lower `stability_metric` at the workload's `max_restarts` in the evaluations.