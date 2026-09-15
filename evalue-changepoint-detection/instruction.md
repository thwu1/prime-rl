A change-point detection system at `/app/` is producing incorrect results. The system is a Python package at `/app/evalue/` with a detection script `/app/detect.py` that processes data streams from `/app/data/streams.json` using null hypothesis parameters from `/app/data/manifest.json`.

When run, the system misidentifies which streams contain genuine distributional changes, and its confidence intervals are miscalibrated. The bugs are in the mathematical implementation, not in data loading or I/O.

Diagnose and fix the implementation so that `python3 /app/detect.py` produces a correct `/app/results.json` satisfying:

- An entry for each of the five streams with keys: `change_detected` (bool), `change_points` (list of 1-indexed alarm times), `final_e_process` (float), `n_alarms` (int)
- Correct discrimination between streams with genuine distributional shifts and the stationary stream
- A `confidence_sequence` key with coverage data for `stream_1` at sample sizes 50, 100, 200, 500, and 1000 — each mapping to `{"lower", "upper", "mean"}` — where intervals computed before any distributional shift contain the true null mean