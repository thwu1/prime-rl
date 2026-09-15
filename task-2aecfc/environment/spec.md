# SRE Incident Analysis Engine - Algorithm Specification

## Input Files

### metrics.csv

Located at `/app/metrics.csv`. One row per cluster per second. Columns:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp_s` | int | Seconds from simulation start (0-based) |
| `cluster` | str | Cluster identifier (`alpha`, `beta`, `gamma`) |
| `requests` | int | Requests received by this cluster this second |
| `errors` | int | Failed requests this second |
| `avg_latency_ms` | int | Average request latency in milliseconds |

### config.json

Located at `/app/config.json`. Contains SLO definition, alert rules, and failure-detection parameters.

## Algorithms

### 1. Global Per-Second Metrics

For each timestamp `t`, compute the global totals by summing across all clusters:

```
global_requests(t) = sum of requests for all clusters at timestamp t
global_errors(t) = sum of errors for all clusters at timestamp t
```

### 2. Sliding-Window Error Rate

For a window of size `W` seconds evaluated at time `t`:

```
start = max(0, t - W + 1)
error_rate(t, W) = sum(global_errors(s) for s in [start, t]) / sum(global_requests(s) for s in [start, t])
```

If the total requests in the window is 0, the error rate is 0.

Note: when `t < W`, the window is shorter than `W` seconds (it starts at 0). This is expected behavior.

### 3. Multi-Window Multi-Burn-Rate Alert Evaluation

Each alert rule specifies:
- `long_window_s`: Long evaluation window in seconds
- `short_window_s`: Short evaluation window in seconds  
- `burn_rate`: Multiplier on the allowed error rate

The alert threshold is:

```
threshold = burn_rate * (1 - slo_target)
```

An alert **FIRES** at time `t` when **BOTH** conditions are true:
- `error_rate(t, long_window_s) > threshold`  (strict inequality)
- `error_rate(t, short_window_s) > threshold`  (strict inequality)

An alert **RESOLVES** when the short-window error rate drops to or below the threshold (i.e., the short-window condition is no longer met).

Report:
- `fired_at_s`: The **first** timestamp where the alert fires. `null` if it never fires.
- `resolved_at_s`: The **first** timestamp **after** `fired_at_s` where the alert is no longer firing. `null` if the alert is still active at the end of the simulation.
- `active_at_end`: `true` if the alert is still firing at the last timestamp; `false` otherwise.

### 4. Cluster Failure Detection

A cluster is declared **failed** at time `T` if for **all** `t` in `[T - consecutive_seconds + 1, T]`:
- The cluster has `requests > 0` at time `t`, **AND**
- The cluster's per-second error rate (`errors / requests`) strictly exceeds `failure_error_rate_threshold`

The first such `T` is `detected_at_s`. The cluster is considered effectively dead starting from `effective_from_s = detected_at_s + 1`.

If a cluster has `requests = 0` at any second within the consecutive window, that second does **not** count as exceeding the threshold (the consecutive counter resets).

### 5. Error Budget Consumption

```
overall_error_rate = total_errors / total_requests
burn_rate = overall_error_rate / (1 - slo_target)
error_budget_consumed_pct = burn_rate * (simulation_duration_s / (slo_period_days * 86400)) * 100
```

Where `simulation_duration_s` is the total number of seconds in the dataset (count of distinct timestamps).

### 6. Peak Error Rate

Find the per-second global error rate for each timestamp:

```
per_second_error_rate(t) = global_errors(t) / global_requests(t)
```

If `global_requests(t) = 0`, the per-second error rate is 0.

Report the maximum value and the **earliest** timestamp achieving it.

## Output Schema

Write to `/app/output/results.json`:

```json
{
  "summary": {
    "total_requests": <int>,
    "total_errors": <int>,
    "overall_error_rate": <float>,
    "simulation_duration_s": <int>,
    "error_budget_consumed_pct": <float>
  },
  "cluster_failures": [
    {
      "cluster": "<name>",
      "detected_at_s": <int>,
      "effective_from_s": <int>
    }
  ],
  "cascade_sequence": ["<first_failed_cluster>", "<second_failed_cluster>", ...],
  "alerts": [
    {
      "name": "<alert_name>",
      "fired_at_s": <int or null>,
      "resolved_at_s": <int or null>,
      "active_at_end": <bool>
    }
  ],
  "peak_error_rate": <float>,
  "peak_error_rate_time_s": <int>
}
```

**Ordering requirements:**
- `cluster_failures`: sorted by `detected_at_s` ascending
- `cascade_sequence`: ordered by failure time (earliest first)
- `alerts`: sorted by `fired_at_s` ascending (`null` values last)
