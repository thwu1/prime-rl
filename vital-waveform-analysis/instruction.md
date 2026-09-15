Build `/app/vital_parser.py` and `/app/analyzer.py` for parsing VitalDB `.vital` binary recordings and analyzing perioperative biosignals from the VitalDB open surgical dataset.

A reference implementation of a `.vital` file reader exists at `/app/reference/vitaldb_utils.py`. Your parser must be standalone — it must not import `vitaldb` or the reference file at runtime.

**`/app/vital_parser.py`** — Two module-level functions:

`parse(path: str) -> dict` returning:
```json
{"tracks": [{"name": str, "type": "wav"|"num"|"str", "unit": str, "srate": float, "fmt": int, "gain": float, "offset": float, "num_records": int}], "devices": [{"name": str, "type": str}], "duration_sec": float, "dtstart": float, "dtend": float}
```
Track names use `DeviceName/TrackName` convention when a device is associated.

`get_track_samples(path: str, track_name: str, interval: float) -> numpy.ndarray` — Dense float32 array at the requested sampling interval (seconds), NaN-filled for gaps. Integer-format waveform tracks must be converted to physical units. Numeric tracks place each value at its floor-indexed time position. Returns a NaN-filled array when the requested track does not exist.

**`/app/analyzer.py`** — CLI: `python3 /app/analyzer.py --case-id <ID> --output <path>`

Downloads `https://api.vitaldb.net/1.0.1/<ID>.vital`, parses it with your vital_parser module, and writes a JSON report:

```json
{
  "case_id": int, "duration_sec": float, "num_tracks": int,
  "tracks": [{"name": str, "type": str, "unit": str, "srate": float}],
  "derived_hr": {"mean": float, "std": float, "median": float},
  "device_hr": {"mean": float, "std": float, "median": float},
  "hr_correlation": float, "hr_mae_bpm": float,
  "hrv_sdnn_ms": float, "hrv_rmssd_ms": float,
  "hypotension_episodes": int, "hypotension_total_sec": float,
  "tachycardia_episodes": int, "tachycardia_total_sec": float
}
```

- `derived_hr`: statistics from heart rate computed from the raw `SNUADC/ECG_II` waveform (500 Hz), at 1-second resolution
- `device_hr`: statistics from `Solar8000/HR`
- `hr_correlation` / `hr_mae_bpm`: Pearson r and mean absolute error between derived and device HR
- `hrv_sdnn_ms` / `hrv_rmssd_ms`: time-domain heart rate variability computed from beat-to-beat intervals (milliseconds)
- Hypotension: `Solar8000/ART_MBP` below 65 mmHg for >= 60 consecutive seconds
- Tachycardia: derived heart rate exceeding 100 bpm for >= 30 consecutive seconds

Null any field whose source track is absent. On case 1: `hr_correlation` > 0.6 and `hr_mae_bpm` < 10.
