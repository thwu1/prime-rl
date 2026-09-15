`/app/` contains a framework for evaluating Newton-Schulz polar decomposition coefficient schedules. The components:

- `/app/polar_solver.py` — Standard and Gram Newton-Schulz solvers, eigenvalue simulation, stability analysis, and restart optimization
- `/app/coefficient_designer.py` — Coefficient schedule design and evaluation
- `/app/configs/` — Baseline configurations (`schulz_classic`, `schulz_conservative`)
- `/app/matrix_specs.json` — Test matrix specifications and stability eigenvalue parameters
- `/app/scripts/`, `/app/Makefile` — Evaluation pipeline (jq, sqlite3, shell, Python) producing benchmarks and a ranked JSON report
- `/app/benchmark_schema.sql` — Database schema
- `/app/design_spec.json` — Coefficient design constraints

The framework has defects across multiple components — in the numerical solver, the analysis functions, and the build pipeline. Make it fully functional so that all of the following hold:

**Solver correctness**: `gram_newton_schulz` must produce polar factors equivalent to `standard_newton_schulz` for all matrix shapes — wide (n<m), tall (n>m), square, and batched (3D) inputs — both with and without restarts. Relative difference must be < 1e-6 without restarts and < 1e-5 with restarts. The Gram variant operates on the symmetric Gram matrix R = XX^T with an accumulator Q, yielding Q @ X as the final result.

**Analysis correctness**: `stability_metric` must return the worst-case condition number max(|q|)/min(|q|) across all Newton-Schulz iterations, consistent with its docstring. `find_optimal_restarts` must return the restart positions (from exhaustive search over all combinations) that minimize the stability metric. `analyze_convergence` must produce decreasing per-iteration orthogonality errors for both wide and tall inputs.

**Custom schedule**: `/app/configs/custom_optimized.json` must contain a novel 5-iteration coefficient schedule with all positive leading coefficients (a > 0), at least one non-zero quadratic term, distinct from `schulz_classic`, `schulz_conservative`, and the reference coefficients `[[4.0848,-6.8946,2.9270],[3.9505,-6.3029,2.6377],[3.7418,-5.5913,2.3037],[2.8769,-3.1427,1.2046],[2.8366,-3.0525,1.2012]]`, achieving lower average orthogonality error than `schulz_conservative` on the test matrices. The config must follow the same JSON schema as the existing configs in `/app/configs/`.

**Pipeline output**: `make -C /app all` must produce `/app/benchmark.db` (SQLite with 3 configurations, 6 matrices, 18 benchmark rows, 9 stability rows) and `/app/evaluation_report.json` (3 configurations ranked by `avg_orthogonality_error`, each with `name`, `avg_orthogonality_error`, `stability_metric`, `optimal_restarts_1`, and `rank`; `schulz_conservative` at rank 3). The report's stability metrics must match the no-restart entries in the database.