# Split-Brain Data Reconciliation Policy

## Context

After a network partition, the Redis Sentinel cluster experienced a split-brain event.
Node A (port 6379) and Node B (port 6380) both accepted writes independently as masters.
The partition has healed but data has diverged. Both nodes have records that were modified
independently, and each created new records that the other never saw.

## Reconciliation Rules

### Rule 1: Conflict Resolution by Timestamp

When the same record key (e.g., `record:15`) exists on both nodes with different content,
compare the `updated_at` field values. The version with the **strictly later** ISO-8601
timestamp is the winner.

### Rule 2: Financial Safety Override

**Exception to Rule 1**: If one version of a conflicting record has `status` set to
`"refunded"` and the other version has any other status value, the version with
`"refunded"` status **always wins**, regardless of which node has the later timestamp.
Refund operations are irreversible financial events that must be preserved for audit
compliance and regulatory integrity. If both versions have `"refunded"` status, fall
back to Rule 1 (timestamp comparison). This rule takes precedence over Rule 1 when
applicable.

### Rule 3: Unique Record Preservation

Records that exist on only one node must be preserved in the final merged dataset.

### Rule 4: Identical Records

Records that exist on both nodes with identical JSON content are not conflicts and should
be retained as-is. Do not include them in the conflict report.

### Rule 5: Final Master Designation

After reconciliation, Node A (port 6379) shall be designated as the master.
Node B (port 6380) shall become its replica. Ensure all reconciled data is written
to Node A before configuring replication, as the replica will flush its local data
during initial sync.

### Rule 6: Sentinel Reconfiguration

All three Sentinel instances (ports 26379, 26380, 26381) must be reconfigured to
monitor the designated master (Node A, port 6379) under the service name "mymaster".

### Rule 7: Reconciliation Report

A JSON report must be written to `/app/reconciliation_report.json` with this schema:

```json
{
  "total_records": <int: total records in merged dataset>,
  "conflicts": {
    "total": <int: number of conflicting records resolved>,
    "node_a_wins": <int: conflicts where Node A version was kept>,
    "node_b_wins": <int: conflicts where Node B version was kept>,
    "details": [
      {
        "record_id": <int>,
        "winner": "node_a" | "node_b",
        "resolution_reason": "timestamp" | "financial_safety",
        "node_a_updated_at": "<ISO-8601 timestamp>",
        "node_b_updated_at": "<ISO-8601 timestamp>"
      }
    ]
  },
  "unique_records": {
    "from_node_a": <int: records existing only on Node A>,
    "from_node_b": <int: records existing only on Node B>
  }
}
```

The `details` array must be sorted by `record_id` ascending.

Set `resolution_reason` to `"financial_safety"` when Rule 2 applies to the conflict
(i.e., exactly one version has `status: "refunded"`). Set it to `"timestamp"` for all
other conflicts resolved by Rule 1.

### Rule 8: Application Restoration

The Flask application at port 5000 must be operational and serving data from the
reconciled dataset via the Sentinel-managed cluster.
