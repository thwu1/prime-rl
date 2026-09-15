# LAVD-Inspired Scheduler Criticality Analyzer — Specification

## Overview

This document specifies an algorithm inspired by the Latency-Criticality Aware Virtual Deadline
(LAVD) scheduler (`scx_lavd`) from the Linux kernel's `sched_ext` framework. The algorithm
analyzes task scheduling traces from a gaming workload to compute per-task latency criticality
scores, determine optimal CPU core assignments for heterogeneous processors using an autopilot
policy, and estimate scheduling metrics including frame latency and energy consumption.

## Input Data

### Event Trace (`/app/data/events.jsonl`)

A JSONL (JSON Lines) file where each line is a JSON object representing a scheduling event.
Events are sorted by timestamp. Each event has the following fields:

- **`ts`** *(int)*: Timestamp in microseconds.
- **`type`** *(string)*: One of `"wake"`, `"exec_start"`, `"exec_end"`.
- **`task`** *(int)*: Task ID.

Additional fields by event type:

- **`wake`**: Includes `"waker"` — the task ID that caused this wakeup, or `null` for
  timer-triggered / self-triggered wakes.
- **`exec_start`**: Task begins executing on a CPU core.
- **`exec_end`**: Task finishes its current execution burst.

Each task follows the pattern: `wake → exec_start → exec_end` for each execution burst.

### CPU Topology (`/app/data/topology.json`)

```json
{
  "cores": [
    {"id": <int>, "type": "<big|medium|little>", "capacity": <float>, "power_watts": <float>}
  ]
}
```

- **`capacity`**: Relative compute capacity. `1.0` is the reference speed for big cores.
  A task's wall-clock runtime on a core equals `task_cpu_time / capacity`.
- **`power_watts`**: Power draw when the core is active.

### Configuration (`/app/data/config.json`)

```json
{
  "base_time_slice_us": <int>,
  "epsilon": <float>,
  "powersave_threshold": <float>,
  "performance_threshold": <float>,
  "big_core_criticality_threshold_performance": <float>,
  "medium_core_criticality_threshold_performance": <float>,
  "big_core_criticality_threshold_balanced": <float>,
  "medium_core_criticality_threshold_balanced": <float>,
  "target_frame_time_us": <int>,
  "num_frames": <int>
}
```

### Task Names (`/app/data/task_names.json`)

A JSON object mapping task ID (as string) to human-readable task name.

---

## Algorithm

### Step 1: Build Wake Dependency Graph

Parse the event trace and construct a directed weighted graph:

- **Nodes**: Unique task IDs found in the trace.
- **Edges**: For each `wake` event where `waker` is **not** `null`, increment the edge
  weight from `waker` to `task` by 1.

Compute per-task aggregate statistics:

- **`fan_out[t]`**: Total number of wake events where task `t` is the waker
  (sum of outgoing edge weights).
- **`fan_in[t]`**: Total number of wake events where task `t` is the wakee and `waker`
  is not null (sum of incoming edge weights).
- **`avg_runtime[t]`**: Mean execution time per burst. For each `exec_start` event for
  task `t` at time `T_start`, find the next `exec_end` event for the same task at time
  `T_end`. The burst runtime is `T_end - T_start`. Average across all bursts.

Tasks that have no wake events with a non-null waker have `fan_in = 0`.
Tasks that never wake other tasks have `fan_out = 0`.

### Step 2: Compute Latency Criticality

For each task `t`, compute the **raw criticality score**:

```
raw_criticality[t] = sqrt((1 + fan_out[t]) * (1 + fan_in[t])) * log2(1 + avg_runtime[t] / base_time_slice_us)
```

The formula captures two aspects of latency criticality:
- **Structural importance**: `sqrt((1 + fan_out) * (1 + fan_in))` — tasks that both wake
  other tasks and are woken by other tasks are structurally central in the dependency graph.
- **Computational weight**: `log2(1 + avg_runtime / base_slice)` — tasks with longer
  runtimes have a larger impact on end-to-end latency when delayed.

**Normalize** to the range [0, 1]:

```
criticality[t] = raw_criticality[t] / max(raw_criticality[u] for all tasks u)
```

The most critical task receives a score of exactly `1.0`.

### Step 3: Compute System Utilization

```
utilization = total_task_runtime / (num_cores * observation_time)
```

