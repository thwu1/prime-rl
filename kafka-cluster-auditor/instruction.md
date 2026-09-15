A production Kafka cluster's diagnostic state has been captured in `/app/`:

- `/app/cluster_state.json` — Broker configs, topic settings with partition assignments/ISR state, consumer groups with lag metrics, producer configs, schema registry metadata.
- `/app/broker_jmx.json` — JMX metrics: replica manager, controller, throughput, request latency percentiles, handler utilization.
- `/app/connect_status.json` — Kafka Connect cluster: workers, connector configs, per-task status with error traces.
- `/app/acl_dump.txt` — Raw `kafka-acls.sh --list` output with all ACL entries.

Write `/app/audit.py` that cross-references all four sources to produce:

**`/app/audit_report.json`** — A structured report containing `cluster_id`, `total_issues` (must equal `len(issues)`), `critical_count`, `warning_count`, `health_score` (formula: `max(0, 100 - 15*critical - 5*warning)`), and an `issues` array. Each issue needs: `id`, `severity` (CRITICAL or WARNING), `category`, `entity_type` (broker/topic/topic_partition/consumer_group/producer/connector/acl/schema), `entity`, `description`, and `recommendation`.

**`/app/reassignment.json`** — A valid `kafka-reassign-partitions.sh` plan (version 1 format) fixing partition placement issues. Each entry must preserve replication factor while achieving rack-level fault isolation using broker rack metadata.

**`/app/remediation.sh`** — Executable script with Kafka CLI commands addressing detected issues, using `$BOOTSTRAP_SERVER` for the cluster endpoint.

Run: `python3 /app/audit.py`