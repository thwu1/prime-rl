The `/app/` directory contains a multi-tool verification pipeline for a multiphase particle-settling simulation code. The pipeline has multiple broken components across different tools.

The verification framework at `/app/mflow_verify.py` implements drag correlation, particle-settling, and grid-convergence analyses using parameters from `/app/config.toml`, but produces physically incorrect results.

A `Makefile` at `/app/Makefile` is intended to orchestrate the pipeline stages but has broken dependency targets and a disconnected build graph. A gnuplot script at `/app/plot_convergence.gp` should generate a convergence visualization but contains errors in terminal type, axis scaling, data column references, and fit model specification.

A SQLite database at `/app/history.db` stores outputs from 12 past code revisions across a normalized schema with five tables (`runs`, `drag_data`, `settling_params`, `settling_fronts`, `mms_data`) — reconstructing any single run's full results requires querying and joining across these tables. A `run_summary` view is also available.

The helper script `/app/extract_convergence.py` converts MMS results from JSON to TSV format for gnuplot consumption.

Produce the following:

1. `/app/report.json` conforming to `/app/expected_schema.json`, containing:
   - A `"verification"` section with physically correct results for all three analyses (drag coefficients, particle settling front positions, and MMS grid convergence demonstrating the scheme's formal spatial accuracy order)
   - An `"audit"` section classifying each historical run in the database (keyed by string `run_id`, `"1"` through `"12"`) with `"status"` (`"correct"` or `"defective"`) and `"defect_type"` (`null` for correct runs, or a keyword identifying the defect category)

2. `/app/convergence.tsv` — tab-separated MMS grid convergence data (grid_level and l2_norm, one pair per line, sorted by grid level) derived from the corrected verification analysis

3. `/app/convergence.png` — a valid PNG convergence plot generated using gnuplot

4. A corrected `/app/plot_convergence.gp` that independently regenerates `convergence.png` from `convergence.tsv` when executed via `gnuplot plot_convergence.gp` in `/app/`