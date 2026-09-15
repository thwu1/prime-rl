# Cascading Failure Simulation Model

## Overview

This document specifies a discrete-time simulation engine that models cascading failures
in a multi-cluster service architecture. The model incorporates adaptive client-side
throttling (per Google SRE Chapter 21), retry amplification with budget caps, overload-
triggered crash-recovery cycles, and cold-cache recovery effects.

## Time Model

- Simulation runs for `duration_steps` discrete time steps, indexed t = 0, 1, ..., duration_steps - 1.
- Each step represents one second of simulated time.

## Cluster State

Each cluster c maintains:

| Field | Description |
|---|---|
| `base_capacity` | Configured maximum QPS. May be modified by capacity_change events. |
| `current_capacity` | Effective capacity this step. Equals base_capacity when healthy. |
| `weight` | Load distribution weight. Fixed; does not change with capacity. |
| `status` | One of: `healthy`, `crashed`, `recovering`. |
| `overload_counter` | Consecutive steps with utilization > crash threshold. |
| `offline_timer` | Steps spent in crashed state (counts up toward offline_steps). |
| `recovery_timer` | Steps spent in recovering state (counts up toward recovery_steps). |

Statuses: There is no separate "overloaded" status. Overload is a condition
(utilization > 1.0) that can occur in healthy or recovering clusters.

## Processing Order Per Time Step

Each time step executes these phases in strict order:

### Phase 1: Event Application

Apply all events scheduled for time t, in the order listed in the scenario file.

- **capacity_change**: Sets `base_capacity` for the named cluster to `new_capacity`.
  If the cluster's status is `healthy`, also sets `current_capacity` to `new_capacity`.
  (Crashed/recovering clusters retain their current capacity until state transition.)
- **load_change**: Sets the base incoming load (`current_load`) to `new_load_qps`.

### Phase 2: State Transitions

For each cluster, advance timers and check for state transitions:

1. If status == `crashed`:
   - Increment `offline_timer` by 1.
   - If `offline_timer >= offline_steps`:
     - Set status = `recovering`.
     - Set `current_capacity = base_capacity * recovery_capacity_fraction`.
     - Reset `offline_timer = 0` and `recovery_timer = 0`.

2. If status == `recovering`:
   - Increment `recovery_timer` by 1.
   - If `recovery_timer >= recovery_steps`:
     - Set status = `healthy`.
     - Set `current_capacity = base_capacity`.
     - Reset `recovery_timer = 0`.

### Phase 3: Load Computation

1. Identify **active clusters**: those with status != `crashed` AND `current_capacity > 0`.
2. Compute `total_active_weight = sum(weight_c)` for all active clusters c.
3. Compute actual retries from previous step's rejected requests:
   `retries = min(pending_retries, budget_fraction * current_load)`
4. Compute total load: `total_load = current_load + retries`
5. Compute throttle probability from the sliding window (see below).
6. Compute effective load: `effective_load = total_load * (1 - throttle_probability)`

### Phase 4: Load Distribution and Processing

**If total_active_weight > 0:**

For each cluster c:
- If c is not active (crashed or capacity=0): incoming=0, accepted=0, rejected=0, utilization=0.
- If c is active:
  - `incoming_c = effective_load * (weight_c / total_active_weight)`
  - `accepted_c = min(incoming_c, current_capacity_c)`
  - `rejected_c = max(0, incoming_c - current_capacity_c)`
  - `utilization_c = incoming_c / current_capacity_c`

Aggregates:
- `total_accepted = sum(accepted_c)` for all clusters
- `total_rejected = sum(rejected_c)` for all clusters

**If total_active_weight == 0** (all clusters down):
- `total_rejected = effective_load`
- `total_accepted = 0`
- All clusters: incoming=0, accepted=0, rejected=0, utilization=0.

Global error rate: `global_error_rate = total_rejected / total_load` (0 if total_load == 0).

### Phase 5: Sliding Window Update

Append this step's `effective_load` to the requests window and `total_accepted` to the
accepts window. Both windows are FIFO queues with maximum length `window_steps`.
Old values are automatically dropped when the window is full.

### Phase 6: Crash Detection

For each cluster c with status != `crashed` and `current_capacity > 0`:

1. If `utilization_c > crash_threshold`: increment `overload_counter` by 1.
2. Else: reset `overload_counter = 0`.
3. If `overload_counter >= consecutive_steps`:
   - Set status = `crashed`, `current_capacity = 0`.
   - Reset `overload_counter = 0`, `offline_timer = 0`.

**Note:** The cluster still processed requests during this step (the crash takes effect
at the end of the step). The status field in the output for this step should reflect
the post-crash-check state (i.e., show "crashed").

### Phase 7: Record Results

Record all metrics for this time step to the time series output.

### Phase 8: Update Retry Pool

Set `pending_retries = total_rejected`. These become potential retries for the next step.
The initial value of `pending_retries` (at t=0) is 0.

## Adaptive Client-Side Throttling

Based on Google's adaptive throttling formula (SRE Book, Chapter 21):

The throttle probability is computed from a sliding window of the most recent
`window_steps` data points (effective_load and total_accepted from previous steps):

    If window is empty:
        throttle_probability = 0
    Else:
        W_requests = sum of all effective_load values in the window
        W_accepts  = sum of all total_accepted values in the window
        throttle_probability = max(0, (W_requests - K * W_accepts) / (W_requests + 1))

K is the multiplier (default 2.0). With K=2, throttling engages only when the rejection
rate exceeds 50% over the window period.

## Output Format

The simulation must produce `/app/results.json` with this structure:

```json
{
  "time_series": [
    {
      "t": 0,
      "current_load": 5000.0,
      "total_load": 5000.0,
      "effective_load": 5000.0,
      "throttle_probability": 0.0,
      "global_error_rate": 0.0,
      "total_accepted": 5000.0,
      "total_rejected": 0.0,
      "clusters": {
        "alpha": {
          "status": "healthy",
          "capacity": 2000.0,
          "incoming": 1666.6667,
          "accepted": 1666.6667,
          "rejected": 0.0,
          "utilization": 0.833333
        }
      }
    }
  ],
  "analysis": {
    "first_overload_time": 10,
    "first_crash_time": 32,
    "peak_error_rate": 1.0,
    "peak_error_time": 36,
    "total_requests_lost": 123456.78,
    "clusters_crashed": ["beta", "delta", "gamma"],
    "max_simultaneous_crashes": 3,
    "recovery_time": 62
  }
}
```

(Values above are illustrative; compute from the simulation.)

### Analysis Field Definitions

- **first_overload_time**: First time step where any active cluster has utilization > 1.0.
- **first_crash_time**: First time step where any cluster transitions to "crashed" status
  due to overload (via the crash detection mechanism, not external events).
- **peak_error_rate**: Maximum `global_error_rate` across all time steps.
- **peak_error_time**: Time step at which `peak_error_rate` first occurs.
- **total_requests_lost**: Sum of `total_rejected` across all time steps.
- **clusters_crashed**: Sorted list of unique cluster names that entered "crashed" status
  at any point during the simulation (only overload-induced crashes, not events).
- **max_simultaneous_crashes**: Maximum number of clusters simultaneously in "crashed"
  status at any single time step.
- **recovery_time**: First time step strictly after `first_crash_time` where ALL clusters
  have status "healthy". Null if the system never fully recovers within the simulation.

### Numerical Precision

Round floating-point values in the output to 4 decimal places for load/capacity/rate
values and 6 decimal places for utilization and probabilities.
