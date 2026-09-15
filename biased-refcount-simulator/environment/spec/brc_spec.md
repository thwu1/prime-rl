# Biased Reference Counting (BRC) Protocol Reference

This document describes the biased reference counting state machine used by
free-threaded CPython (PEP 703).

## Data Layout

Each object stores three fields relevant to BRC:

| Field           | Type     | Description                                    |
|-----------------|----------|------------------------------------------------|
| `ob_tid`        | int64    | Owning thread ID. 0 = unowned.                 |
| `ob_ref_local`  | uint32   | Local reference count (owner thread only).      |
| `ob_ref_shared` | int64    | Shared reference count (upper bits) + BRC state (lower 2 bits). |

## Constants

| Name                  | Value        | Meaning                          |
|-----------------------|--------------|----------------------------------|
| `_Py_SHARED_SHIFT`    | 2            | Bits reserved for state encoding |
| `_Py_IMMORTAL_REFCNT` | 0xFFFFFFFF   | UINT32_MAX; marks immortal objects |

## BRC States

The **two least-significant bits** of `ob_ref_shared` encode the BRC state.
The remaining upper bits store the shared reference count, shifted left by
`_Py_SHARED_SHIFT`. The shared count is extracted via **arithmetic** right
shift (preserving sign) and can be negative.

| Bits  | State    | Meaning                                               |
|-------|----------|-------------------------------------------------------|
| 0b00  | default  | Initial state. Eligible for quick deallocation.       |
| 0b01  | weakrefs | Has weak references or non-owner optimistic access.   |
| 0b10  | queued   | Non-owner has requested refcount merge.               |
| 0b11  | merged   | Fully merged. `ob_tid`=0, `ob_ref_local` unused.     |

States progress **monotonically** (only to numerically higher values).
Objects can only be deallocated from `default` or `merged` states.

### Total reference count

- Non-merged object: `ob_ref_local + shared_count`
- Merged object (`ob_tid == 0`): `shared_count` alone
- Immortal object: undefined (lives forever)

## Thread ID Semantics

Scenario thread IDs are positive integers (1, 2, 3, …). The value 0
exclusively means "unowned" (used in the merged state). The simulator
must never treat 0 as a real thread.

## Operation Semantics

### create

Thread `tid` creates object `obj_id`. The object is owned by `tid`, starts
with `ob_ref_local = 1`, and `ob_ref_shared = 0` (default state, zero
shared count).

### incref

Immortal objects are immune to all reference count changes. Immortality is
detected via uint32 overflow: adding 1 to `ob_ref_local` at `UINT32_MAX`
wraps to 0. This overflow check takes priority over ownership checks — an
immortal object is unaffected regardless of which thread calls incref.

For non-immortal objects:
- **Owning thread** (`tid == ob_tid`): `ob_ref_local` increases by 1.
- **Non-owning thread**: the shared count increases by 1. The low state
  bits in `ob_ref_shared` must be preserved.

### decref

Immortal objects (`ob_ref_local == _Py_IMMORTAL_REFCNT`) are unaffected.

**Owner path** (`tid == ob_tid`): `ob_ref_local` decreases by 1. If it
reaches zero, zero-refcount handling triggers (see below).

**Non-owner / post-merge path** (`tid != ob_tid`): the shared-decref
logic triggers (see below). Note that after a merge, `ob_tid` becomes 0,
so **all** threads — including the former owner — follow this path.

### Zero-refcount handling

Triggered when the owning thread's `ob_ref_local` reaches zero.

- If `ob_ref_shared == 0` (no shared activity, default state): the object
  is deallocated immediately. `ob_tid` is set to 0. `dealloc_type` =
  `"quick"`. No state transition is counted.

- Otherwise: the local and shared counts are combined into a unified total.
  This total replaces the shared count in `ob_ref_shared` with the state
  set to `merged`. `ob_tid` is set to 0 and `ob_ref_local` cleared to 0.
  One state transition is counted (from whatever the current state was to
  merged). If the combined total equals zero, the object is deallocated
  with `dealloc_type` = `"merged"`.

### Shared-decref logic