Where:
- **`total_task_runtime`**: Sum of all individual burst durations (`exec_end.ts - exec_start.ts`)
  across every event in the trace.
- **`num_cores`**: Total number of cores in the topology.
- **`observation_time`**: `max(ts) - min(ts)` across all events in the trace.

### Step 4: Determine Autopilot Mode

Compare utilization against config thresholds:

- If `utilization < powersave_threshold` → mode = `"powersave"`
- If `utilization > performance_threshold` → mode = `"performance"`
- Otherwise → mode = `"balanced"`

### Step 5: Assign Tasks to Core Types

Each task is assigned to a core **type** (`"big"`, `"medium"`, or `"little"`) based on
the autopilot mode and the task's normalized criticality score:

**Powersave mode**: All tasks → `"little"`.

**Performance mode**:
- `criticality > big_core_criticality_threshold_performance` → `"big"`
- `criticality > medium_core_criticality_threshold_performance` → `"medium"`
- Otherwise → `"little"`

**Balanced mode**:
- `criticality > big_core_criticality_threshold_balanced` → `"big"`
- `criticality > medium_core_criticality_threshold_balanced` → `"medium"`
- Otherwise → `"little"`

### Step 6: Compute Virtual Deadlines

For **each** `wake` event in the trace (regardless of whether `waker` is null or not),
compute the virtual deadline for the woken task:

```
virtual_deadline = ts + base_time_slice_us / (criticality[task] + epsilon)
```

Where `epsilon` prevents division by near-zero for tasks with very low criticality.
Higher-criticality tasks receive **shorter** deadlines (they should be scheduled sooner).

### Step 7: Compute Frame Metrics

The trace covers `num_frames` frames, each with a period of `target_frame_time_us`
microseconds. Frame `i` (0-indexed) spans the timestamp range:

```
[i * target_frame_time_us, (i + 1) * target_frame_time_us)
```

For each frame, compute the **frame time**:

```
frame_time = max(exec_end.ts for events in frame) - min(ts for events in frame)
```

Only consider frames that contain at least one event.

Aggregate metrics:
- **`avg_frame_time_us`**: Arithmetic mean of all frame times.
- **`p99_frame_time_us`**: 99th percentile frame time. Sort frame times ascending,
  then use index `ceil(0.99 * N) - 1` where `N` is the number of frames.

### Step 8: Compute Energy Consumption

For each task `t`:

1. Look up the assigned core type from Step 5.
2. Find the first core of that type in the topology to get `capacity` and `power_watts`.
3. Compute actual wall-clock time: `actual_time_us = total_runtime[t] / capacity`
   where `total_runtime[t]` is the sum of all burst durations for task `t`.
4. Compute energy: `energy_joules += power_watts * (actual_time_us / 1_000_000)`

Sum across all tasks to get `total_energy_joules`.

---

## Output Files

All output must be written to `/app/output/` as valid JSON files.

### `/app/output/wake_graph.json`

```json
{
  "edges": [
    {"from": <waker_task_id>, "to": <wakee_task_id>, "weight": <int>},
    ...
  ],
  "num_tasks": <int>,
  "task_names": {"<task_id_str>": "<name>", ...}
}
```

Edges should be sorted by `(from, to)`.

### `/app/output/criticality.json`

```json
{
  "scores": {"<task_id_str>": <float>, ...},
  "raw_scores": {"<task_id_str>": <float>, ...},
  "ranking": [<task_id_int>, ...]
}
```

- `scores`: Normalized criticality in [0, 1].
- `raw_scores`: Unnormalized criticality values.
- `ranking`: Task IDs ordered by descending criticality.

### `/app/output/schedule.json`

```json
{
  "mode": "<powersave|balanced|performance>",
  "utilization": <float>,
  "assignments": {"<task_id_str>": "<big|medium|little>", ...},
  "deadlines": [
    {"task": <int>, "wake_time": <int>, "virtual_deadline": <float>, "criticality": <float>},
    ...
  ]
}
```

`deadlines` should contain entries for all wake events (or at minimum the first 20).

### `/app/output/metrics.json`

```json
{
  "avg_frame_time_us": <float>,
  "p99_frame_time_us": <float>,
  "total_energy_joules": <float>,
  "utilization": <float>,
  "mode": "<string>",
  "num_tasks": <int>,
  "num_events": <int>,
  "num_frames": <int>,
  "frame_times": [<float>, ...]
}
```
