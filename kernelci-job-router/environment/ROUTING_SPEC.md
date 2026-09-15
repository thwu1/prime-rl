# KernelCI Pipeline Job Router — Technical Specification

## 1. Scope

This specification defines the deterministic routing logic for dispatching kernel checkout events to LAVA labs in the KernelCI multi-lab testing federation. Given a set of lab configurations, device inventories, reliability metrics, and ordered checkout events, the router produces a routing report that assigns each event to a lab or marks it unroutable.

## 2. Input Data

| File | Description |
|------|-------------|
| `/app/pipeline_config.yaml` | Multi-lab pipeline configuration with scheduling policies |
| `/app/checkout_events.json` | Ordered array of kernel checkout events |
| `/app/device_catalog.json` | Maps device types to hosting lab names |
| `/app/reliability.db` | SQLite database of per-lab device reliability scores |

### 2.1 Reliability Database Schema

The SQLite database at `/app/reliability.db` contains a `lab_reliability` table with columns `lab_name TEXT`, `device_type TEXT`, and `score REAL`. A `reliability_metadata` table stores configuration including the default score used when no lab-device pair is recorded.

## 3. Lab Configuration & Validation

### 3.1 Participating Runtimes

Only runtimes with `lab_type: lava` participate in event routing. Other runtime types (docker, kubernetes, shell) are excluded from all routing considerations.

### 3.2 Configuration Validation

Each LAVA lab must pass configuration validation before it can receive any events. A lab failing any check is **entirely excluded** from the routing run — it cannot receive events, does not appear in eligible-lab lists, and is not counted in capacity tracking. Validation checks are evaluated in the order below; only the **first** failure per lab is reported as a validation error:

| Priority | Condition | Error Type |
|----------|-----------|------------|
| 1 | `priority_min >= priority_max` | `invalid_priority_range` |
| 2 | URL scheme is `http://` (not HTTPS) | `insecure_url` |
| 3 | `notify.callback.token` is empty string or absent | `missing_callback_token` |

### 3.3 Capacity Model

Each LAVA lab declares a `capacity` field specifying its maximum concurrent job slots. The router processes events sequentially — each routing assignment consumes one slot, reducing the lab's remaining capacity. A lab whose remaining capacity has reached zero is ineligible for further events. Because capacity is consumed sequentially, the order of event processing directly affects routing outcomes: earlier assignments constrain the options available for later events.

## 4. Routing Policy

### 4.1 Event Processing

Events are processed in the order they appear in the input array. Each routing decision is final within the run. For each event, the router determines the set of eligible labs, selects the optimal one (or marks the event unroutable), and updates capacity state before proceeding to the next event.

### 4.2 Lab Eligibility

A lab is eligible for a given event if and only if all of the following hold:

- The lab is a validated LAVA runtime (passed all checks in §3.2)
- The lab hosts the event's `device_type` according to the device catalog
- The event's `tree` satisfies the lab's tree filter (§4.3)
- The lab has remaining capacity > 0

### 4.3 Tree Filtering

Labs declare tree acceptance rules via `rules.tree` — a list of fnmatch-compatible glob patterns. Patterns prefixed with `!` are exclusion rules (the `!` prefix is stripped before matching).

**Evaluation semantics**: Exclusion rules are evaluated first. If the event's tree matches any exclusion pattern, the lab is immediately ineligible for that event regardless of inclusion rules. If no exclusion rule fires, the tree must match at least one inclusion pattern for the lab to be eligible.

Example: given rules `["stable*", "!stable-rc-*"]`:
- `stable-5.15` → included (matches `stable*`, no exclusion fires)
- `stable-rc-6.12` → excluded (matches exclusion `stable-rc-*`)
- `next` → not eligible (no inclusion match)

### 4.4 Scoring & Selection

When multiple labs are eligible for an event, the lab with the highest composite score is selected:

```
score = 0.4 · R + 0.3 · F + 0.2 · H + 0.1 · (1 − C)
```

| Factor | Definition |
|--------|------------|
| **R** (reliability) | The lab's reliability score for the event's device type, from `/app/reliability.db`. If no score is recorded for the lab-device pair, use the default value `0.50`. |
| **F** (priority fit) | `1.0` if `priority_min ≤ requested_priority ≤ priority_max`, otherwise `0.0` |
| **H** (capacity headroom) | `remaining_capacity / max_capacity`, where `remaining_capacity` is measured **before** this event's assignment and `max_capacity` is the lab's configured `capacity` |
| **C** (cost) | The lab's `cost_factor` from the pipeline config |

