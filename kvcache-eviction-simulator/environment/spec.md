# KVCache Store Simulator Specification

## Overview

This document specifies a discrete-event simulator for a KVCache store inspired by production disaggregated LLM serving systems (such as those used for prefill/decode separation in large model inference). The store manages cached key-value objects in a fixed-capacity memory pool with LRU-based eviction, lease-based access protection, and tiered pinning mechanisms.

## Configuration

The simulator reads its configuration from a JSON file with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `total_capacity_bytes` | int | Total cache capacity in bytes |
| `lease_ttl_sec` | float | Duration of lease granted on GET |
| `soft_pin_ttl_sec` | float | Duration of soft pin before auto-expiry |
| `allow_evict_soft_pinned` | bool | Whether soft-pinned objects may be evicted in phase 2 |

## Object State

Each cached object maintains:

- **key** (string): unique identifier
- **size** (int): size in bytes, positive
- **hard_pin** (bool): permanent eviction immunity, immutable after creation
- **soft_pin_expiry** (float): timestamp after which soft pin expires; 0 means not soft-pinned
- **lease_expiry** (float): timestamp after which lease expires; 0 means not leased
- **last_access_time** (float): timestamp of most recent PUT or GET on this object

## Temporal Model

Operations are provided as a JSONL trace file. Each line is a JSON object with a `t` field (float timestamp) and an `op` field (string operation type). Operations are processed in trace order. Multiple operations may share the same timestamp; trace order is authoritative.

An object is **leased** at time `t` if `lease_expiry > t`.

An object is **actively soft-pinned** at time `t` if `soft_pin_expiry > t`.

## Operations

### PUT

```json
{"t": <float>, "op": "PUT", "key": <string>, "size": <int>, "hard_pin": <bool>}
```

The `hard_pin` field is optional and defaults to `false`.

Processing:

1. If an object with the same key already exists, **remove** it unconditionally (freeing its space, discarding its pins and lease). This removal is not subject to lease or hard-pin protection — it is an internal replacement, not a user-facing REMOVE.
2. Compute `needed = used_bytes + size - total_capacity`. If `needed <= 0`, skip to step 5.
3. Run the **Eviction Algorithm** (see below) with target = `needed`.
4. After eviction planning: if the total reclaimable bytes across both phases is `>= needed`, execute the eviction (remove all selected objects, record eviction events). Otherwise, **no objects are evicted** (atomic semantics) and the PUT fails — record a `put_failed` event and stop.
5. Store the new object: `last_access_time = t`, `hard_pin` as specified, `soft_pin_expiry = 0`, `lease_expiry = 0`. Update `used_bytes`.

### GET

```json
{"t": <float>, "op": "GET", "key": <string>}
```

- If the key exists: **cache hit**.
  - Set `last_access_time = t`.
  - Set `lease_expiry = max(current lease_expiry, t + lease_ttl_sec)`.
  - If the object is currently soft-pinned (`soft_pin_expiry > t`): set `soft_pin_expiry = t + soft_pin_ttl_sec`.
- If the key does not exist: **cache miss**. No state change.

### REMOVE

```json
{"t": <float>, "op": "REMOVE", "key": <string>}
```

- If the key exists **and** the object is not hard-pinned **and** the object is not leased (`lease_expiry <= t`): remove the object, free its space.
- If the key exists but the object is hard-pinned or leased: the REMOVE fails. Record a `remove_failed` event.
- If the key does not exist: no-op.

### SOFT_PIN

```json
{"t": <float>, "op": "SOFT_PIN", "key": <string>}
```

- If the key exists: set `soft_pin_expiry = t + soft_pin_ttl_sec`.
- If the key does not exist: no-op.

## Eviction Algorithm

Eviction is triggered during PUT when `used_bytes + size > total_capacity` (after removing any existing object with the same key).

**Target**: free at least `needed = used_bytes + size - total_capacity` bytes.

### Phase 1

Collect all objects satisfying ALL of:
- Not hard-pinned (`hard_pin == false`)
- Not leased (`lease_expiry <= t`)
- Not actively soft-pinned (`soft_pin_expiry <= t`)

Sort ascending by `(last_access_time, key)`. The `key` comparison is lexicographic and serves as a deterministic tiebreaker.

Greedily select objects from this sorted list until the cumulative selected size `>= needed`.

### Phase 2

Only runs if Phase 1 did not select enough AND `allow_evict_soft_pinned` is `true`.

Collect all objects satisfying ALL of:
- Not hard-pinned
- Not leased (`lease_expiry <= t`)
- Actively soft-pinned (`soft_pin_expiry > t`)

Sort ascending by `(last_access_time, key)`.

Continue selecting from this list until cumulative total across both phases `>= needed`.

### Atomicity

If after both phases the cumulative selected size is still `< needed`, **no objects are evicted**. The PUT fails.

If enough was selected, all selected objects are evicted (removed from the store). Eviction events are recorded in selection order (Phase 1 objects first, then Phase 2).

## Output Format

The simulator writes a single JSON object to stdout:

```json
{
  "events": [
    {"t": <float>, "type": "eviction", "key": <string>, "freed": <int>},
    {"t": <float>, "type": "put_failed", "key": <string>},
    {"t": <float>, "type": "remove_failed", "key": <string>}
  ],
  "stats": {
    "cache_hits": <int>,
    "cache_misses": <int>,
    "evictions_count": <int>,
    "bytes_evicted": <int>,
    "failed_puts": <int>
  },
  "final_state": {
    "<key>": {
      "size": <int>,
      "hard_pin": <bool>,
      "soft_pinned": <bool>,
      "leased": <bool>
    }
  },
  "final_used_bytes": <int>
}
```

**Notes:**

- `events`: ordered list of all events that occurred during simulation, in chronological/trace order.
- `final_state`: snapshot of all objects after the last operation. The `soft_pinned` and `leased` booleans are evaluated at the timestamp of the last operation in the trace.
- Within a single eviction trigger, events are listed in the order objects were selected (Phase 1 LRU first, then Phase 2 LRU).

## Command-Line Interface

```
python3 /app/simulator.py --config <path_to_config.json> --trace <path_to_trace.jsonl>
```

Exit code 0 on success, non-zero on error. JSON output to stdout.
