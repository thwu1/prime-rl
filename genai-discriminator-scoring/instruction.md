An evaluation pipeline for the NIST GenAI Text Challenge discriminator track at `/app/pipeline/` was abandoned mid-development with bugs and misconfigurations across its architecture: `make`, `jq`, shell, `sqlite3`, Python, SQL, and a JSON configuration layer.

**Data** at `/app/data/`:
- `ground_truth.json` — evaluation sets mapping narrative IDs to source labels and human-annotated believability scores
- `predictions/` — six discriminator prediction files in NIST submission format (some may contain format violations)

**Pipeline configuration** at `/app/pipeline/config.json` — parameterizes evaluation behavior (binning granularity, score weights, detection thresholds). Some parameter values may be inconsistent with the evaluation specification or standard statistical practice; where the config disagrees with the reference output, the config is wrong.

**Evaluation specification** at `/app/nist_spec.md` — abbreviated protocol describing evaluation criteria. Certain implementation details (binning, weighting, thresholds) are delegated to the pipeline configuration.

**Reference output** at `/app/reference/reference_output.json` — known-correct evaluation metrics for specific submissions. Your pipeline output must match these values within floating-point tolerance.

Fix and complete the pipeline so it correctly processes all discriminator predictions and produces `/app/output/`:
- `validation_report.json` — per-file format validation results with error details
- `metrics.json` — per-valid-submission evaluation metrics
- `rankings.json` — submissions ranked by composite quality score (descending), excluding entries where the composite score is undefined

All numeric values must be rounded to 6 decimal places.