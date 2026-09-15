A proprietary industrial monitoring system stored time-series sensor data in a custom binary format. The original software is lost. You have the raw data file, incomplete engineering notes, and a set of records with known correct parsed values.

## Available Files

- `/app/data/sensor_data.bin` — the binary data file (~1.6 MB, 32-byte header + 32-byte records)
- `/app/data/known_records.json` — 20 records with verified field values and byte offsets into the file
- `/app/data/format_notes.md` — incomplete internal engineering notes about the format

## Task

Reverse-engineer the complete binary record format by cross-referencing the known records against the raw bytes. Write a parser that correctly handles all encoding details and edge cases, then produce two JSON output files with aggregate statistics computed from all **production** (non-diagnostic/calibration) records.

### `/app/output/stats.json`

```json
{
  "total_records": "<int: total records in file>",
  "calibration_records": "<int: diagnostic/calibration record count>",
  "production_records": "<int: non-calibration count>",
  "by_type": {"temperature": "<int>", "pressure": "<int>", "humidity": "<int>"},
  "mean_primary": {"temperature": "<float>", "pressure": "<float>", "humidity": "<float>"},
  "unique_sensors": "<int: distinct sensor IDs in production data>",
  "time_span_hours": "<float: hours between earliest and latest record timestamp>"
}
```

### `/app/output/queries.json`

All values computed from production (non-calibration) records only:

```json
{
  "hottest_sensor_id": "<int: sensor ID with highest mean temperature>",
  "max_pressure": "<float: maximum pressure reading>",
  "min_humidity": "<float: minimum humidity reading>",
  "total_temp_records": "<int: temperature record count>",
  "high_quality_count": "<int: records where the quality metric is >= 12>",
  "sensor_7_records": "<int: total records from sensor ID 7>",
  "median_temperature": "<float: median of all temperature values>",
  "pressure_std": "<float: standard deviation of all pressure values>"
}
```

Round all float values to 4 decimal places.