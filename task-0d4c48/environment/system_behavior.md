# Payment Gateway — Operational Behavior Documentation

## Service Architecture

The payment gateway distributes incoming request traffic across multiple backend clusters. Cluster definitions (name, maximum QPS capacity, routing weight, region) are maintained in a YAML topology file. Each cluster independently processes requests up to its capacity; requests exceeding capacity are rejected.

## External Events

Events are scheduled at specific tick numbers in the incident database. Two types:

- **capacity_change**: Updates a named cluster's base capacity. If the cluster is currently `healthy`, its effective capacity updates immediately. Clusters in `crashed` or `recovering` states retain their current effective capacity until their next state transition restores it from the (now updated) base capacity.
- **load_change**: Updates the base incoming traffic rate (`current_base_load`).

Events for a tick take effect before any other activity for that tick.

## Cluster Health & Recovery

Each cluster is in one of three states: `healthy`, `crashed`, or `recovering`. State transitions are resolved before traffic is routed for the current tick.

**Healthy**: Operating at full base capacity. Subject to overload detection.

**Crashed**: Offline — effective capacity is 0, receives no traffic. A crash timer increments each tick spent in this state. After `crash_offline_steps` ticks offline, the cluster transitions to `recovering`: its effective capacity becomes `base_capacity × crash_recovery_capacity_fraction`, and both timers reset to 0.

**Recovering**: Operating at reduced capacity (cold-cache effect). A recovery timer increments each tick spent in this state. After `crash_recovery_steps` ticks, the cluster returns to `healthy` at full base capacity and the recovery timer resets.

## Traffic Distribution

Active clusters — those with status not `crashed` and positive effective capacity — receive traffic proportional to their routing weights.

For each active cluster *c*:

    incoming_c  = effective_load × (weight_c / sum_of_active_weights)
    accepted_c  = min(incoming_c, capacity_c)
    rejected_c  = max(0, incoming_c − capacity_c)
    utilization_c = incoming_c / capacity_c

If no clusters are active, the entire effective load is rejected. Each cluster records incoming=0, accepted=0, rejected=0, utilization=0. The aggregate rejected equals the full effective load.

Aggregates: `total_accepted = Σ accepted_c`, `total_rejected = Σ rejected_c` (across active clusters; inactive ones contribute 0).

## Client-Side Adaptive Throttling

Clients maintain a sliding window — a FIFO queue with a maximum length of `throttle_window_steps` entries. Each entry stores the effective load dispatched and the total requests accepted during a completed tick.

The current tick's values are appended to the window after traffic distribution for that tick completes. The throttle probability applied during a tick is therefore derived from the window's accumulated history of prior ticks only:

    If window is empty:
        throttle_probability = 0
    Otherwise:
        W_req = sum of effective_load values in the window
        W_acc = sum of total_accepted values in the window
        throttle_probability = max(0, (W_req − K × W_acc) / (W_req + 1))

*K* is the configured multiplier (parameter `throttle_K`).

## Retry Behavior

Requests rejected during tick *T* become candidate retries for tick *T+1*. The retry volume is bounded:

    retries = min(pending_rejected_from_previous_tick, retry_budget_fraction × current_base_load)

Total load for a tick: `current_base_load + retries`. The retry pool initializes to zero (no retries on tick 0). After all processing for a tick completes, the pending retry pool is set to that tick's total_rejected.

## Effective Load

    total_load = current_base_load + retries
    effective_load = total_load × (1 − throttle_probability)

## Overload Detection

Each non-crashed cluster with positive capacity tracks the number of **consecutive** ticks where its utilization exceeds `crash_threshold`. When this count reaches `crash_consecutive_steps`, the cluster crashes: status becomes `crashed`, effective capacity drops to 0, the overload counter resets to 0, and the crash timer initializes to 0.

Crash detection evaluates after traffic has been distributed and processed for the current tick. The crashing cluster handled its share of load during this tick — the crash takes effect afterward. In the tick's output, the cluster's status is recorded as `crashed` (reflecting the post-detection state) while its incoming/accepted/rejected/utilization values reflect the traffic it actually processed.

