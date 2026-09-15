A binary serial capture at `/app/capture.bin` was recorded from an embedded sensor node. The device's firmware source (Rust) is at `/app/firmware/`. The capture contains framed telemetry messages, some of which are malformed.

Write a decoder at `/app/decoder.py` that processes the capture and writes `/app/report.json`. It must be runnable via `python3 /app/decoder.py`.

## Report schema

`/app/report.json` must contain exactly these fields:
- `total_messages` (int): number of frames extracted from the capture
- `valid_count` (int): successfully decoded messages
- `invalid_count` (int): messages that failed to decode
- `type_counts` (object): root enum variant name to count of valid messages of that type
- `messages` (array): ordered per-frame results, each with:
  - `index` (int): zero-based frame position
  - `valid` (bool)
  - Valid messages: `type` (variant name string), `data` (decoded fields as nested objects; enum values as objects with a `_variant` string key plus the variant's field values; `None` options as JSON `null`)
  - Invalid messages: `error_type` (string classification), `error_detail` (string description)