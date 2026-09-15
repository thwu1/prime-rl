`/app/` contains artifacts from a COBS-postcard sensor telemetry system:

- `/app/capture.bin` — binary capture: 8-byte header (`PCOB` magic, u16le frame count, 2 reserved), then COBS-framed postcard messages delimited by `0x00`. Some frames are corrupted.
- `/app/buggy_decoder.py` — Python decoder with exactly 3 bugs; its output is in `/app/buggy_output/`.
- `/app/libcobs/` — unbuilt C reference decoder (correct): `cobs_postcard.{c,h}`, `decode_capture.c`, `Makefile`.
- `/app/protocol_reference.md` — COBS framing, LEB128 varint, zigzag encoding specs.
- `/app/schema.json` — v1 struct schema.
- `/app/reference_hex.json` — raw postcard payload hex for select frames.
- `/app/incident_report.txt` — production incident symptoms.
- `/app/v2_delta.json` — proposed v2 schema evolution (type narrowing, field addition with partial sensor mapping, unit scaling, enum reordering, type widening).

Build the C reference decoder, cross-validate against the buggy Python decoder, diagnose all 3 bugs, produce correct decoded output, and evaluate v2 schema migration backward compatibility.

Produce the following in `/app/results/`:

**`bug_report.json`** — Array of 3 objects: `{"component", "bug_description", "fix_description"}`.

**`summary.json`** — `{"total_frames", "valid_frames", "corrupted_frames", "unique_sensors": [sorted ints]}`.

**`decoded.csv`** — Header: `frame_idx,sensor_id,timestamp_ms,temperature_cdeg,humidity_pct_x10,pressure_pa,battery_mv,status,num_sub_readings`. One row per valid frame in stream order. `status` is the enum variant name. `num_sub_readings` is the sub_readings sequence length.

**`per_sensor.json`** — Keyed by sensor_id string. Each value: `{"count", "avg_temperature_cdeg" (float 2dp), "min_temperature_cdeg", "max_temperature_cdeg", "error_count", "total_sub_readings"}`.

**`anomalies.json`** — Array of `{"frame_idx", "sensor_id", "reasons": [sorted]}` for valid frames with Error status, temperature_cdeg > 450, or temperature_cdeg < -350. Ordered by frame_idx. Reason strings: `error_status`, `high_temperature`, `low_temperature`.

**`conformance.json`** — C-vs-Python cross-validation: `{"c_decoder_valid_frames", "python_decoder_valid_frames", "frames_compared", "frames_matching", "discrepancies": []}`. Zero discrepancies expected.

**`migration_analysis.json`** — V2 backward-compatibility evaluation: `{"schema_changes": [array], "total_valid_frames", "fully_lossless_frames", "lossy_frames"}`. Each change: `{"field", "change", "compatibility": "lossless"|"lossy", "reason", "affected_frame_count"}`. A frame is fully lossless only when all schema changes are lossless for that frame's data.