**Tiebreaker**: When two or more labs have equal composite scores, the lexicographically smallest lab name is selected.

### 4.5 Priority Clamping

The assigned priority is the requested priority clamped to the selected lab's `[priority_min, priority_max]` range:

```
assigned = max(priority_min, min(requested_priority, priority_max))
```

The `priority_clamped` flag is `true` when the assigned priority differs from the requested priority.

## 5. LAVA Job Artifacts

For each successfully routed event, the router generates a LAVA job definition:

| Field | Value |
|-------|-------|
| `device_type` | From the event |
| `job_name` | `kernelci-{tree}-{branch}-{device_type}-{commit}` |
| `priority` | The assigned (potentially clamped) priority |
| `timeouts.job` | `{"minutes": 30}` |
| `timeouts.action` | `{"minutes": 10}` |
| `timeouts.connection` | `{"minutes": 5}` |
| `boot_method` | Inferred from device type (§5.1) |
| `notify.callback_url` | `https://callback.kernelci.org/lava/{lab_name}` |
| `notify.token` | The selected lab's `notify.callback.token` |

### 5.1 Boot Method Inference

The boot method is determined by the device type name:

| Condition | Boot Method |
|-----------|-------------|
| Name starts with `qemu` | `"qemu"` |
| Name starts with `x86` | `"grub"` |
| Name equals `db410c` | `"fastboot"` |
| All others | `"u-boot"` |

Conditions are evaluated in the order shown; the first match applies.

## 6. Counterfactual Capacity Analysis

After processing all events, the router compares the actual (capacity-constrained) routing with an unconstrained counterfactual to quantify the impact of finite capacity on routing outcomes.

**Unconstrained routing**: For each event independently, determine eligible labs using the same device catalog, tree filter, and validation checks but **without** capacity filtering (all validated labs with the right device and tree match are eligible). Compute scores with H = 1.0 for all labs (full headroom). Select the winner using the same scoring formula and tiebreaker.

Events that are unroutable even with unlimited capacity (i.e., no lab passes device/tree/validation checks) are excluded from this analysis.

**Rerouted events**: Events that were routed in the actual run but to a **different** lab than the unconstrained routing would choose. Record the actual lab and the unconstrained lab.

**Blocked events**: Events that could not be routed in the actual run due to capacity exhaustion but **would** have been routable with unlimited capacity. Record the unconstrained winner and the sorted list of labs that were eligible by device/tree/validation but had zero remaining capacity at the time of actual routing.

## 7. Output

Write JSON to `/app/output/routing_report.json`:

```json
{
  "routing_decisions": [
    {
      "event_id": "evt_NNN",
      "eligible_labs": ["lab-a", "lab-b"],
      "selected_lab": "lab-a",
      "assigned_priority": 50,
      "priority_clamped": false,
      "lava_job": {
        "device_type": "...",
        "job_name": "...",
        "priority": 50,
        "timeouts": {
          "job": {"minutes": 30},
          "action": {"minutes": 10},
          "connection": {"minutes": 5}
        },
        "boot_method": "...",
        "notify": {
          "callback_url": "https://callback.kernelci.org/lava/lab-a",
          "token": "..."
        }
      }
    }
  ],
  "validation_errors": [
    {
      "lab": "lab-name",
      "error_type": "...",
      "detail": "..."
    }
  ],
  "summary": {
    "total_events": 15,
    "routed": 11,
    "unroutable": 4,
    "unroutable_by_spec": 3,
    "unroutable_by_capacity": 1,
    "labs_used": {"lab-a": 5, "lab-b": 3},
    "validation_error_count": 3
  },
  "capacity_impact": {
    "rerouted_events": [
      {
        "event_id": "evt_NNN",
        "actual_lab": "lab-a",
        "unconstrained_lab": "lab-b"
      }
    ],
    "blocked_events": [
      {
        "event_id": "evt_NNN",
        "unconstrained_lab": "lab-b",
        "exhausted_labs": ["lab-a", "lab-b"]
      }
    ],
    "total_rerouted": 1,
    "total_blocked": 1
  }
}
```

### 7.1 Ordering & Null Constraints

- `routing_decisions` preserves input event order
- `eligible_labs` sorted alphabetically (includes only labs with remaining capacity that pass all checks)
- Unroutable events: `selected_lab` is `null`, `assigned_priority` is `null`, `priority_clamped` is `false`, `lava_job` is `null`
- `validation_errors` sorted by lab name
- `labs_used` keys sorted alphabetically
- `exhausted_labs` sorted alphabetically
- `rerouted_events` and `blocked_events` sorted by `event_id`
