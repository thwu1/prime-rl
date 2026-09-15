Build `/app/emg_pipeline.py`, a standalone CLI tool for multi-channel surface EMG signal processing and analysis.

**Usage**: `python3 /app/emg_pipeline.py --input <csv> --config <json> --output <dir>`

**Input**: CSV file — N rows × C columns (samples × channels), no header, comma-delimited floats. Must handle single-channel input.

**Config** (`--config`): JSON object with fields:
- `sampling_frequency` (float): sampling rate in Hz
- `window_size` (int): samples per analysis window
- `window_increment` (int): stride between consecutive windows
- `filters` (array, optional): ordered filter specifications — supported types: `bandpass` (with `cutoff` [low, high] array and `order`), `highpass` (with scalar `cutoff` and `order`), `notch` (with scalar `cutoff` and `bandwidth`). Filters are applied sequentially via zero-phase IIR filtering per `/app/reference/filtering.py` conventions. Skip filtering if absent or empty.
- `features` (array): feature group names and/or individual feature names
- `labels_file`, `predictions_file` (string, optional): paths to integer-valued label/prediction CSVs
- `null_label` (int, optional): the null/rest class label for AER computation

**Feature groups** expand to individual output keys:
- `HTD` → `MAV`, `ZC`, `SSC`, `WL`
- `TDPSD` → `M0`, `M2`, `M4`, `SPARSI`, `IRF`, `WLF`
- `HJORTH` → `ACT`, `MOB`, `COMP`

Individual features `SAMPEN`, `FUZZYEN`, `MDF`, `MNF` may also appear directly. When a group and one of its member features both appear, each feature must appear exactly once in the output (deduplicate).

**Output** (in `--output` directory):
- `features.json`: `{"<name>": [[ch0_w0, ch1_w0, …], …]}` — 2D array (windows × channels) per feature.
- `summary.json`: `{"num_windows": int, "num_channels": int, "features_extracted": [str], "sampling_frequency": float}` — `features_extracted` lists individual feature names after group expansion and deduplication.
- `metrics.json` (only when both `labels_file` and `predictions_file` are provided): `{"CA": float, "AER": float, "INS": float, "REJ_RATE": float, "F1": float, "CONF_MAT": [[int]]}`. Prediction value −1 denotes a rejection. Rejected samples are excluded before computing CA, AER, INS, F1, and CONF_MAT; REJ_RATE is computed on the original prediction array.

**Reference material**: `/app/reference/` contains source modules from the libEMG biosignal processing library defining windowing conventions, filtering approach, feature extraction algorithms (including entropy-based features with specific normalization and pattern-matching conventions), and classification metric computations. Your pipeline's outputs must match these reference implementations numerically. The reference code may contain subtle discrepancies from textbook definitions — some are intentional conventions, others are bugs you must diagnose and correct.
