"""
SQLite-backed pool store with cross-pool content-based deduplication.

Stores persistent vector pool data in a normalized relational schema.
Nodes are identified by content-derived SHA-256 hashes for deduplication:
leaf hashes are computed from their JSON-encoded data arrays, inner node
hashes from the concatenation of their children's hashes (Merkle-style).

"""

import hashlib
import json
import sqlite3
import sys

sys.path.insert(0, "/app")

from pvec import B


class PoolStore:
    """Normalized SQLite-backed pool store with content-based deduplication."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_type TEXT NOT NULL CHECK(node_type IN ('leaf', 'inner')),
                content_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS leaf_data (
                node_id INTEGER NOT NULL REFERENCES nodes(id),
                position INTEGER NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (node_id, position)
            );
            CREATE TABLE IF NOT EXISTS inner_children (
                parent_id INTEGER NOT NULL REFERENCES nodes(id),
                position INTEGER NOT NULL,
                child_id INTEGER NOT NULL REFERENCES nodes(id),
                PRIMARY KEY (parent_id, position)
            );
            CREATE TABLE IF NOT EXISTS vectors (
                name TEXT PRIMARY KEY,
                source_pool TEXT NOT NULL,
                root_id INTEGER NOT NULL REFERENCES nodes(id),
                tail_id INTEGER NOT NULL REFERENCES nodes(id),
                size INTEGER NOT NULL,
                shift INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ic_child ON inner_children(child_id);
        """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Content hashing
    # ------------------------------------------------------------------

    @staticmethod
    def _leaf_hash(data_list):
        raw = json.dumps(data_list, sort_keys=False, separators=(",", ":"))
        return "L:" + hashlib.sha256(raw.encode()).hexdigest()[:32]

    @staticmethod
    def _inner_hash(child_hashes):
        raw = "|".join(child_hashes)
        return "I:" + hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_pool(self, pool_json, source_name):
        """Import a POOL_FORMAT-compliant dict with cross-pool dedup."""
        nodes_data = pool_json["nodes"]
        pool_to_db = {}  # pool_id_str -> (db_id, content_hash)

        def _import_node(pool_id):
            ps = str(pool_id)
            if ps in pool_to_db:
                return pool_to_db[ps]

            desc = nodes_data[ps]

            if desc["type"] == "leaf":
                ch = self._leaf_hash(desc["data"])
                row = self.conn.execute(
                    "SELECT id FROM nodes WHERE content_hash=?", (ch,)
                ).fetchone()
                if row:
                    db_id = row[0]
                else:
                    cur = self.conn.execute(
                        "INSERT INTO nodes(node_type, content_hash) "
                        "VALUES('leaf', ?)",
                        (ch,),
                    )
                    db_id = cur.lastrowid
                    for i, val in enumerate(desc["data"]):
                        self.conn.execute(
                            "INSERT INTO leaf_data(node_id, position, value) "
                            "VALUES(?, ?, ?)",
                            (db_id, i, json.dumps(val)),
                        )
                pool_to_db[ps] = (db_id, ch)
                return db_id, ch

            else:  # inner
                child_info = [_import_node(cid) for cid in desc["children"]]
                child_db_ids = [ci[0] for ci in child_info]
                child_hashes = [ci[1] for ci in child_info]
                ch = self._inner_hash(child_hashes)
                row = self.conn.execute(
                    "SELECT id FROM nodes WHERE content_hash=?", (ch,)
                ).fetchone()
                if row:
                    db_id = row[0]
                else:
                    cur = self.conn.execute(
                        "INSERT INTO nodes(node_type, content_hash) "
                        "VALUES('inner', ?)",
                        (ch,),
                    )
                    db_id = cur.lastrowid
                    for i, cdb_id in enumerate(child_db_ids):
                        self.conn.execute(
                            "INSERT INTO inner_children"
                            "(parent_id, position, child_id) VALUES(?, ?, ?)",
                            (db_id, i, cdb_id),
                        )
                pool_to_db[ps] = (db_id, ch)
                return db_id, ch

        for vname, vinfo in pool_json["vectors"].items():
            root_db_id = _import_node(vinfo["root"])[0]
            tail_db_id = _import_node(vinfo["tail"])[0]
            self.conn.execute(
                "INSERT OR REPLACE INTO vectors"
                "(name, source_pool, root_id, tail_id, size, shift) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    vname,
                    source_name,
                    root_db_id,
                    tail_db_id,
                    vinfo["size"],
                    vinfo["shift"],
                ),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_all(self):
        """Export all stored vectors as a POOL_FORMAT-compliant dict."""
        rows = self.conn.execute(
            "SELECT name, root_id, tail_id, size, shift FROM vectors"
        ).fetchall()
        if not rows:
            return {"B": B, "nodes": {}, "vectors": {}}

        db_to_pool = {}
        pool_nodes = {}

        def _assign(db_id):
            if db_id in db_to_pool:
                return db_to_pool[db_id]

            ntype = self.conn.execute(
                "SELECT node_type FROM nodes WHERE id=?", (db_id,)
            ).fetchone()[0]

            if ntype == "leaf":
                pid = len(db_to_pool)
                db_to_pool[db_id] = pid
                vals = self.conn.execute(
                    "SELECT value FROM leaf_data "
                    "WHERE node_id=? ORDER BY position",
                    (db_id,),
                ).fetchall()
                pool_nodes[str(pid)] = {
                    "type": "leaf",
                    "data": [json.loads(r[0]) for r in vals],
                }
                return pid
            else:
                children = self.conn.execute(
                    "SELECT child_id FROM inner_children "
                    "WHERE parent_id=? ORDER BY position",
                    (db_id,),
                ).fetchall()
                child_pids = [_assign(r[0]) for r in children]
                pid = len(db_to_pool)
                db_to_pool[db_id] = pid
                pool_nodes[str(pid)] = {
                    "type": "inner",
                    "children": child_pids,
                }
                return pid

        vec_entries = {}
        for name, root_id, tail_id, size, shift in rows:
            rpid = _assign(root_id)
            tpid = _assign(tail_id)
            vec_entries[name] = {
                "root": rpid,
                "tail": tpid,
                "size": size,
                "shift": shift,
            }

        return {"B": B, "nodes": pool_nodes, "vectors": vec_entries}

    def export_vectors(self, vector_names):
        """Export a subset of vectors."""
        full = self.export_all()
        names = set(vector_names)
        filtered = {k: v for k, v in full["vectors"].items() if k in names}
        return {"B": full["B"], "nodes": full["nodes"], "vectors": filtered}

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    def verify_integrity(self):
        """Return integrity report computed via SQL queries."""
        total_nodes = self.conn.execute(
            "SELECT COUNT(*) FROM nodes"
        ).fetchone()[0]
        total_vectors = self.conn.execute(
            "SELECT COUNT(*) FROM vectors"
        ).fetchone()[0]

        if total_vectors == 0:
            return {
                "orphaned_nodes": total_nodes,
                "duplicate_content": 0,
                "invalid_refs": 0,
                "total_nodes": total_nodes,
                "total_vectors": 0,
            }

        # Orphaned nodes: not reachable from any vector root/tail
        reachable_count = self.conn.execute(
            """
            WITH RECURSIVE reachable(nid) AS (
                SELECT root_id AS nid FROM vectors
                UNION
                SELECT tail_id AS nid FROM vectors
                UNION
                SELECT ic.child_id
                FROM inner_children ic
                JOIN reachable r ON ic.parent_id = r.nid
            )
            SELECT COUNT(*) FROM reachable
        """
        ).fetchone()[0]
        orphaned = total_nodes - reachable_count

        # Duplicate content hashes (should be 0 due to UNIQUE constraint)
        dups = self.conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT content_hash FROM nodes
                GROUP BY content_hash HAVING COUNT(*) > 1
            )
        """
        ).fetchone()[0]

        # Invalid references
        inv = self.conn.execute(
            """
            SELECT COUNT(*) FROM inner_children
            WHERE child_id NOT IN (SELECT id FROM nodes)
               OR parent_id NOT IN (SELECT id FROM nodes)
        """
        ).fetchone()[0]
        inv += self.conn.execute(
            """
            SELECT COUNT(*) FROM vectors
            WHERE root_id NOT IN (SELECT id FROM nodes)
               OR tail_id NOT IN (SELECT id FROM nodes)
        """
        ).fetchone()[0]

        return {
            "orphaned_nodes": orphaned,
            "duplicate_content": dups,
            "invalid_refs": inv,
            "total_nodes": total_nodes,
            "total_vectors": total_vectors,
        }

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self):
        """Return statistics about the store."""
        tn = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        ln = self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE node_type='leaf'"
        ).fetchone()[0]
        inn = self.conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE node_type='inner'"
        ).fetchone()[0]
        tv = self.conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        te = self.conn.execute(
            "SELECT COUNT(*) FROM inner_children"
        ).fetchone()[0]
        return {
            "total_nodes": tn,
            "leaf_nodes": ln,
            "inner_nodes": inn,
            "total_vectors": tv,
            "total_edges": te,
        }

    def close(self):
        """Close the database connection."""
        self.conn.close()
