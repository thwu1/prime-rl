The directory `/app/` contains a GPU shared memory bank conflict analysis pipeline. The pipeline simulates warp-level shared memory access patterns and computes bank conflict metrics (wavefronts, total conflicts, conflict-free status) for a set of kernel definitions. Reference metrics from a hardware profiler are stored in a SQLite database at `/app/profiling.db`.

Running `make` in `/app/` executes the simulator and validates its output against the reference data. The validation currently fails — the simulator produces incorrect results for multiple kernels.

Diagnose and fix all issues in the pipeline so that validation passes. Then evaluate the shared memory layout optimization strategies defined in `/app/strategies.json` for the `column_major` kernel. Compute bank conflict metrics for each strategy using the corrected pipeline parameters and the bank conflict model documented in `/app/spec.md`.

Write `/app/results.json` containing:

- `bugs_found`: array of objects each with keys `file`, `description`, `wrong_value`, `correct_value`
- `corrected_metrics`: object keyed by kernel name, each value having `wavefronts` (int), `total_conflicts` (int), `conflict_free` (bool) — the correct metrics after all fixes
- `optimization_analysis`: object with key `column_major` containing `strategies` (object keyed by strategy name, each with `stride` (int), `wavefronts` (int), `total_conflicts` (int)) and `recommendation` (string naming the best strategy — the one that eliminates bank conflicts with the least memory overhead)