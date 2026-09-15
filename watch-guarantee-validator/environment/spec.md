# etcd Linearizability Analysis — Data Format & Model Specification

## Operation History Format

Each JSON file under `/app/data/` contains a recorded history of concurrent client
operations against an etcd key-value cluster:

```json
{
  "keys": ["k1", "k2"],
  "operations": [
    {
      "client_id": 0,
      "call_ns": 100,
      "return_ns": 200,
      "request": { ... },
      "response": { ... }
    }
  ]
}
```

- `keys` — all keys referenced in the history
- `call_ns` / `return_ns` — operation start/end timestamps (nanoseconds). Always `call_ns < return_ns`.
- `client_id` — identifies the issuing client. Operations from the same client never overlap in time.

### Request Types

**Put**: `{"type": "put", "key": "k1", "value": "v1"}`

**Get**: `{"type": "get", "key": "k1"}`

**Delete**: `{"type": "delete", "key": "k1"}`

**Transaction**:
```json
{
  "type": "txn",
  "conditions": [{"key": "k1", "expected_mod_revision": 2}],
  "on_success": [{"type": "put", "key": "k1", "value": "v2"}],
  "on_failure": []
}
```
Conditions check a key's modification revision. Sub-operations use the same
request format as top-level operations (excluding nested transactions).

### Response Types

**Put**: `{"type": "put", "revision": 4}`

**Get (key exists)**: `{"type": "get", "revision": 3, "value": "alpha", "count": 1}`

**Get (key missing)**: `{"type": "get", "revision": 3, "value": null, "count": 0}`

**Delete**: `{"type": "delete", "revision": 4, "deleted": 1}` — `deleted` is 0 if key did not exist.

**Transaction**:
```json
{"type": "txn", "revision": 4, "succeeded": true, "results": [{"type": "put"}]}
```
`results` mirrors the executed branch's sub-operations. Delete results include `deleted`.

**Error**: `{"error": "context deadline exceeded"}` — the operation's outcome is unknown.

## etcd State Machine Semantics

State starts at `revision = 1` with an empty key-value store. Each key tracks its
value and `mod_revision` (the revision at which it was last written).

**Put(key, value)**: Increments revision. Sets key to value with `mod_revision = new_revision`.
Response revision = new revision.

**Get(key)**: Pure read — no state change. Returns the key's current value and count=1
(or value=null, count=0 if the key does not exist). Response revision = current revision.

**Delete(key)**: If key exists: removes it, increments revision, `deleted = 1`.
If key does not exist: no state change, `deleted = 0`.
Response revision = current revision (which is the new revision if deletion occurred).

**Txn(conditions, on_success, on_failure)**: Evaluates all conditions against current state.
If all pass, executes `on_success`; otherwise `on_failure`. A transaction increments
revision **at most once** — all write sub-operations within a single transaction share
the same new revision. A transaction with no write sub-operations (or only failed deletes
of non-existent keys) does not increment revision. Response revision = state revision after
the transaction.

## Linearizability

A history of operations is **linearizable** if there exists a total ordering of all
operations such that:

1. **Real-time precedence**: If operation A completes before operation B begins
   (`A.return_ns <= B.call_ns`), then A must precede B in the ordering.

2. **Sequential consistency**: Executing the operations in this order against the
   state machine (starting from revision 1, empty store) produces exactly the
   observed responses.

Two operations are **concurrent** if their time intervals overlap (neither completes
before the other begins). Concurrent operations may be placed in either order.

## Non-Deterministic Model (Error Responses)

An error response means the client did not observe the outcome. The operation may
have been **persisted** (applied to state, incrementing revision) or **lost** (state
unchanged). Both possibilities must be explored.

The history is linearizable if **any** combination of persisted/lost decisions for
error-response operations yields a valid linearization as defined above.

This models real distributed system behavior: network timeouts, leader changes, and
crash recovery can cause the client to lose track of whether a write was committed.

## Output Schemas

### `/app/results.json`
```json
{
  "h1_sequential": {"linearizable": true, "violating_op_index": -1},
  "h4_stale_read": {"linearizable": false, "violating_op_index": 2}
}
```
Keys are filenames without `.json` extension. `violating_op_index` is -1 if linearizable;
otherwise the 0-based index of the earliest operation in the original sequence that cannot
be satisfied under any valid ordering and error-branch combination.

### `/app/groundtruth.json`
```json
{
  "h1_sequential": {"k1": "gamma", "k2": "beta"},
  "h3_error_valid": {"k1": "c"}
}
```
For each **linearizable** history only: the final key-value state after executing the
valid linearization. Include only keys that have a value (omit deleted keys).
Non-linearizable histories are omitted entirely.

### `/app/etcd-snapshot.db`
An etcd database snapshot created with `etcdctl snapshot save` from a live etcd instance
where you have verified ground-truth states. Must exist and be non-empty.
