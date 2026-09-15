A forecaster evaluation pipeline at `/app/pipeline/` ranks 25 prediction-market forecasters using five scoring methods against data in `/app/data/forecasts.db`. The pipeline uses `sqlite3` for extraction, `jq` for transformation, and Python for scoring. A prior analysis at `/app/baseline/results.json` has been flagged as unreliable. Reference scoring implementations are at `/app/reference/`. Analyst notes are at `/app/baseline/notes.txt`. Pipeline configuration is at `/app/pipeline/config.json`.

Audit the pipeline, correct all errors, evaluate how much independent information the five scoring methods collectively provide, and produce a principled consensus ranking. Write the complete analysis to `/app/results/audit.json`.

Required output structure:

- `rankings`: keys `brier`, `risk_neutral`, `kelly`, `crra_utility`, `pairwise_skill` — each an array of `{"forecaster_id": "...", "score": ...}` sorted descending, scores rounded to 6 decimal places
- `data_quality`: integer fields `events_total`, `events_resolved`, `forecasts_raw`, `forecasts_clean`, `issues_found`
- `correlation_matrix`: 5×5 Spearman rank correlation matrix between methods in order [brier, risk_neutral, kelly, crra_utility, pairwise_skill], rounded to 6 decimal places
- `method_evaluation`:
  - `eigenvalues`: eigenvalues of the correlation matrix sorted descending, rounded to 6 decimal places
  - `effective_dimensions`: count of eigenvalues ≥ 1.0
  - `method_weights`: per-method importance weight, normalized to sum to 1.0, rounded to 6 decimal places
  - `consensus_ranking`: array of `{"forecaster_id": "...", "score": ...}` sorted descending, rounded to 6 decimal places
  - `stability_analysis`: `max_rank_spread` (forecaster_id → max rank difference across methods), `most_stable_forecaster` (smallest spread, alphabetical tie-break), `least_stable_forecaster` (largest spread, alphabetical tie-break)