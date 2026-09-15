A national laboratory is procuring a next-generation supercomputer. Benchmark results from three scientific applications -- molecular dynamics (LAMMPS), lattice quantum chromodynamics (MILC), and a machine-learning scientific workflow (ML4NSE) -- have been collected from the proposed system and must be evaluated against the facility's procurement scoring methodology.

The evaluation specification, raw benchmark output logs, validation tools, and output schemas are provided under `/app/`. Study these materials to understand the required performance metrics, scientific validation procedures, and procurement scoring methodology, then process the benchmark logs to produce:

1. `/app/milc_validations/` -- Per-log validation output from the tool specified in the evaluation specification, one file per MILC log.

2. `/app/results.db` -- SQLite database conforming to `/app/db_schema.sql`.

3. `/app/report.json` -- Procurement evaluation report conforming to `/app/schema.json`.

## Available Materials

- `/app/spec.toml` -- Evaluation specification (metrics, validation, scoring, tools)
- `/app/system.toml` -- Proposed system configuration
- `/app/schema.json` -- Report schema
- `/app/db_schema.sql` -- Database schema
- `/app/logs/` -- Raw benchmark output logs
- `/app/tools/` -- Validation tools referenced by the specification