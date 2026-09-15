# Gaze Analysis Pipeline — Specification

## Data

Raw eye-tracking data from 8 participants reading 6 texts at 1000 Hz.

Files in `/app/data/`:

| File | Columns |
|------|---------|
| `raw_gaze.csv` | timestamp_ms, x_px, y_px, pupil_diameter, participant_id, text_id |
| `word_aois.csv` | text_id, word_index, x_min, y_min, x_max, y_max, word |
| `participants.csv` | participant_id, reading_skill_score, is_l2_reader |
| `stimuli.csv` | text_id, difficulty_level, num_words |

Data notes:
- Blink samples are encoded as `pupil_diameter = 0` with gaze position `(0, 0)`.
- Each (participant, text) pair constitutes one trial (48 trials total).

## Required Interfaces

`/app/pipeline.py` must expose these functions:

### `detect_fixations_ivt(timestamps, x_pos, y_pos, pupil_diam, velocity_threshold=100.0, min_duration_ms=80)`

Velocity-based fixation detection. Returns a list of dicts, each with keys:
`onset_ms`, `offset_ms`, `duration_ms`, `centroid_x`, `centroid_y`.

### `compute_word_measures(mapped_fixations, n_words)`

Compute per-word reading measures from temporally ordered fixations
(each dict must have `word_index` and `duration_ms`).
Returns `{word_index: {FFD, GD, TRT, skip, regression}}`.

## Output Schema

`/app/results.json`:
```json
{
  "fixation_summary": {
    "total_fixations": "<int>",
    "mean_fixation_duration_ms": "<float>",
    "mean_saccade_amplitude_px": "<float>"
  },
  "reading_measures_summary": {
    "mean_FFD": "<float>",
    "mean_GD": "<float>",
    "mean_TRT": "<float>",
    "overall_skip_rate": "<float>",
    "overall_regression_rate": "<float>"
  },
  "evaluation": {
    "unseen_reader": {"rmse": "<float>", "r2": "<float>"},
    "unseen_text": {"rmse": "<float>", "r2": "<float>"},
    "unseen_both": {"rmse": "<float>", "r2": "<float>"}
  },
  "split_sizes": {
    "unseen_reader": {"n_folds": "<int>", "mean_train_size": "<int>", "mean_test_size": "<int>"},
    "unseen_text": {"n_folds": "<int>", "mean_train_size": "<int>", "mean_test_size": "<int>"},
    "unseen_both": {"n_folds": "<int>", "mean_train_size": "<int>", "mean_test_size": "<int>"}
  }
}
```

## Cross-Validation Protocol

Three regimes for predicting `reading_skill_score` from trial-level features:

- **unseen_reader**: leave-one-reader-out
- **unseen_text**: leave-one-text-out
- **unseen_both**: hold out one (reader, text) pair; training set excludes all trials involving the held-out reader OR the held-out text

## Reading Measure Definitions

| Measure | Definition |
|---------|-----------|
| FFD | Duration of the first fixation on a word during first-pass reading |
| GD | Sum of all fixation durations on a word during first-pass |
| TRT | Sum of all fixation durations on a word across all passes |
| skip | Word received no fixation during first-pass reading |
| regression | Word received fixation during second-pass (re-reading) |

First-pass reading of a word ends when gaze leaves that word for the first time.
