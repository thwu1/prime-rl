The directory `/app/` contains:

- `qartod_reference.md` — full specification for QARTOD quality control tests, including flag definitions, algorithm descriptions, edge-case handling rules, and flag aggregation semantics.
- `config.yaml` — per-stream QC test configuration mapping stream names to their enabled tests and threshold parameters.
- `sensor_data.csv` — time-series sensor observations with columns `timestamp`, `depth`, and one column per sensor variable.

Create `/app/run_qc.py`. When executed via `python3 /app/run_qc.py`, it must read the configuration and sensor data, apply every configured QC test to its corresponding data stream according to the reference specification, aggregate each stream's test results into a combined flag array, and write the complete results to `/app/output/flags.json`.

**Output schema** (`/app/output/flags.json`):

```json
{"<stream_name>": {"<test_name>": [int, ...], "aggregate": [int, ...]}}
```

- Each flag array contains only valid QARTOD flag codes (1, 2, 3, 4, or 9).
- Each flag array length equals the number of data rows in the input CSV.
- Test keys match the test names from the configuration.
- The `aggregate` key holds the combined flag array for that stream, computed according to the aggregation rules in the specification.

The pipeline must correctly handle all edge cases described in the specification — missing-value propagation, endpoint boundary conditions, time-unit conversions, depth-direction sign adjustment, rolling-window pre-fill behavior, and period-based temporal matching.
