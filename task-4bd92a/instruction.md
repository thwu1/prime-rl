A seismological research group needs a complete pick-benchmark evaluation pipeline. Given a SeisBench-format dataset with model predictions and a configuration file specifying the evaluation protocol, produce three output files that correctly evaluate the model's performance.

## Input

- `/app/dataset/metadata.csv` — Trace metadata: phase arrival columns, sampling rate, sample count, component order, train/dev/test splits.
- `/app/dataset/waveforms.hdf5` — Waveform arrays in SeisBench HDF5 layout.
- `/app/predictions/model_output.hdf5` — Per-trace model prediction arrays under `predictions/{trace_name}`.
- `/app/config.json` — Evaluation protocol specification: phase dictionary mapping variant phase columns to canonical P/S labels, target sampling rate, window parameters, phase spacing constraints, prediction channel layout, scoring formulas, and metric computation instructions.

## Required Output (`/app/output/`)

**`task1_targets.csv`** — Earthquake detection targets for dev/test splits. Columns: `trace_name`, `trace_split`, `sampling_rate`, `start_sample`, `end_sample`, `trace_type` (earthquake/noise). Each trace with arrivals gets an earthquake window containing the first arrival. Traces with sufficient pre-arrival space also get a noise window. Arrival-free traces get a noise window.

**`task23_targets.csv`** — Phase picking targets with isolated phase onsets for dev/test splits. Columns: `trace_name`, `trace_split`, `sampling_rate`, `start_sample`, `end_sample`, `phase_label` (P/S), `phase_onset`. Each arrival that can be isolated from neighbors (respecting the minimum spacing constraint) gets a window. Variant phase types (Pg, Sg, Pn, etc.) must be mapped to canonical P/S labels via the phase dictionary. Arrivals at non-target sampling rates must be converted.

**`metrics.json`** — Benchmark metrics computed by scoring predictions against targets, then optimizing thresholds on dev set and evaluating on test set. Required keys: `det_threshold`, `test_det_f1`, `test_det_precision`, `test_det_recall`, `test_det_auc`, `phase_threshold`, `test_phase_f1`, per-phase onset MAE (`test_P_mae_s`, `test_S_mae_s`), and dev-set counterparts (`dev_det_f1`, `dev_det_auc`).

The scoring formulas, metric computation procedures, and all protocol parameters are specified in `/app/config.json`.