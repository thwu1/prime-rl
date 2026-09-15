The calibration evaluation pipeline at `/app/` assesses post-hoc calibration quality for a 5-class classifier. It uses a SQLite database (`/app/calibration.db`) for data storage, a `Makefile` for orchestration, and `jq`-based schema validation.

Running `make all` in `/app/` should execute the full pipeline: generate deterministic predictions into SQLite, run calibration methods, validate the output JSON schema, and produce a summary report. The pipeline currently fails at multiple stages. Diagnose and fix all issues so that `make all` completes successfully.

The SQLite database stores prediction data in tables `train_logits` (sample_id, class_id, logit), `train_labels` (sample_id, label), `test_logits`, `test_labels`, and `metadata`.

Extend the pipeline with two additions, updating `/app/config.json`:

- A `bbq` calibration method (Bayesian Binning into Quantiles) — an ensemble over histogram binning models scored by an information criterion.
- A `brier` metric — the mean squared error between top-class confidence and binary correctness indicator.

**Output schema** (`/app/results.json`):

```json
{
  "uncalibrated": {"ece": float, "mce": float, "ace": float, "brier": float},
  "histogram_binning": {
    "ece": float, "mce": float, "ace": float, "brier": float,
    "calibrated_confidences": [float, ...]
  },
  "temperature_scaling": {
    "ece": float, "mce": float, "ace": float, "brier": float,
    "optimal_temperature": float,
    "calibrated_confidences": [float, ...]
  },
  "bbq": {
    "ece": float, "mce": float, "ace": float, "brier": float,
    "calibrated_confidences": [float, ...],
    "num_models_selected": int,
    "model_weights": [float, ...]
  }
}
```

**Success criteria**:

- `make all` in `/app/` completes without errors
- Calibration metrics (ece, mce, ace, brier) match standard definitions within 1e-4
- `temperature_scaling.optimal_temperature` correct within 1e-3
- All `calibrated_confidences` in [0, 1] with length equal to test set size
- `bbq` ECE strictly less than uncalibrated ECE; `model_weights` sum to 1.0 (±1e-6), length equals `num_models_selected`
- `/app/validate.sh /app/results.json` exits 0
- SQLite table `results` in `/app/calibration.db` with columns (`method` TEXT, `metric` TEXT, `value` REAL) has one row per (method, scalar metric) pair
- `/app/report.txt` has header then tab-separated method/metric/value rows
- `/app/config.json` lists `bbq` in methods and `brier` in metrics
