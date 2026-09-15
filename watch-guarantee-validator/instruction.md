`/app/data/` contains 6 operation history files from concurrent etcd clients under fault conditions. Each records timestamped key-value operations (puts, gets, deletes, transactions) with their responses — some of which are errors indicating unknown persistence outcomes.

Determine which histories are linearizable under etcd's non-deterministic consistency model: error responses fork the possible state (the operation may or may not have been persisted). Concurrent operations (overlapping time intervals) may be serialized in either order; sequential operations must respect real-time ordering. For non-linearizable histories, identify the 0-based index of the first operation that cannot be satisfied under any valid ordering and error-branch combination.

Verify your analysis using the pre-installed etcd toolchain (`etcd`, `etcdctl`, `etcdutl`). Replay deterministic write operations from linearizable histories against a live etcd instance to confirm state consistency, and create a database snapshot at `/app/etcd-snapshot.db` for integrity verification.

Write results to `/app/results.json` and `/app/groundtruth.json` per the schemas defined in `/app/spec.md`.