Raw seismic waveform data from a heterogeneous multi-station network is at `/app/raw_data/`. Stations in the network record with different sampling rates (100 Hz and 200 Hz) and different component orderings (ZNE and ENZ). Harmonize this data into a valid SeisBench-compatible dataset, compute signal quality metrics, and evaluate model predictions using the seismic benchmark methodology.

## Input Data

- `/app/raw_data/events.json` — earthquake event metadata (ID, location, magnitude, origin time)
- `/app/raw_data/stations.json` — station metadata including native `sampling_rate_hz` and `component_order` per station
- `/app/raw_data/waveforms_info.json` — maps each trace to its event and station
- `/app/raw_data/picks.json` — analyst P and S wave arrival sample indices at each trace's native sampling rate
- `/app/raw_data/waveforms/` — 3-component seismograms stored at native rate and native component ordering (shape varies by station)
- `/app/raw_data/split_assignment.json` — temporal split assignments (train/dev/test)
- `/app/raw_data/predictions/` — model prediction CSVs for detection (`task1_*.csv`) and phase picking (`task23_*.csv`)

## Required Output

### 1. SeisBench-Format Dataset at `/app/output/dataset/`

`metadata.csv` and `waveforms.hdf5` conforming to the SeisBench specification at `/app/docs/seisbench_format.md`. All waveforms must be harmonized to 100 Hz sampling rate with canonical ZNE component ordering. The dataset must use the trace block extension with no cross-split block mixing. `metadata.csv` must include `trace_snr_db` and `trace_quality` columns for earthquake traces.

### 2. Quality Report at `/app/output/quality_report.json`

JSON report with SNR-based quality tier classification for earthquake traces. Tiers: A (SNR >= 10 dB), B (5 <= SNR < 10 dB), C (SNR < 5 dB). Must include `tier_counts` (per-split counts of A/B/C) and `snr_statistics` (mean_db, median_db, min_db, max_db across all earthquake traces).

### 3. Evaluation Results at `/app/output/results.csv`

Benchmark evaluation metrics for all three tasks, computed following the exact methodology in `/app/docs/seisbench_format.md`. Pay close attention to the threshold optimization procedures, the onset-timing residual computation (per-entry sampling rates, correct prediction column per phase), and the statistical definitions for timing metrics.

Columns: `det_precision`, `det_recall`, `det_f1`, `det_auc`, `cls_precision`, `cls_recall`, `cls_f1`, `cls_mcc`, `p_mean_s`, `p_std_s`, `p_mae_s`, `s_mean_s`, `s_std_s`, `s_mae_s`.