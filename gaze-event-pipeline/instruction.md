Build `/app/gaze_pipeline.py` that processes BIDS-formatted eye-tracking datasets, classifies raw gaze samples into discrete oculomotor events, and stores all results in both BIDS-standard file outputs and a normalized SQLite database.

**Interface**

```
python3 /app/gaze_pipeline.py <input_bids_dir> <output_dir>
```

Exit code 0 on success.

**Input**

A BIDS dataset directory containing `*_recording-*_physio.tsv.gz` physiological recordings with JSON sidecars. Only eye-tracking recordings should be processed. Recordings may vary in sampling frequency, screen geometry, column ordering, and metadata inheritance level. Some may contain signal dropout (missing coordinates, non-zero pupil).

**TSV Output**

For each eye-tracking recording, write `<output_dir>/<recording_entities>_physioevents.tsv.gz` — gzip-compressed, headerless, tab-separated: `onset` (ms), `duration` (ms), `trial_type` (`fixation`/`saccade`/`blink`), `blink` (1 or 0), `amplitude_dva` (degrees of visual angle for saccades, `n/a` otherwise). Events must be onset-sorted, cover the entire recording without gaps or overlaps, and merge contiguous same-type samples.

**SQLite Output**

Write `<output_dir>/pipeline.db` with foreign key enforcement enabled. Required tables:

- `recordings` — `recording_id TEXT PRIMARY KEY`, `subject TEXT`, `task TEXT`, `run TEXT`, `recording TEXT`, `sampling_freq REAL`, `screen_distance REAL`, `screen_width_m REAL`, `screen_height_m REAL`, `screen_res_x INTEGER`, `screen_res_y INTEGER`, `recorded_eye TEXT`
- `events` — `event_id INTEGER PRIMARY KEY AUTOINCREMENT`, `recording_id TEXT REFERENCES recordings(recording_id)`, `onset REAL`, `duration REAL`, `trial_type TEXT`, `blink INTEGER`, `amplitude_dva REAL` (NULL for non-saccades)
- `quality_metrics` — `recording_id TEXT PRIMARY KEY REFERENCES recordings(recording_id)`, `n_fixations INTEGER`, `n_saccades INTEGER`, `n_blinks INTEGER`, `total_duration_sec REAL`, `mean_saccade_amplitude_dva REAL`, `mean_fixation_duration_ms REAL`, `pct_blink REAL`

Events in the database must exactly match the TSV output. Recording metadata must reflect resolved BIDS inheritance (e.g., run-level sidecars override task-level defaults for screen geometry).

**JSON Output**

Write `<output_dir>/quality_report.json` mapping each recording identifier (filename stem without `_physio`) to `{n_fixations, n_saccades, n_blinks, total_duration_sec, mean_saccade_amplitude_dva, mean_fixation_duration_ms, pct_blink}`. Values must match the `quality_metrics` table.

**Environment**

Materials under `/app/specs/` and `/app/reference/` document the BIDS eye-tracking format and provide a reference example pairing raw gaze data with classified events.
