Create `/app/calibrate.py` — a pipeline that reads raw vis-NIR soil absorbance spectra from `/app/data/` and builds a calibration model predicting soil organic carbon (OC).

Run `python3 /app/generate_data.py` to populate `/app/data/` with `spectra.csv` (200 samples × 4201 bands), `wavelengths.csv`, and `properties.csv` (columns: sample_id, OC, clay, sand, pH). Pipeline parameters are in `/app/config.json`.

**Required outputs in `/app/output/`:**

`diagnostics.json` — characterize the raw spectral data quality:
- `splice_location_nm`: float — detected wavelength where an instrumental discontinuity occurs between detector regions
- `mean_splice_offset`: float — mean absolute magnitude of the discontinuity across all 200 samples
- `n_bands_processed`: int — columns in the final feature matrix
- `outlier_indices`: sorted list of int — sample indices whose discontinuity magnitude exceeds the dataset mean by more than 2 standard deviations

`preprocessed.csv` — final feature matrix (200 × n_bands_processed), no header, comma-separated. Must contain no NaN/Inf and must have both positive and negative values.

`train_indices.json` / `test_indices.json` — sorted 0-based integer lists forming a complete disjoint partition of [0, 200). Training set: 130–140 samples. The sample-selection strategy must be driven by spectral characteristics, not random.

`predictions.csv` — header `sample_id,observed,predicted`, one row per test sample. Observed values must match source OC properties.

`metrics.json` — keys: `rmsep`, `rpd`, `bias`, `sep_b`, `r_squared`, `n_components` (int).

`cv_curve.json` — list of `{"n_components": <int>, "rmsecv": <float>}` for every component count evaluated during model selection.

**Success criteria:**
- RPD > 1.2, R² > 0.3, |bias| < RMSEP, observed-predicted correlation > 0.5
- RMSEP² ≈ SEP-b² + bias² (≤ 5% relative error)
- RPD = std(observed_test) / RMSEP
- n_components in [1, 20]; cv_curve has monotonically defined entries with minimum RMSECV at n_components
- Preprocessing spot-checks: independent recomputation of 3 sample rows must correlate > 0.99 with your output
- The two spectrally most-distant samples in the selection space must both appear in the training set
- `python3 /app/calibrate.py` must produce all outputs deterministically
