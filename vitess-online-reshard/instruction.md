A messaging platform runs a Vitess-style sharded MySQL backend. Data is distributed across two shards by hashing `channel_id` through a hash vindex to produce an 8-byte `keyspace_id`, which determines shard placement via hex key range partitioning (left-justified binary comparison).

Shard `shard1` (keyspace range `80-`) is experiencing cascading OOM failures under sustained write load. The operations team requires this shard to be subdivided so that each resulting sub-shard covers an equal portion of the parent's keyspace range. After remediation, the following conditions must hold:

- The full keyspace is partitioned across exactly 3 contiguous, non-overlapping shard ranges — `shard0` is untouched, and `shard1` is replaced by two new shard databases named `shard1a` and `shard1b`
- Every row resides in the shard whose key range contains its `keyspace_id`, with zero data loss or duplication across the `messages` and `subscriptions` tables
- The original `shard1` tables are emptied
- `/app/config.yaml` reflects the final 3-shard topology using the existing config schema so that `/app/router.py` routes all queries correctly
- `/app/circuit_breaker.py` provides a `CircuitBreaker` class (constructor: `failure_threshold: int`, `recovery_timeout: float` seconds; interface: `state` property returning `"closed"` / `"open"` / `"half_open"`, `allow_request() -> bool`, `record_failure()`, `record_success()`) implementing standard circuit breaker state machine semantics
- `/app/vdiff_report.json` contains a JSON object keyed by table name (`messages`, `subscriptions`), each entry having `consistent` (bool), `source_row_count` (int, original count from `shard1`), and `target_row_count` (int, sum across new shards)

## Environment

- MySQL is installed but stopped; `/usr/local/bin/ensure-mysql.sh` starts it
- `/app/config.yaml` — current 2-shard topology and MySQL credentials
- `/app/vhash.py` — hash vindex: `compute_keyspace_id(int) -> bytes`, `keyspace_id_in_range(bytes, str, str) -> bool`
- `/app/router.py` — query router using config + vhash
- `/app/original_counts.json` — per-shard row counts from initial load
- Databases `shard0` (range `-80`) and `shard1` (range `80-`) each contain `messages` and `subscriptions` tables with a `keyspace_id BINARY(8)` column