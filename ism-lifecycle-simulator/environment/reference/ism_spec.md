# OpenSearch ISM (Index State Management) Reference

## ISM Explain API

The `GET /_plugins/_ism/explain/{index}` endpoint returns the current ISM execution status for managed indices.

### Per-Index Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `policy_id` | string | The ISM policy managing this index |
| `policy_seq_no` | integer | The policy version this index is running. Compare against the policy file's `_seq_no` to detect version drift. |
| `policy_primary_term` | integer | Policy primary term |
| `rolled_over` | boolean | Whether this index has completed a rollover action |
| `index_creation_date` | long | Epoch milliseconds when the index was created |
| `state.name` | string | Current ISM state name |
| `state.start_time` | long | Epoch ms when the current state was entered |
| `action.name` | string | Current ISM action being executed or attempted |
| `action.failed` | boolean | Whether the current action has failed |
| `action.consumed_retries` | integer | Number of retries consumed for the current action |
| `action.last_retry_time` | long | Epoch ms of last retry attempt |
| `retry_info.failed` | boolean | Overall retry status |
| `retry_info.consumed_retries` | integer | Total retries consumed |
| `info.message` | string | Human-readable status message |
| `info.cause` | string | (Optional) Error cause details when an action has failed |
| `enabled` | boolean | Whether ISM is enabled for this index |

### Policy Version Management

Each ISM policy has a `_seq_no` that increments on updates. Managed indices track their running policy version via `policy_seq_no`. When `policy_seq_no < _seq_no`, the index is running an outdated version and may exhibit behavioral differences from the current policy definition (e.g., different replica counts or allocation settings).

## ISM Policy Structure

```json
{
  "_id": "policy-name",
  "_seq_no": 3,
  "_primary_term": 1,
  "policy": {
    "policy_id": "policy-name",
    "default_state": "hot",
    "states": [{ "name": "...", "actions": [...], "transitions": [...] }]
  }
}
```

### Actions

Actions execute sequentially when an index enters a state. If an action fails and exhausts retries, it blocks all subsequent actions and transitions for that index.

| Action | Description |
|--------|-------------|
| `rollover` | Creates a new index with incremented suffix, transfers write alias. Conditions use OR logic. |
| `replica_count` | Sets `number_of_replicas` on the index |
| `force_merge` | Merges segments to `max_num_segments` per shard. Fails on high-shard-count indices. |
| `read_only` | Makes the index read-only |
| `allocation` | Updates shard allocation routing via `require`, `include`, or `exclude` node attributes |
| `delete` | Deletes the index |

### Transitions

Transitions evaluate only after all state actions complete successfully. The first transition whose conditions are met fires, moving the index to the target state. **If any action is in a failed state, transitions are blocked.**

### Rollover Semantics

- Creates a new index with the numeric suffix incremented (e.g., `logs-000001` → `logs-000002`)
- Transfers the write alias from the rolled index to the new index
- Sets `rolled_over: true` on the old index in ISM explain
- Conditions use **OR logic**: any single condition met triggers rollover
- Available conditions: `min_doc_count`, `min_index_age`, `min_primary_shard_size`

### Allocation Action

Configures shard routing using node attributes:

```json
{ "allocation": { "require": { "attribute_name": "attribute_value" } } }
```

The attribute name must **exactly match** a node attribute configured on cluster data nodes. If no nodes have the specified attribute, allocation fails. Verify available attributes via `GET /_cat/nodeattrs?format=json`.

## Cluster State Data Sources

| File | Equivalent API | Description |
|------|---------------|-------------|
| `ism_explain.json` | `GET /_plugins/_ism/explain/*` | ISM status for all managed indices |
| `cat_indices.json` | `GET /_cat/indices?format=json&bytes=b` | Index stats: docs, size, shards, replicas |
| `cat_aliases.json` | `GET /_cat/aliases?format=json` | Alias-to-index mappings |
| `node_attrs.json` | `GET /_cat/nodeattrs?format=json` | Node attributes for allocation awareness |

## Index Naming Conventions

Rollover indices follow `{prefix}-{6-digit-number}` (e.g., `applogs-000001`). A rollover chain is the sequence of indices sharing a prefix. The write alias (e.g., `applogs-write`) should point to the latest unrolled index in the chain.
