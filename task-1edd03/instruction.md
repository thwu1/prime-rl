The `/data/` directory contains a raw, unvalidated export from a software project's bug tracking system.

- `/data/regression_export.csv` — regression dependency records
- `/data/patch_metadata.jsonl` — supplementary bug metadata (partial coverage)
- `/data/output_schema.json` — required analysis output specification
- `/data/README.txt` — data description

Produce a complete regression cascade risk assessment conforming to the structure in `/data/output_schema.json`. Write results to `/app/results.json`.