If utilization is at or below the threshold during a tick, the consecutive overload counter resets to 0.

## Global Error Rate

    global_error_rate = total_rejected / total_load    (0 when total_load is 0)

## Determinism

The system's behavior within each tick is fully deterministic. The causal relationships between subsystems — which clusters are online when traffic is distributed, what the throttle window contains, when crashes take effect, and how retries carry forward — jointly determine the outcome. Errors in the sequencing of these interactions will produce divergent results.

## Output: JSON Time Series

Write to `/app/results.json`:

```json
{
  "time_series": [
    {
      "t": "<tick_index>",
      "current_load": "<base_load_this_tick>",
      "total_load": "<base_load_plus_retries>",
      "effective_load": "<after_throttling>",
      "throttle_probability": "<probability>",
      "global_error_rate": "<ratio>",
      "total_accepted": "<sum_across_clusters>",
      "total_rejected": "<sum_across_clusters>",
      "clusters": {
        "<name>": {
          "status": "<healthy|crashed|recovering>",
          "capacity": "<effective_capacity>",
          "incoming": "<traffic_to_cluster>",
          "accepted": "<processed>",
          "rejected": "<excess>",
          "utilization": "<incoming_over_capacity>"
        }
      }
    }
  ],
  "analysis": {
    "first_overload_time": "<see_below>",
    "first_crash_time": "<see_below>",
    "peak_error_rate": "<see_below>",
    "peak_error_time": "<see_below>",
    "total_requests_lost": "<see_below>",
    "clusters_crashed": "<see_below>",
    "max_simultaneous_crashes": "<see_below>",
    "recovery_time": "<see_below>"
  }
}
```

All values are numeric (not strings). Ticks indexed from 0.

## Output: Analysis Metrics

Computed by scanning the complete time series:

| Metric | Definition |
|--------|-----------|
| `first_overload_time` | First tick where any active cluster has `utilization > 1.0`. Null if never. |
| `first_crash_time` | First tick where any cluster enters `crashed` status via the overload detection mechanism (not via external events). |
| `peak_error_rate` | Maximum `global_error_rate` across all ticks. |
| `peak_error_time` | Tick where `peak_error_rate` first occurs. |
| `total_requests_lost` | Sum of `total_rejected` across all ticks. |
| `clusters_crashed` | Sorted list of unique cluster names that entered `crashed` status via overload at any point. |
| `max_simultaneous_crashes` | Maximum number of clusters simultaneously in `crashed` status at any tick. |
| `recovery_time` | First tick strictly after `first_crash_time` where **all** clusters are `healthy`. Null if full recovery never occurs. |

## Output: SQLite Tables

Append to the incident database:

**Table `simulation_results`**: One row per tick.
- `time_step` INTEGER PRIMARY KEY
- `base_load` REAL — the current_load for this tick
- `total_load` REAL
- `effective_load` REAL
- `throttle_probability` REAL
- `error_rate` REAL — the global_error_rate
- `total_accepted` REAL
- `total_rejected` REAL

**Table `cluster_states`**: One row per cluster per tick.
- `time_step` INTEGER
- `cluster_name` TEXT
- `status` TEXT
- `capacity` REAL
- `incoming` REAL
- `accepted` REAL
- `rejected` REAL
- `utilization` REAL
- Primary key: (`time_step`, `cluster_name`)

**Table `analysis_summary`**: Key-value pairs for analysis metrics.
- `metric` TEXT PRIMARY KEY
- `value` TEXT — numeric values as string representation; lists as comma-separated sorted strings; null values as literal string `null`

**View `capacity_headroom`**: Aggregation over `cluster_states`, excluding ticks where the cluster was crashed.
- `cluster_name` TEXT
- `min_headroom` — minimum of (capacity − incoming)
- `avg_headroom` — average of (capacity − incoming)
- `overload_ticks` — count of ticks where incoming > capacity

## Numerical Precision

Round to 4 decimal places for load, capacity, accepted, and rejected values. Round to 6 decimal places for utilization, throttle_probability, and global_error_rate. SQLite output uses full floating-point precision.
