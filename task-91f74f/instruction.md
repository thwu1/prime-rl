A multi-stage evaluation pipeline at `/app/` processes clinical challenge submissions across segmentation, staging, and survival prognosis tasks.

The pipeline is orchestrated by `/app/Makefile` with stages for data ingestion (importing survival predictions from NDJSON files into SQLite), evaluation (computing metrics and rankings), and output validation.

Segmentation and staging data are pre-loaded in `/app/submissions.db`. Survival predictions are in per-team NDJSON files under `/app/raw_predictions/` and must be ingested into the database's `survival` table (schema present but empty) before evaluation can proceed.

The data ingestion commands (`jq` transformations and `sqlite3` imports), the Makefile orchestration, and the evaluation engine (`/app/evaluate.py`) all contain bugs. The rank-stability analysis described in `/app/methodology.md` has not been implemented.

The evaluation methodology specification is at `/app/methodology.md`, runtime parameters at `/app/eval_config.toml`, and validated spot-check values at `/app/audit.json`.

Produce two output files:
- `/app/results.json`
- `/app/stability.json`

Both must conform to the output schemas in the methodology specification and be consistent with all audit reference values within stated tolerances.