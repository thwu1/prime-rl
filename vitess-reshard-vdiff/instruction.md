The application at `/app/` implements a Vitess-compatible shard routing and data migration system backed by SQLite databases under `/app/data/`. Rows are assigned to shards based on the `workspace_id` column through a hash vindex that maps values to 8-byte keyspace IDs.

Two source shards exist (`-80` and `80-`). The system must reshard into four target shards (`-40`, `40-80`, `80-c0`, `c0-`). Empty target databases with the correct schema exist at `/app/data/target_*.db`.

## Problems

**`/app/vindex.py`**: The `compute_keyspace_id` function produces keyspace IDs inconsistent with the source data. The source databases were populated using the standard Vitess hash vindex, but the current implementation uses a different algorithm. Shard routing is incorrect and the keyspace ID distribution is heavily skewed.

**`/app/reshard.py`**: `execute_reshard()` is an unimplemented stub.

**`/app/vdiff.py`**: `run_vdiff()` is an unimplemented stub.

**`/app/jobs.py`**: `forget_user()` generates disproportionate database load when processing users with subscriptions across many channels and sends notifications to users who have already been deactivated.

## Expected outcome

The vindex matches the canonical Vitess hash vindex behavior. Resharding distributes every row to its correct target shard with no data loss. VDiff confirms full data consistency between source and target shards. The batch user removal job deactivates subscriptions efficiently without excess queries or spurious notifications.

Configuration: `/app/config.py`. Schema: `/app/schema.py`.