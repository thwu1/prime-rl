The financial ML backtesting system at `/app/` evaluates a classifier on synthetic time-series data. Internal review has flagged its reported performance metrics as unrealistically optimistic — the cross-validated scores suggest near-perfect prediction on inherently noisy data.

Investigate the system, identify the source(s) of metric inflation, and correct the evaluation methodology. Configuration and historical data are distributed across the codebase and its data stores — you will need to explore thoroughly to understand the full picture.

After your corrections, `python3 /app/run.py` must produce `/app/results.json` containing exactly these keys:

- `original_cv_score` (float): mean negative log-loss from the original flawed evaluation. Must be in the range (-0.8, -0.1).
- `corrected_cv_score` (float): mean negative log-loss from your corrected evaluation. Must be in the range (-2.0, -0.3).
- `leakage_ratio` (float): `abs(corrected_cv_score) / abs(original_cv_score)`. Must be in the range (1.02, 15.0), and must be consistent with the reported scores (within 0.15 of the value computed from them).
- `corrected_sampling_uniqueness` (float): mean sample uniqueness under corrected sampling. Must be in (0, 1] and must exceed `baseline_sampling_uniqueness`.
- `baseline_sampling_uniqueness` (float): mean sample uniqueness under original sampling. Must be in (0, 1].
- `n_informative_in_top10` (int): count of informative features among the top-10 by importance. Must be in [0, 10] and at least 3.

## Quantitative requirements

- The corrected CV score must be strictly lower (more negative) than the original CV score.
- The difference `original_cv_score - corrected_cv_score` must exceed 0.02.
- The corrected evaluation must use a custom cross-validation splitter (not a standard sklearn splitter like `KFold` or `StratifiedKFold`) that prevents temporal label overlap: no training observation whose label span overlaps with the test period may appear in the training set for that fold.
- The pipeline must be deterministic: running `python3 /app/run.py` twice must produce `original_cv_score` and `corrected_cv_score` values that agree within 0.01.