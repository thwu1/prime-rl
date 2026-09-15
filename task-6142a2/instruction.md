A CDC FluSight-style forecast hub is configured at `/app/`. Your job is to build an evaluation pipeline that validates model submissions, scores them against observed data, ranks models, constructs an optimal ensemble, and exports results in multiple storage formats.

## Environment

- `/app/hub-config/tasks.json` — Hubverse task configuration (JSON) defining valid targets, required quantile levels, submission constraints, and forecast horizons
- `/app/data/forecasts/` — Model forecast submissions in mixed file formats (CSV, Apache Parquet, newline-delimited JSON)
- `/app/data/observations.db` — SQLite database containing table `weekly_admissions` (columns: `date`, `location`, `location_name`, `value`) with observed weekly hospital admission counts
- `/app/data/locations.csv` — Jurisdiction metadata

## Required Outputs

All outputs must be written to `/app/output/`. All numeric values rounded to 4 decimal places.

### `validation_manifest.json`

A JSON object extracted from the hub task configuration with exactly these keys:
- `required_quantiles`: sorted array of required quantile levels (numbers)
- `value_minimum`: minimum allowed forecast value (number)
- `required_horizons`: sorted array of required horizons (numbers)
- `required_locations`: sorted array of required location codes (strings)

### `wis_scores.csv`

Per-forecast Weighted Interval Score with three-component decomposition. Each model submission must first be validated against the hub task configuration; submissions that fail validation (incomplete quantile sets, constraint violations) must be excluded from all scored outputs. Columns: `model_id`, `reference_date`, `location`, `horizon`, `target_end_date`, `observed`, `wis`, `dispersion`, `overprediction`, `underprediction`. Sorted by model_id, reference_date, location, horizon.

### `coverage.csv`

Empirical prediction interval coverage rates. Columns: `model_id`, `coverage_50`, `coverage_95`, `n_forecasts`.

### `model_rankings.csv`

Pairwise relative WIS model rankings. Columns: `rank`, `model_id`, `mean_wis`, `relative_wis`. Rank 1 = best. The product of all models' `relative_wis` values should be approximately 1.0 (geometric mean normalization property).

### `ensemble_weights.csv`

Optimal ensemble weights that minimize mean WIS of the combined quantile forecast (linear opinion pool). Columns: `model_id`, `weight`. Weights must be non-negative and sum to 1.

### `ensemble_evaluation.csv`

Performance comparison of all validated models plus an optimized ensemble named `Ensemble-Trained`. Columns: `model_id`, `mean_wis`, `relative_wis`. The ensemble's `relative_wis` is its mean WIS divided by the arithmetic mean of all component models' mean WIS values. Sorted by `mean_wis` ascending.

### `results.db`

A SQLite database mirroring all CSV report data. Tables: `wis_scores`, `coverage`, `model_rankings`, `ensemble_weights`, `ensemble_evaluation` — each with columns matching the corresponding CSV file.

### `summary.parquet`

A Parquet file containing a left join of `ensemble_evaluation` with `ensemble_weights` on `model_id`. Columns: `model_id`, `mean_wis`, `relative_wis`, `weight` (NULL for Ensemble-Trained). Sorted by `mean_wis` ascending.