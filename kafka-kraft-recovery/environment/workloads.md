# Platform Workload Specifications

## Topic Specifications

Determine appropriate partition counts based on the throughput requirements to ensure consumers can keep up with peak producer throughput.

### order-events
- Peak producer throughput: 200 MB/s
- Per-consumer throughput capacity: 50 MB/s
- Data retention: 30 days
- Maximum single message payload: 1 MB

### sensor-telemetry
- Peak producer throughput: 400 MB/s
- Per-consumer throughput capacity: 50 MB/s
- Data retention: 6 hours
- Cleanup policy: delete

### compliance-audit
- Volume: < 5 MB/s (partition count not throughput-driven)
- Must maintain exactly one authoritative record per entity key (log compaction required)
- Records older than 365 days must be permanently purged for regulatory compliance (time-based deletion required)
- Global total ordering required across all messages (single partition)
- Minimum cleanable dirty ratio: 0.1

### payment-ledger
- Peak producer throughput: 300 MB/s
- Per-consumer throughput capacity: 50 MB/s
- Data retention: 90 days
- Segment rotation size: 256 MB

## Client Configuration Profiles

### /app/configs/exactly-once-producer.properties
Producer guaranteeing exactly-once delivery with strict per-key ordering:
- Full ISR acknowledgment
- Idempotent production enabled
- Max in-flight requests constrained for ordering guarantee with idempotence (at most 5)

### /app/configs/throughput-producer.properties
Producer optimized for maximum throughput:
- Snappy compression
- Batch size at least 128 KB
- Linger time at least 50 ms

### /app/configs/transactional-consumer.properties
Consumer for exactly-once consumption:
- Auto-commit disabled
- Offset reset from earliest
- Read-committed transaction isolation

## Partition Reassignment Design

The cluster is expanding from 3 brokers (IDs 0, 1, 2) to 5 brokers (IDs 0, 1, 2, 3, 4). A topic named `migration-test` has 10 partitions with replication factor 3. The current partition-to-replica assignments are:

| Partition | Replicas (leader first) |
|-----------|------------------------|
| 0         | [0, 1, 2]              |
| 1         | [1, 2, 0]              |
| 2         | [2, 0, 1]              |
| 3         | [0, 1, 2]              |
| 4         | [1, 2, 0]              |
| 5         | [2, 0, 1]              |
| 6         | [0, 1, 2]              |
| 7         | [1, 2, 0]              |
| 8         | [2, 0, 1]              |
| 9         | [0, 1, 2]              |

Design a partition reassignment plan and write it to `/app/evaluation/reassignment.json` in Kafka's reassignment JSON format:

```json
{"version":1,"partitions":[{"topic":"migration-test","partition":0,"replicas":[...]}, ...]}
```

Your plan must satisfy ALL of these constraints simultaneously:
1. **Balance**: Each of the 5 brokers must hold exactly 6 replicas
2. **Rack awareness**: Brokers 0, 1, 2 are in rack-A; brokers 3, 4 are in rack-B. Every partition must have at least one replica in each rack.
3. **Leader distribution**: The first replica listed for each partition is the preferred leader. Preferred leaders must be evenly distributed (exactly 2 per broker).
4. **Minimum movement**: The total number of replica changes (replicas assigned to a different broker than in the current assignment) must not exceed 12.

## Configuration Governance Audit

Review the five configuration change proposals in `/app/config_proposals.md`. For each proposal, evaluate whether it should be accepted or rejected based on the platform's workload requirements, Kafka best practices, and potential impact on data safety and performance.

Write your verdicts to `/app/evaluation/config_audit.json`:
```json
{"proposals":[{"id":"A","verdict":"ACCEPT or REJECT","reason":"one-line justification"}, ...]}
```

## Cluster Verification

Produce at least 10 messages to the order-events topic and consume them back. Save produced messages to `/app/verification/produced.txt` and consumed messages to `/app/verification/consumed.txt` (one per line).
