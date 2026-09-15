
"""
Full implementation of the Persistent Vector Snapshot Store.
"""

import sqlite3
import json
import hashlib
from persistent_vector import Node, PersistentVector, BITS, WIDTH, MASK


class SnapStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_db(self, schema_path):
        with open(schema_path) as f:
            self.conn.executescript(f.read())
        self.conn.commit()

    # -- internal helpers --

    def _node_hash(self, node):
        """Merkle-style content hash for deduplication."""
        if node.is_leaf:
            content = json.dumps(["L", node.values], sort_keys=True)
        else:
            child_hashes = [self._node_hash(c) for c in node.children]
            content = json.dumps(["I", child_hashes], sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def _store_tree(self, node, cursor, seen):
        """Recursively store tree nodes, deduplicating by content hash."""
        if node is None:
            return None
        py_id = id(node)
        if py_id in seen:
            return seen[py_id]

        nhash = self._node_hash(node)

        # Check if node with this content already exists
        cursor.execute("SELECT node_id FROM nodes WHERE node_hash = ?", (nhash,))
        row = cursor.fetchone()
        if row:
            seen[py_id] = row[0]
            return row[0]

        if node.is_leaf:
            cursor.execute(
                "INSERT INTO nodes (node_hash, is_leaf, data) VALUES (?, 1, ?)",
                (nhash, json.dumps(node.values))
            )
        else:
            child_ids = [self._store_tree(c, cursor, seen) for c in node.children]
            cursor.execute(
                "INSERT INTO nodes (node_hash, is_leaf, data) VALUES (?, 0, ?)",
                (nhash, json.dumps(child_ids))
            )

        nid = cursor.lastrowid
        seen[py_id] = nid
        return nid

    def _load_tree(self, node_id, cursor, cache):
        """Recursively load tree, using cache to restore sharing."""
        if node_id is None:
            return None
        if node_id in cache:
            return cache[node_id]

        cursor.execute("SELECT is_leaf, data FROM nodes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Node {node_id} not found in database")
        is_leaf, data_str = row
        data = json.loads(data_str)

        if is_leaf:
            node = Node(values=data)
        else:
            children = [self._load_tree(cid, cursor, cache) for cid in data]
            node = Node(children=children)

        cache[node_id] = node
        return node

    # -- public API --

    def save(self, name, vector):
        self.save_batch({name: vector})

    def save_batch(self, named_vectors):
        cursor = self.conn.cursor()
        seen = {}
        for name, vec in named_vectors.items():
            root_id = self._store_tree(vec.root, cursor, seen)
            cursor.execute("DELETE FROM snapshots WHERE name = ?", (name,))
            cursor.execute(
                "INSERT INTO snapshots (name, root_node_id, tail, vec_size, shift) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, root_id, json.dumps(vec.tail), vec.size, vec.shift)
            )
        self.conn.commit()

    def load(self, name):
        result = self.load_batch([name])
        return result[name]

    def load_batch(self, names):
        cursor = self.conn.cursor()
        cache = {}
        result = {}
        for name in names:
            cursor.execute(
                "SELECT root_node_id, tail, vec_size, shift "
                "FROM snapshots WHERE name = ?",
                (name,)
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(f"Snapshot '{name}' not found")
            root_id, tail_json, size, shift = row
            root = self._load_tree(root_id, cursor, cache)
            result[name] = PersistentVector(
                size=size, shift=shift, root=root, tail=json.loads(tail_json)
            )
        return result

    def diff(self, name_a, name_b):
        vecs = self.load_batch([name_a, name_b])
        vec_a = vecs[name_a]
        vec_b = vecs[name_b]

        changed = []
        added = []
        removed = []
        nodes_compared = [0]
        min_len = min(len(vec_a), len(vec_b))

        def diff_nodes(na, nb, shift, base_idx, limit):
            if na is nb:
                return
            nodes_compared[0] += 1
            if na.is_leaf and nb.is_leaf:
                for j in range(min(len(na.values), len(nb.values))):
                    idx = base_idx + j
                    if idx < limit and na.values[j] != nb.values[j]:
                        changed.append((idx, na.values[j], nb.values[j]))
            elif not na.is_leaf and not nb.is_leaf:
                stride = 1 << shift
                for j in range(min(len(na.children), len(nb.children))):
                    child_base = base_idx + j * stride
                    if child_base < limit:
                        diff_nodes(na.children[j], nb.children[j],
                                   shift - BITS, child_base, limit)

        if (vec_a.root is not None and vec_b.root is not None
                and vec_a.shift == vec_b.shift):
            tree_limit = min(vec_a._tail_offset(), vec_b._tail_offset(), min_len)
            diff_nodes(vec_a.root, vec_b.root, vec_a.shift, 0, tree_limit)
            for i in range(tree_limit, min_len):
                va = vec_a.get(i)
                vb = vec_b.get(i)
                if va != vb:
                    changed.append((i, va, vb))
        elif vec_a.root is not None or vec_b.root is not None:
            for i in range(min_len):
                va = vec_a.get(i)
                vb = vec_b.get(i)
                if va != vb:
                    changed.append((i, va, vb))
        else:
            for i in range(min_len):
                va = vec_a.get(i)
                vb = vec_b.get(i)
                if va != vb:
                    changed.append((i, va, vb))

        if len(vec_b) > len(vec_a):
            for i in range(len(vec_a), len(vec_b)):
                added.append((i, vec_b.get(i)))
        elif len(vec_a) > len(vec_b):
            for i in range(len(vec_b), len(vec_a)):
                removed.append((i, vec_a.get(i)))

        return {
            "changed": changed,
            "added": added,
            "removed": removed,
            "nodes_compared": nodes_compared[0],
        }

    def delete(self, name):
        self.conn.execute("DELETE FROM snapshots WHERE name = ?", (name,))
        self.conn.commit()

    def list_snapshots(self):
        cursor = self.conn.execute("SELECT name FROM snapshots ORDER BY name")
        return [row[0] for row in cursor.fetchall()]

    def node_count(self):
        cursor = self.conn.execute("SELECT COUNT(*) FROM nodes")
        return cursor.fetchone()[0]
