# Data Format Reference

## Input

### Gaze Data (`{data_dir}/gaze/`)

One CSV per trial. Filename format: `{reader_id}_{passage_id}.csv`.

| Column | Type | Description |
|--------|------|-------------|
| `timestamp_ms` | int | Sample timestamp in milliseconds (1000 Hz sampling rate) |
| `x_deg` | float | Horizontal gaze position in degrees of visual angle |
| `y_deg` | float | Vertical gaze position in degrees of visual angle |

Missing data (blinks, track loss) is encoded as `NaN`. Samples within 50 ms of any NaN gap boundary should be treated as contaminated by pupil-recovery artifacts and excluded before event detection.

### Word Interest Areas (`{data_dir}/aois.csv`)

| Column | Type | Description |
|--------|------|-------------|
| `passage_id` | str | Passage identifier |
| `word_idx` | int | 0-based word index within passage |
| `word_text` | str | The word text |
| `x_min` | float | Left edge of bounding box (degrees) |
| `y_min` | float | Top edge of bounding box (degrees) |
| `x_max` | float | Right edge of bounding box (degrees) |
| `y_max` | float | Bottom edge of bounding box (degrees) |

## CLI Interface

```
python3 /app/analyze.py [--data-dir DIR] [--output-dir DIR]
```

Defaults: `--data-dir /app/data`, `--output-dir /app/output`. Create the output directory if it does not exist.

## CSV Output

### `fixations.csv`

| Column | Type | Description |
|--------|------|-------------|
| `trial_id` | str | Trial identifier (filename without `.csv` extension) |
| `onset_ms` | int | Fixation onset timestamp |
| `offset_ms` | int | Fixation offset timestamp |
| `duration_ms` | int | Fixation duration in ms |
| `x_center` | float | Centroid x position during the fixation (degrees) |
| `y_center` | float | Centroid y position during the fixation (degrees) |
| `word_idx` | int | Index of the fixated word, or -1 if off-text |
| `landing_position` | float | Relative position within the word (0.0 = left edge, 1.0 = right edge), -1 for off-text |

### `saccades.csv`

| Column | Type | Description |
|--------|------|-------------|
| `trial_id` | str | Trial identifier |
| `onset_ms` | int | Saccade onset timestamp |
| `offset_ms` | int | Saccade offset timestamp |
| `duration_ms` | int | Saccade duration in ms |

### `reading_measures.csv`

One row per word per trial. Include all words in the passage, even those never fixated.

| Column | Type | Description |
|--------|------|-------------|
| `trial_id` | str | Trial identifier |
| `word_idx` | int | Word index within passage |
| `first_fixation_duration` | int | FFD in ms (0 if no first-pass fixation) |
| `gaze_duration` | int | GD in ms (0 if no first-pass fixation) |
| `go_past_time` | int | GPT / regression-path duration in ms (0 if skipped) |
| `total_reading_time` | int | TRT in ms (0 if never fixated) |
| `was_skipped` | int | 1 if skipped, 0 otherwise |
| `was_regressed_to` | int | 1 if regressed to, 0 otherwise |
| `first_fixation_landing` | float | Landing position of first first-pass fixation (0-1 scale), -1 if no first-pass fixation |

## SQLite Database (`{output_dir}/gaze.db`)

Created by the Makefile using the `sqlite3` CLI by importing the three CSV files.

### Tables

`fixations`, `saccades`, `reading_measures` — column names match the CSV headers.

### Views

**`reader_summary`** — Per-reader aggregate statistics:

| Column | Description |
|--------|-------------|
| `reader_id` | Reader identifier (portion of `trial_id` before `_`) |
| `mean_ffd` | Average FFD of non-skipped words |
| `mean_gd` | Average GD of non-skipped words |
| `skip_rate` | Fraction of words skipped (0.0–1.0) |
| `regression_rate` | Fraction of words regressed to (0.0–1.0) |

**`passage_difficulty`** — Per-passage aggregate statistics:

| Column | Description |
|--------|-------------|
| `passage_id` | Passage identifier (portion of `trial_id` after `_`) |
| `mean_trt` | Average total reading time |
| `mean_skip_rate` | Fraction of words skipped (0.0–1.0) |

**`processing_difficulty`** — Per-passage per-word processing difficulty:

| Column | Description |
|--------|-------------|
| `passage_id` | Passage identifier |
| `word_idx` | Word index within passage |
| `mean_gpt` | Average go-past time (non-skipped words) |
| `regression_cost` | mean_gpt − mean_gd for non-skipped words |
| `mean_landing` | Average first-fixation landing position (non-skipped) |

## Makefile (`/app/Makefile`)

| Target | Behavior |
|--------|----------|
| `all` | Default target. Runs `analyze.py` then creates the SQLite database via `sqlite3` CLI. |
| `clean` | Removes the entire output directory. |

## Reading Measure Definitions

**First-pass reading**: A fixation on word *W* is classified as first-pass if the reader has not previously fixated any word at a position beyond *W* in the same trial. Once reading advances past a word, any later fixation on it is a regression (second-pass).

- **First fixation duration (FFD)**: Duration of the first first-pass fixation on the word.
- **Gaze duration (GD)**: Sum of all first-pass fixation durations on the word.
- **Go-past time (GPT)** / regression-path duration: Sum of all fixation durations from the first first-pass fixation on the word until the reader's gaze first moves to a word with index greater than this word. Includes time spent on regressions to earlier words before advancing. GPT ≥ GD always holds.
- **Total reading time (TRT)**: Sum of all fixation durations on the word (first-pass and second-pass combined).
- **Skipped**: A word is skipped if it receives no first-pass fixation yet the reader progressed past it.
- **Regressed to**: A word is regressed to if it receives any second-pass fixation.
- **First fixation landing position**: Relative horizontal position within the word AOI where the first first-pass fixation lands. Calculated as (fixation_x − word_x_min) / (word_x_max − word_x_min).
