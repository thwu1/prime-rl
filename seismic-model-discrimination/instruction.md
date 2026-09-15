A newly deployed global seismological monitoring network has accumulated its first batch of teleseismic phase arrival time picks. The raw data is stored at `/app/data/`. Before the network can be declared operational, its data pipeline must be calibrated and validated.

Known issues with the raw data:
- The automatic phase picker's reference Earth velocity model is undocumented.
- Station clocks have not been calibrated — systematic per-station timing biases are expected.
- The automatic picker occasionally misidentifies phases, producing grossly incorrect arrival times mixed in with valid observations.

Produce a calibration report at `/app/results.json`:

```json
{
  "reference_model": "<name>",
  "station_corrections": {"<station>": {"P": <sec>, "S": <sec>}, ...},
  "outlier_indices": [<0-based indices into observations array>],
  "clean_rms": <float>,
  "event_quality": {"<event_id>": {"azimuthal_gap": <degrees>, "quality_class": "<A|B|C|D>"}, ...}
}
```

- `reference_model`: which standard 1D Earth velocity model best explains the clean observations.
- `station_corrections`: estimated per-station per-phase timing biases (seconds) relative to the identified reference model.
- `outlier_indices`: observations identified as gross measurement errors.
- `clean_rms`: RMS of travel time residuals after calibration, computed over clean (non-outlier) picks only, in seconds.
- `quality_class`: azimuthal gap classification — A (gap < 90°), B (90°–180°), C (180°–270°), D (≥ 270°).