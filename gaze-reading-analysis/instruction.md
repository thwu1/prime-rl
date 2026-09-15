Raw 1000 Hz gaze position recordings from a reading experiment are at `/app/data/`. Three participants (varying reading skill) each read two passages (20 words each); gaze traces are CSV files in `/app/data/gaze/` (filename: `{reader}_{passage}.csv`) with blink periods encoded as NaN. Word bounding boxes are in `/app/data/aois.csv`.

Build a psycholinguistically valid analysis system that extracts oculomotor events from the raw position signal, computes standard reading measures, and produces a queryable analytical database. Data format specifications and reading measure definitions are in `/app/spec.md`.

## Deliverables

**`/app/analyze.py`** — Python script (`--data-dir`, `--output-dir` arguments, defaults `/app/data`, `/app/output`). Writes:

- `/app/output/fixations.csv` — columns: `trial_id`, `onset_ms`, `offset_ms`, `duration_ms`, `x_center`, `y_center`, `word_idx`, `landing_position`. Minimum fixation duration 80 ms. `landing_position`: relative horizontal position within the word AOI (0.0 = left edge, 1.0 = right edge), -1 for off-text fixations.

- `/app/output/saccades.csv` — columns: `trial_id`, `onset_ms`, `offset_ms`, `duration_ms`. Minimum saccade duration 6 ms.

- `/app/output/reading_measures.csv` — per-word per-trial psycholinguistic measures: `trial_id`, `word_idx`, `first_fixation_duration`, `gaze_duration`, `go_past_time`, `total_reading_time`, `was_skipped`, `was_regressed_to`, `first_fixation_landing`. 120 rows total. Constraints: FFD <= GD <= GPT; FFD <= GD <= TRT; all non-negative. Skipped words: FFD = GD = GPT = 0. `first_fixation_landing`: landing position of the first first-pass fixation (-1 if no first-pass fixation).

**`/app/Makefile`** — targets `all` (default: analysis then database creation via `sqlite3` CLI) and `clean`. Correct dependency tracking.

**`/app/output/gaze.db`** — SQLite database created via `sqlite3` CLI (not Python sqlite3 module). Tables: `fixations`, `saccades`, `reading_measures`. Views:
- `reader_summary`: per-reader — `reader_id`, `mean_ffd`, `mean_gd`, `skip_rate`, `regression_rate` (non-skipped word averages).
- `passage_difficulty`: per-passage — `passage_id`, `mean_trt`, `mean_skip_rate`.
- `processing_difficulty`: per-passage per-word — `passage_id`, `word_idx`, `mean_gpt`, `regression_cost` (mean go-past time minus mean gaze duration for non-skipped words), `mean_landing`.