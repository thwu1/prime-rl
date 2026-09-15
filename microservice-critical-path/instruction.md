A SQLite database at `/app/traces.db` contains distributed tracing data collected from a microservice system. It stores span-level records from 10 request traces that enter through a `gateway` service's `handleRequest` operation and fan out across downstream services. The database schema, reference semantics, and any data quality characteristics are yours to discover.

Build `/app/crisp_analyzer.py` that computes the **critical path** for each trace and writes a latency attribution report to `/app/results.json`.

The **critical path** of a request trace is the chain of causally dependent operations whose total duration determines the request's end-to-end latency. Reducing time on any operation in this chain reduces overall latency; operations off this chain could slow down without affecting end-to-end time.

## CLI

```
python3 /app/crisp_analyzer.py \
  --db /app/traces.db \
  --service gateway \
  --operation handleRequest \
  --output /app/results.json
```

## Output (`/app/results.json`)

```json
{
  "service": "gateway",
  "operation": "handleRequest",
  "num_traces": 10,
  "per_trace": [
    {
      "trace_id": "...",
      "end_to_end_us": ...,
      "critical_path": [
        {"service": "...", "operation": "...", "exclusive_us": ..., "inclusive_us": ...}
      ]
    }
  ],
  "percentiles": {
    "p50": {"latency_us": ..., "trace_id": "..."},
    "p95": {"latency_us": ..., "trace_id": "..."},
    "p99": {"latency_us": ..., "trace_id": "..."}
  }
}
```

- `per_trace`: sorted by `trace_id` lexicographically
- `critical_path`: each entry's `inclusive_us` is the span's effective wall-clock duration; `exclusive_us` is `inclusive_us` minus the inclusive times of its direct children that are also on the critical path. Sorted by `exclusive_us` descending; ties broken by `service` then `operation` ascending
- The sum of all `exclusive_us` values on a trace's critical path must equal `end_to_end_us`
- Percentiles: nearest-rank ceiling over end-to-end latencies; ties broken by lexicographically smallest `trace_id`
- All times in microseconds (integer)