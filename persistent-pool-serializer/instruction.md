`/app/persistent_vector.py` implements an immutable vector backed by a radix balanced tree (branching factor 2). Mutations return new versions that share unchanged subtrees with their predecessors. Study it thoroughly — the tree internals drive every design decision in this task.

Two serialization layers and two shell utilities must be completed. All must correctly preserve structural sharing: when multiple vector versions share subtrees, that relationship must survive serialization and be faithfully restored on deserialization.

## `/app/snapstore.py`

Complete the `SnapStore` class to persist named vector snapshots in SQLite. The schema at `/app/schema.sql` provides only the `snapshots` table — extend it as needed. After `load_batch`, subtrees shared between the original vectors must be the same Python object (verifiable via `is`). The `diff` method must report a `nodes_compared` count that demonstrates shared subtrees were not traversed.

## `/app/pool_serializer.py`

Complete all four functions. The module docstring specifies the pool data format that `serialize_to_pools` must produce and `deserialize_from_pools` must consume. Sharing identity must survive a serialize/deserialize round-trip. `transform_pool` must apply a function to all leaf and tail values without mutating the original pool. `compute_shared_diff` must report `nodes_visited` showing shared subtrees were skipped.

## `/app/compact.sh`

Garbage-collect nodes no longer reachable from any snapshot. Must use the `sqlite3` CLI.

## `/app/export.sh`

Export a named snapshot as JSON to stdout. Must use `sqlite3` and `jq`. Output format: `{"name", "size", "shift", "total_db_nodes", "elements"}`.