A production Kafka cluster (`kafka-prod-east-1`) has been expanded from 4 brokers (2 racks) to 6 brokers (3 racks). The two new brokers (IDs 4 and 5) in `rack-c` are currently empty. Partition assignments are heavily skewed toward the original 4 brokers, and multiple partitions have rack-awareness violations.

The cluster metadata is spread across multiple data sources in `/app/metadata/`, reflecting the output of various Kafka admin tools and ops configurations:

- `broker_configs/server-{0..5}.properties` — Kafka broker configuration files (broker.id, broker.rack, etc.)
- `topic_descriptions.txt` — Output of `kafka-topics.sh --describe` showing partition assignments, leaders, and ISR sets
- `log_dirs.json` — Output of `kafka-log-dirs.sh --describe` with partition sizes in bytes (nested JSON per broker/logDir/partition)
- `disk_quotas.csv` — Broker disk capacity allocations (CSV with capacity in bytes)
- `constraints.yaml` — Operational constraints for rebalancing (YAML format with nested structure)

A custom cluster management tool `kafkactl` is available at `/app/tools/kafkactl` (also on PATH). Use `kafkactl --help`, `kafkactl inspect`, `kafkactl validate`, and `kafkactl diff` to understand the cluster state and validate your plan. The `kafkactl validate` command writes a validation report that must be included in your outputs.

Reconstruct the full cluster state from these heterogeneous sources, compute an optimal partition reassignment plan, and produce three output files:

**`/app/reassignment_plan.json`** — A phased reassignment plan:
```json
{
  "version": 1,
  "batches": [
    {
      "batch_id": 1,
      "partitions": [
        {"topic": "...", "partition": 0, "replicas": [0, 4, 2], "log_dirs": ["any", "any", "any"]}
      ]
    }
  ]
}
```

**`/app/audit_report.json`** — Before/after balance metrics:
```json
{
  "before": {
    "replica_count_per_broker": {"0": ..., "1": ..., ...},
    "leader_count_per_broker": {"0": ..., "1": ..., ...},
    "disk_usage_gb_per_broker": {"0": ..., "1": ..., ...},
    "rack_awareness_violations": ...
  },
  "after": { ... same structure ... },
  "total_replica_moves": ...,
  "total_data_moved_gb": ...,
  "num_batches": ...,
  "partitions_reassigned": ...
}
```

**`/app/validation_report.json`** — Output of running `kafkactl validate /app/reassignment_plan.json`. Must show `"valid": true`.

The reassignment must satisfy all constraints from `constraints.yaml`:
- **Rack awareness**: Each partition's replicas must span the maximum possible number of distinct racks (RF=3 -> 3 racks, RF=2 -> 2 racks).
- **Replica balance**: Max minus min replica count across all 6 brokers must be within `max_replica_imbalance`.
- **Leader balance**: Max minus min leader count across all 6 brokers must be within `max_leader_imbalance`.
- **Disk capacity**: No broker's total partition data may exceed its capacity from `disk_quotas.csv` (convert bytes to GB).
- **No co-location**: No two replicas of the same partition on the same broker.
- **Batch size**: Each batch may contain at most `max_concurrent_partition_moves` reassignments.
- **Minimize movement**: Minimize total data moved (in GB) while satisfying all other constraints.
- The first entry in each partition's `replicas` array is the preferred leader.
- The `log_dirs` array must match the length of `replicas`, with each entry set to `"any"`.
- Only include partitions whose replica assignments actually changed.
- The `audit_report.json` must accurately reflect the before and after states.