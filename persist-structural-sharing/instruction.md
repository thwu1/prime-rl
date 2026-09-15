`/app/pvec.py` implements a persistent vector (radix balanced tree, B=2, M=4) with structural sharing. `/app/serialize.py` provides pool-based serialization that deduplicates shared subtrees within a single pool. `/app/POOL_FORMAT.md` describes the pool JSON format.

`/app/snapshots.db` is a SQLite database containing independently-serialized pool snapshots. Explore it with `sqlite3` CLI and examine the pool JSON with `jq` to understand the data before writing any code.

## Goal

Build a system that eliminates the cross-pool node duplication present in `/app/snapshots.db`, enables efficient structural comparison between stored vectors, and produces a compaction report.

### `/app/pool_store.py`

A `PoolStore` class backed by SQLite that normalizes multiple pools into a single deduplicated relational store. Structurally identical tree nodes must exist exactly once regardless of which pool they originated from.

Schema tables: `nodes` (autoincrement id, node_type, UNIQUE content_hash), `leaf_data` (node_id, position, JSON-encoded value), `inner_children` (parent_id, position, child_id), `vectors` (name PRIMARY KEY, source_pool, root_id, tail_id, size, shift).

Methods: `__init__(self, db_path)`, `import_pool(self, pool_json: dict, source_name: str)`, `export_all(self) -> dict` (must round-trip through `serialize.deserialize_pool`), `export_vectors(self, vector_names: list[str]) -> dict`, `verify_integrity(self) -> dict` returning `{orphaned_nodes, duplicate_content, invalid_refs, total_nodes, total_vectors}`, `stats(self) -> dict` returning `{total_nodes, leaf_nodes, inner_nodes, total_vectors, total_edges}`, `close(self)`.

### `/app/diff_engine.py`

A `StructuralDiff` class that computes element-level diffs between two vectors in a `PoolStore`. When two subtrees at corresponding positions resolve to the same database node, the diff must skip the entire subtree — achieving cost proportional to actual changes, not vector size.

Constructor: `StructuralDiff(store: PoolStore)`.

`diff(self, vec_name_a: str, vec_name_b: str) -> dict` returning `{"modified": {idx: [old, new]}, "added": {idx: val}, "removed": {idx: val}, "stats": {"nodes_visited": int, "nodes_skipped": int, "total_reachable": int}}`. Keys in `modified`/`added`/`removed` are integer element indices.

`sharing_ratio(self, vec_name_a: str, vec_name_b: str) -> float` — Jaccard similarity (intersection / union) of two vectors' reachable node sets.

### `/app/compact`

An executable script that reads all snapshots from `/app/snapshots.db`, builds a compacted store at `/app/compacted.db`, runs structural diffs between consecutively-suffixed vectors sharing a common name prefix (e.g. `counter_0` through `counter_9`), and writes `/app/report.json`. Must integrate `sqlite3` CLI for database statistics, `jq` for JSON validation, and `awk` for formatted tabular output of node distributions. Report keys: `total_raw_nodes`, `compacted_nodes`, `reduction_pct`, `vectors_imported`, `integrity`, `diff_summary` (mapping pair labels like `"vec_a->vec_b"` to diff stats including `nodes_visited` and `nodes_skipped`).