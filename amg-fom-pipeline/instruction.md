Six candidate HPC systems were evaluated across four CORAL-2-style benchmarks (AMG, Kripke, STREAM, PENNANT). Raw results are in a SQLite database at `/app/benchmark.db`. The database schema is undocumented.

Reference documentation is in `/app/docs/`:
- `benchmark_specs.md` — authoritative FOM formulas and benchmark descriptions
- `benchmark_spec.toml` — machine-readable FOM specification (supplementary; may contain errors)
- `standard_configs.toml` — reference configurations for valid cross-system comparison
- `evaluation_protocol.md` — complete validation methodology, quality dimensions, and deliverable specifications

Scoring parameters and quality thresholds are in `/app/config.toml`.

The evaluation committee suspects systematic data integrity issues in the submitted results, including potential calculation bugs in the vendor FOM submission pipeline. Execute the complete validation protocol defined in `/app/docs/evaluation_protocol.md`, producing all four deliverables in `/app/results/`. The protocol requires data integrity checks, independent FOM recomputation, configuration compliance verification, physical plausibility validation against hardware capabilities, and cross-benchmark consistency analysis.

Where the benchmark specification documents conflict, treat the human-readable Markdown spec as authoritative. The database schema is not documented — explore it to understand the available data.