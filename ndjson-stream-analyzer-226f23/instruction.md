`/app/stream_analyzer.cpp` is a broken NDJSON stream analytics tool built on simdjson. Run `/app/setup_simdjson.sh` to download simdjson, then build with `make -C /app`. The resulting binary must be at `/app/stream_analyzer`.

**Usage:** `/app/stream_analyzer <file> <format> <pointer> <agg> [--group-by <pointer>]`

**Formats:** `auto`, `ndjson`, `rfc7464`. Auto-detection: first non-whitespace byte `0x1E` (Record Separator) selects `rfc7464`; otherwise `ndjson`. For `rfc7464`, all RS bytes must be replaced with newlines before the content reaches simdjson's parser.

**Pointer:** RFC 6901 JSON Pointer (e.g. `/price`, `/metrics/latency`, `/1`).

**Aggregations:**

- `count` — number of successfully extracted values
- `sum`, `min`, `max` — standard aggregations; min/max return `0.0` for empty sets
- `avg` — sum divided by the count of successfully extracted values
- `median` — middle value of sorted extracted values; for even-length sets, average the two middle values
- `stddev` — population standard deviation: `sqrt(sum((xi - mean)^2) / N)` where N = count of extracted values
- `percentile:P` — Pth percentile using linear interpolation on sorted values: rank = P/100 * (N-1); result interpolates between values at floor(rank) and ceil(rank)
- `values` — all extracted doubles as a JSON array in document order

**`--group-by <pointer>`:** Groups documents by the string value at the given pointer. Output includes a `"groups"` object keyed by group value, each entry containing `"count"`, `"sum"`, and `"result"` (the aggregation applied to that group's values). Per-group aggregations must use per-group counts. Both the aggregation value and group key must be extracted from each document.

**Output (JSON to stdout):** `total_documents`, `valid_documents`, `error_documents`, `truncated_bytes`, `detected_format`, `result`. When aggregation is `values`, include a `values` array. When `--group-by` is used, include a `groups` object.

**Requirements:**

- Handle documents up to 10 MB without capacity errors.
- Distinguish parse errors (malformed JSON increments `error_documents`) from valid documents missing the pointer target (neither error nor valid). Check document parse status before field access.
- Report truncated trailing bytes from the document stream.
