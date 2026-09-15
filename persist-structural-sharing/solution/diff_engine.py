"""
Structural diff engine for persistent vectors stored in a PoolStore.

Exploits content-addressed tree structure to skip shared subtrees,
achieving diff complexity proportional to actual changes rather than
vector size.

"""

import json
import sys

sys.path.insert(0, "/app")
from pvec import B, M, MASK


class StructuralDiff:
    """Computes element-level diffs between vectors in a PoolStore."""

    def __init__(self, store):
        self.store = store
        self.conn = store.conn

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _get_vec(self, name):
        row = self.conn.execute(
            "SELECT root_id, tail_id, size, shift FROM vectors WHERE name=?",
            (name,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Vector '{name}' not found")
        return {
            "root_id": row[0],
            "tail_id": row[1],
            "size": row[2],
            "shift": row[3],
        }

    def _get_leaf_data(self, node_id):
        rows = self.conn.execute(
            "SELECT value FROM leaf_data WHERE node_id=? ORDER BY position",
            (node_id,),
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def _get_children(self, node_id):
        rows = self.conn.execute(
            "SELECT child_id FROM inner_children WHERE parent_id=? ORDER BY position",
            (node_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def _get_node_type(self, node_id):
        return self.conn.execute(
            "SELECT node_type FROM nodes WHERE id=?", (node_id,),
        ).fetchone()[0]

    @staticmethod
    def _tail_offset(size):
        if size < M:
            return 0
        return ((size - 1) >> B) << B

    def _collect_reachable(self, node_id, seen=None):
        if seen is None:
            seen = set()
        if node_id in seen:
            return seen
        seen.add(node_id)
        ntype = self._get_node_type(node_id)
        if ntype == "inner":
            for child_id in self._get_children(node_id):
                self._collect_reachable(child_id, seen)
        return seen

    def _get_element(self, vec, index):
        """Get a single element from a vector by traversing the DB tree."""
        tail_off = self._tail_offset(vec["size"])
        if index >= tail_off:
            data = self._get_leaf_data(vec["tail_id"])
            return data[index - tail_off]
        node_id = vec["root_id"]
        level = vec["shift"]
        while level > 0:
            children = self._get_children(node_id)
            child_idx = (index >> level) & MASK
            node_id = children[child_idx]
            level -= B
        data = self._get_leaf_data(node_id)
        return data[index & MASK]

    # ------------------------------------------------------------------
    # Tree-level structural diff
    # ------------------------------------------------------------------

    def _diff_nodes(self, node_a, node_b, shift, base_idx, limit, modified, stats):
        """Recursively diff two subtrees at the same shift level.

        When both sides resolve to the same database node ID the entire
        subtree is skipped — this is the core optimisation.
        """
        if node_a == node_b:
            stats["nodes_skipped"] += 1
            return

        stats["nodes_visited"] += 2

        type_a = self._get_node_type(node_a)
        type_b = self._get_node_type(node_b)

        if type_a == "leaf" and type_b == "leaf":
            data_a = self._get_leaf_data(node_a)
            data_b = self._get_leaf_data(node_b)
            for i in range(min(len(data_a), len(data_b))):
                idx = base_idx + i
                if idx < limit:
                    if data_a[i] != data_b[i]:
                        modified[idx] = [data_a[i], data_b[i]]
            return

        if type_a == "inner" and type_b == "inner":
            children_a = self._get_children(node_a)
            children_b = self._get_children(node_b)
            child_span = 1 << shift
            for i in range(min(len(children_a), len(children_b))):
                child_base = base_idx + i * child_span
                if child_base >= limit:
                    break
                self._diff_nodes(
                    children_a[i],
                    children_b[i],
                    shift - B,
                    child_base,
                    limit,
                    modified,
                    stats,
                )
            return

        raise ValueError(f"Node type mismatch at shift {shift}: {type_a} vs {type_b}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diff(self, name_a, name_b):
        """Compute element-level diff between two stored vectors.

        Returns dict with keys: modified, added, removed, stats.
        """
        a = self._get_vec(name_a)
        b = self._get_vec(name_b)

        modified = {}
        added = {}
        removed = {}
        stats = {"nodes_visited": 0, "nodes_skipped": 0, "total_reachable": 0}

        min_size = min(a["size"], b["size"])

        tail_off_a = self._tail_offset(a["size"])
        tail_off_b = self._tail_offset(b["size"])
        common_tree_end = min(tail_off_a, tail_off_b)

        # --- Structural diff on common tree range ---
        if common_tree_end > 0 and a["shift"] == b["shift"]:
            self._diff_nodes(
                a["root_id"],
                b["root_id"],
                a["shift"],
                0,
                common_tree_end,
                modified,
                stats,
            )
        elif common_tree_end > 0:
            # Different tree depths — fall back to element comparison
            for i in range(common_tree_end):
                va = self._get_element(a, i)
                vb = self._get_element(b, i)
                if va != vb:
                    modified[i] = [va, vb]

        # --- Tail comparison ---
        if tail_off_a == tail_off_b and min_size > tail_off_a:
            if a["tail_id"] == b["tail_id"]:
                stats["nodes_skipped"] += 1
            else:
                stats["nodes_visited"] += 2
                tail_a = self._get_leaf_data(a["tail_id"])
                tail_b = self._get_leaf_data(b["tail_id"])
                for i in range(min(len(tail_a), len(tail_b))):
                    idx = tail_off_a + i
                    if idx < min_size:
                        if tail_a[i] != tail_b[i]:
                            modified[idx] = [tail_a[i], tail_b[i]]
        elif common_tree_end < min_size:
            # Transition zone — tail offsets differ, compare individually
            for i in range(common_tree_end, min_size):
                va = self._get_element(a, i)
                vb = self._get_element(b, i)
                if va != vb:
                    modified[i] = [va, vb]

        # --- Added / removed ---
        if b["size"] > min_size:
            for i in range(min_size, b["size"]):
                added[i] = self._get_element(b, i)
        if a["size"] > min_size:
            for i in range(min_size, a["size"]):
                removed[i] = self._get_element(a, i)

        # --- Total reachable nodes ---
        reachable = set()
        self._collect_reachable(a["root_id"], reachable)
        self._collect_reachable(a["tail_id"], reachable)
        self._collect_reachable(b["root_id"], reachable)
        self._collect_reachable(b["tail_id"], reachable)
        stats["total_reachable"] = len(reachable)

        return {
            "modified": modified,
            "added": added,
            "removed": removed,
            "stats": stats,
        }

    def sharing_ratio(self, name_a, name_b):
        """Jaccard similarity of two vectors' reachable node sets."""
        a = self._get_vec(name_a)
        b = self._get_vec(name_b)

        reachable_a = set()
        self._collect_reachable(a["root_id"], reachable_a)
        self._collect_reachable(a["tail_id"], reachable_a)

        reachable_b = set()
        self._collect_reachable(b["root_id"], reachable_b)
        self._collect_reachable(b["tail_id"], reachable_b)

        union = reachable_a | reachable_b
        if not union:
            return 1.0
        intersection = reachable_a & reachable_b
        return len(intersection) / len(union)
