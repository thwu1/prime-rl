Simulation outputs from 10 branch predictor designs evaluated across 15 benchmark traces (3 workload categories) are in `/app/data/<predictor_name>/` — one `.out` file per trace in 12-field CSV format. Trace metadata with category assignments and deployment importance weights is in `/app/traces.json`. The scoring model, metric definitions, and required output schema are in `/app/spec.md`.

Produce:

- `/app/analysis.db` — SQLite database containing all trace-level simulation records and per-predictor aggregate metrics, with a schema designed for analytical queries.

- `/app/designspace.png` — gnuplot-generated scatter plot of the design space. Non-dominated and dominated designs must be visually distinguished and each predictor labeled.

- `/app/results.json` — Complete design-space analysis conforming to the output schema in `/app/spec.md`.