Triggered by a non-owner decref (or any decref after merge).

The shared count decreases by 1 (state bits are preserved). Then:

- If the state is `merged` and the shared count is now 0: the object is
  deallocated with `dealloc_type` = `"merged"`.

- If the shared count is now **negative** and the current state is
  numerically below `queued`: the state bits transition to `queued`. One
  state transition is counted. The object is enqueued for its owning
  thread to merge later.

### immortalize

Sets `ob_ref_local` to `_Py_IMMORTAL_REFCNT`. Does not modify
`ob_ref_shared` or the BRC state. After this, incref and decref are
no-ops and the object can never be deallocated.

### create_weakref

If the object is in `default` state: transition the state bits to
`weakrefs`. Count one state transition. Otherwise no effect.

### process_queue

The owning thread `tid` processes all objects in its merge queue. For
each queued object, the same merge logic as zero-refcount handling
applies: combine local and shared counts, store the total in
`ob_ref_shared` with `merged` state, set `ob_tid` to 0 and
`ob_ref_local` to 0. Count one state transition. Deallocate if the
merged total is zero.

## Simulator Interface

### `/app/libbrc.so`

Native shared library exporting these symbols: `brc_init`, `brc_incref`,
`brc_decref`, `brc_immortalize`, `brc_create_weakref`, `brc_process_queued`.

### `/app/brc_engine.py`

Python module that wraps the native library using `ctypes`.

Module-level exports:

- `SHARED_SHIFT` — must equal `2`
- `_Py_IMMORTAL_REFCNT` — must equal `0xFFFFFFFF`
- `BRCSimulator` class
- `BRCObject` class

**`BRCSimulator`** must provide an `objects` dict mapping object IDs to
`BRCObject` instances, and these methods whose behavior must match the
corresponding operations above:

- `create(tid, obj_id)`, `incref(tid, obj_id)`, `decref(tid, obj_id)`
- `immortalize(obj_id)`, `create_weakref(obj_id)`, `process_queue(tid)`

**`BRCObject`** must expose these attributes:

- `ob_ref_local` (uint32), `ob_ref_shared` (signed int64 with arithmetic
  right-shift semantics), `ob_tid` (int)
- `deallocated` (bool), `is_immortal` (bool)
- `dealloc_type` (`"quick"`, `"merged"`, or `None`)
- `state_transitions` (int — count of BRC state transitions)

Independent `BRCSimulator` instances must be safe to use from separate
threads concurrently (no shared mutable state between instances).

### `/app/run_analysis.py`

Processes every scenario in `/app/scenarios/` and writes `/app/results.json`.
The result must contain exactly the scenarios found in `/app/scenarios/`
(keyed by filename without `.json`), with no extra or missing entries.

## Scenario File Format

Each JSON file in `/app/scenarios/` has:

```json
{
  "description": "...",
  "operations": [
    {"tid": 1, "op": "create", "obj": "A"},
    {"tid": 2, "op": "incref", "obj": "A"},
    ...
  ]
}
```

Operations are executed **sequentially** in listed order (deterministic,
no actual parallelism). Thread IDs affect only the ownership logic.

The `tid` field is present on all operations. For operations that target
a specific object, the `obj` field identifies it. The `process_queue`
operation has `tid` but no `obj` — it processes all queued objects for
that thread.

## Required Output Schema

```json
{
  "<scenario_name>": {
    "<object_id>": {
      "alive": true,
      "immortal": false,
      "dealloc_type": null,
      "total_refcount": 2,
      "state_transitions": 1,
      "final_state": "weakrefs"
    }
  }
}
```

| Field              | Type          | Description                                |
|--------------------|---------------|--------------------------------------------|
| `alive`            | bool          | `true` if object was NOT deallocated       |
| `immortal`         | bool          | `true` if object was immortalized          |
| `dealloc_type`     | string\|null  | `"quick"`, `"merged"`, or `null` if alive  |
| `total_refcount`   | int\|null     | Final total; `null` for immortal; `0` if dead |
| `state_transitions`| int           | Count of BRC state transitions             |
| `final_state`      | string        | BRC state name at end (or at deallocation) |
