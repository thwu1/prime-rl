"""Tree query module.

WARNING: This module was written for the development SQLite backend.
The production analytics engine is DuckDB — see /app/config/production.yaml.
Additionally, recursive CTEs are not permitted under the production
analytics database configuration.

TODO: Rewrite to use the duckdb Python module with index-based queries
that comply with production constraints. See /app/pipeline/index.py.
"""
import sqlite3


def query_ancestors(db_path, node_id):
    """Return list of ancestors from node_id to root (inclusive, node first).

    DEPRECATED: Uses SQLite WITH RECURSIVE — violates production constraints.
    Must be reimplemented to use DuckDB and pre-built index structures.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        WITH RECURSIVE ancestry(id, depth) AS (
            SELECT id, 0 FROM tree WHERE id = ?
            UNION ALL
            SELECT t.parent_id, a.depth + 1
            FROM tree t JOIN ancestry a ON t.id = a.id
            WHERE t.parent_id IS NOT NULL
        )
        SELECT id FROM ancestry ORDER BY depth
    """, (node_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def query_lca(db_path, node_a, node_b):
    """Return lowest common ancestor of two nodes.

    DEPRECATED: Relies on query_ancestors which uses SQLite WITH RECURSIVE.
    """
    ancestors_a = set(query_ancestors(db_path, node_a))
    path_b = query_ancestors(db_path, node_b)
    for node in path_b:
        if node in ancestors_a:
            return node
    return -1
