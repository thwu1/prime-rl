A 3-node Raft cluster at `/app/cluster/` (subdirectories `node_0/`, `node_1/`, `node_2/`) experienced multiple leader elections, a network partition, and node crashes across several terms. Each node directory contains WAL segment files (`.wal`) and optionally snapshot files (`.snap`) representing that node's persistent log state at the time of failure.

The Go source at `/app/gowal/` is the sole specification for the binary wire format used in all segment and snapshot files. A pre-built binary at `/app/gowal/gowal` supports `generate` and `verify` subcommands for single-node WAL data.

The cluster operated through at least three Raft terms. One node carries log entries from a superseded term that never achieved majority replication. Multiple segments across different nodes have CRC integrity failures. One node's snapshot is corrupted and cannot be trusted.

Produce:

- `/app/wal_reconciler.py` -- Python module exporting `reconcile(cluster_dir)` that returns `(committed_state, report)`:
  - `committed_state`: `dict[str, str]` -- key-value state from replaying only committed entries in index order
  - `report`: `dict` with keys `commit_index` (int -- highest committed index), `committed_entry_count` (int -- total committed entries including those covered by snapshots), `stale_entries` (dict mapping node name to sorted list of entry indices from superseded non-committed terms), `corrupted_entries` (dict mapping node name to sorted list of entry indices that failed CRC verification), `cross_referenced_recoveries` (sorted list of entry indices whose payloads were recovered via a clean copy from another node)
- `/app/committed_state.json` -- committed state from `reconcile('/app/cluster/')`
- `/app/reconciliation.json` -- report from the same run

Commitment rule: an entry at a given index is committed iff its (index, term) pair is present (including CRC-failed copies) on a strict majority of nodes. When multiple terms exist at the same index, the highest term with majority presence is authoritative. Entries from lower terms at the same index are stale. WAL commands are UTF-8 strings: `SET key value` or `DEL key`. Corrupted entries (CRC mismatch) count toward majority presence but their payloads must be sourced from a clean copy on another node.