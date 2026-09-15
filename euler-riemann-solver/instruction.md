A computational fluid dynamics simulation and validation pipeline at `/app/` is broken and incomplete. The pipeline uses a `Makefile` to orchestrate multiple stages: running a compressible flow solver on standard test problems, performing a mesh convergence study, generating a convergence plot with gnuplot, importing all results into a SQLite database, and running final validation checks.

Currently, `make validate` (run from `/app/`) fails due to multiple issues across the pipeline.

Fix all issues so that `make validate` succeeds when run from `/app/`. Expected outputs:

- `/app/results/sod.csv`, `/app/results/einfeldt.csv`, `/app/results/blast.csv` — physically valid solver output (positive density and pressure everywhere, correct wave structures, conservation laws satisfied to numerical precision)
- `/app/results/convergence.json` — mesh convergence study results with observed convergence rate >= 0.7, monotonically decreasing errors, and `"pass": true`
- `/app/results/convergence_data.csv` — per-resolution error data
- `/app/results/convergence.png` — log-log convergence plot
- `/app/results/results.db` — SQLite database containing all simulation results and convergence data with correct schema and column names