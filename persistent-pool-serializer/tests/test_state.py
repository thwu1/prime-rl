
import sys
sys.path.insert(0, '/app')
import os
import json
import sqlite3
import subprocess
import pytest
from persistent_vector import Node, PersistentVector, BITS, WIDTH
from snapstore import SnapStore
from pool_serializer import serialize_to_pools, deserialize_from_pools, transform_pool, compute_shared_diff


def count_tree_nodes(node):
    """Count all nodes in a tree rooted at node."""
    if node is None:
        return 0
    if node.is_leaf:
        return 1
    return 1 + sum(count_tree_nodes(c) for c in node.children)


def count_unique_tree_nodes(*roots):
    """Count unique nodes across multiple trees using identity."""
    seen = set()
    def walk(node):
        if node is None or id(node) in seen:
            return 0
        seen.add(id(node))
        if node.is_leaf:
            return 1
        return 1 + sum(walk(c) for c in node.children)
    return sum(walk(r) for r in roots)


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SnapStore(db_path)
    s.init_db("/app/schema.sql")
    return s


@pytest.fixture
def app_store():
    """Store at /app/store.db for CLI script tests."""
    db_path = "/app/store.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    s = SnapStore(db_path)
    s.init_db("/app/schema.sql")
    yield s
    if os.path.exists(db_path):
        os.remove(db_path)


# ---------------------------------------------------------------------------
# PersistentVector sanity
# ---------------------------------------------------------------------------

class TestPersistentVectorSanity:
    def test_push_back_and_get(self):
        v = PersistentVector()
        for ch in "abcdefgh":
            v = v.push_back(ch)
        assert list(v) == list("abcdefgh")

    def test_structural_sharing_exists(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        assert v1.root is not v2.root
        assert v1.root.children[1] is v2.root.children[1]


# ---------------------------------------------------------------------------
# Save / Load round-trip
# ---------------------------------------------------------------------------

class TestSaveLoad:
    def test_round_trip(self, store):
        v = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        store.save("v1", v)
        loaded = store.load("v1")
        assert list(loaded) == ["a", "b", "c", "d", "e", "f"]

    def test_empty_vector(self, store):
        v = PersistentVector()
        store.save("empty", v)
        loaded = store.load("empty")
        assert list(loaded) == []
        assert len(loaded) == 0

    def test_tail_only(self, store):
        v = PersistentVector.from_list(["x"])
        store.save("one", v)
        assert list(store.load("one")) == ["x"]

    def test_numeric_values(self, store):
        v = PersistentVector.from_list([10, 20, 30, 40, 50, 60])
        store.save("nums", v)
        assert list(store.load("nums")) == [10, 20, 30, 40, 50, 60]

    def test_large_vector(self, store):
        items = [f"item_{i}" for i in range(20)]
        v = PersistentVector.from_list(items)
        store.save("large", v)
        assert list(store.load("large")) == items

    def test_load_nonexistent(self, store):
        with pytest.raises(KeyError):
            store.load("nonexistent")

    def test_overwrite(self, store):
        store.save("s", PersistentVector.from_list(["a", "b"]))
        store.save("s", PersistentVector.from_list(["x", "y", "z"]))
        assert list(store.load("s")) == ["x", "y", "z"]

    def test_multiple_vectors_batch(self, store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d"])
        v2 = v1.push_back("e").push_back("f")
        v3 = v1.set(0, "X")
        store.save_batch({"v1": v1, "v2": v2, "v3": v3})
        loaded = store.load_batch(["v1", "v2", "v3"])
        assert list(loaded["v1"]) == ["a", "b", "c", "d"]
        assert list(loaded["v2"]) == ["a", "b", "c", "d", "e", "f"]
        assert list(loaded["v3"]) == ["X", "b", "c", "d"]


# ---------------------------------------------------------------------------
# Structural sharing preservation
# ---------------------------------------------------------------------------

class TestSharing:
    def test_node_deduplication(self, store):
        """Shared tree nodes must be stored once, not duplicated."""
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        store.save_batch({"v1": v1, "v2": v2})

        total_naive = count_tree_nodes(v1.root) + count_tree_nodes(v2.root)
        db_count = store.node_count()
        assert db_count < total_naive, (
            f"DB has {db_count} nodes but naive tree walk counts {total_naive}; "
            f"shared nodes must be deduplicated"
        )

    def test_sharing_restored_on_load(self, store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        store.save_batch({"v1": v1, "v2": v2})
        loaded = store.load_batch(["v1", "v2"])
        assert loaded["v1"].root.children[1] is loaded["v2"].root.children[1], \
            "Shared subtrees must be the same Python object after load"

    def test_sharing_deep_tree(self, store):
        """Deep tree: changing one leaf should share all other subtrees."""
        items = list(range(16))
        v1 = PersistentVector.from_list(items)
        v2 = v1.set(0, 999)
        store.save_batch({"v1": v1, "v2": v2})
        loaded = store.load_batch(["v1", "v2"])
        assert loaded["v1"].root.children[1] is loaded["v2"].root.children[1]

    def test_diamond_sharing(self, store):
        """v2 and v3 both derive from v1 with different modifications."""
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        v3 = v1.set(2, "Y")
        store.save_batch({"v1": v1, "v2": v2, "v3": v3})
        loaded = store.load_batch(["v1", "v2", "v3"])
        assert list(loaded["v1"]) == ["a", "b", "c", "d", "e", "f"]
        assert list(loaded["v2"]) == ["X", "b", "c", "d", "e", "f"]
        assert list(loaded["v3"]) == ["a", "b", "Y", "d", "e", "f"]

    def test_identical_vectors_share_root(self, store):
        v = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        store.save_batch({"v1": v, "v2": v})
        loaded = store.load_batch(["v1", "v2"])
        assert loaded["v1"].root is loaded["v2"].root


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

class TestDiff:
    def test_identical_snapshots_skip_all(self, store):
        v = PersistentVector.from_list(["a", "b", "c", "d"])
        store.save_batch({"v1": v, "v2": v})
        result = store.diff("v1", "v2")
        assert result["changed"] == []
        assert result["added"] == []
        assert result["removed"] == []
        assert result["nodes_compared"] == 0

    def test_single_change(self, store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        store.save_batch({"v1": v1, "v2": v2})
        result = store.diff("v1", "v2")
        assert (0, "a", "X") in result["changed"]
        assert len(result["changed"]) == 1

    def test_exploits_sharing(self, store):
        """Diff must visit fewer nodes than total when subtrees are shared."""
        items = list(range(16))
        v1 = PersistentVector.from_list(items)
        v2 = v1.set(0, 999)
        store.save_batch({"v1": v1, "v2": v2})
        result = store.diff("v1", "v2")
        assert len(result["changed"]) == 1
        total = count_tree_nodes(v1.root)
        assert result["nodes_compared"] < total, \
            f"Should skip shared subtrees ({result['nodes_compared']} vs {total})"

    def test_added_elements(self, store):
        v1 = PersistentVector.from_list(["a", "b"])
        v2 = PersistentVector.from_list(["a", "b", "c", "d"])
        store.save("v1", v1)
        store.save("v2", v2)
        result = store.diff("v1", "v2")
        added_indices = [idx for idx, _ in result["added"]]
        assert 2 in added_indices
        assert 3 in added_indices

    def test_removed_elements(self, store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d"])
        v2 = PersistentVector.from_list(["a", "b"])
        store.save("v1", v1)
        store.save("v2", v2)
        result = store.diff("v1", "v2")
        removed_indices = [idx for idx, _ in result["removed"]]
        assert 2 in removed_indices
        assert 3 in removed_indices

    def test_changed_values_correct(self, store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(2, "Z")
        store.save_batch({"v1": v1, "v2": v2})
        result = store.diff("v1", "v2")
        assert (2, "c", "Z") in result["changed"]

    def test_diff_nonexistent(self, store):
        store.save("v1", PersistentVector.from_list(["a"]))
        with pytest.raises(KeyError):
            store.diff("v1", "nope")


# ---------------------------------------------------------------------------
# Delete / List / Count
# ---------------------------------------------------------------------------

class TestDeleteListCount:
    def test_delete(self, store):
        store.save("v1", PersistentVector.from_list(["a"]))
        assert "v1" in store.list_snapshots()
        store.delete("v1")
        assert "v1" not in store.list_snapshots()

    def test_list_sorted(self, store):
        v = PersistentVector.from_list(["a"])
        store.save("gamma", v)
        store.save("alpha", v)
        store.save("beta", v)
        assert store.list_snapshots() == ["alpha", "beta", "gamma"]

    def test_node_count(self, store):
        assert store.node_count() == 0
        store.save("v1", PersistentVector.from_list(["a", "b", "c", "d"]))
        assert store.node_count() > 0


# ---------------------------------------------------------------------------
# compact.sh (subprocess)
# ---------------------------------------------------------------------------

class TestCompactSh:
    def test_removes_all_orphans(self, app_store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        app_store.save_batch({"v1": v1, "v2": v2})
        app_store.delete("v1")
        app_store.delete("v2")

        result = subprocess.run(
            ["bash", "/app/compact.sh", "/app/store.db"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"compact.sh failed: {result.stderr}"

        store2 = SnapStore("/app/store.db")
        store2.init_db("/app/schema.sql")
        assert store2.node_count() == 0, \
            "All nodes should be removed when no snapshots reference them"

    def test_preserves_live_nodes(self, app_store):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        app_store.save_batch({"v1": v1, "v2": v2})
        app_store.delete("v2")

        result = subprocess.run(
            ["bash", "/app/compact.sh", "/app/store.db"],
            capture_output=True, text=True
        )
        assert result.returncode == 0

        store2 = SnapStore("/app/store.db")
        store2.init_db("/app/schema.sql")
        assert list(store2.load("v1")) == ["a", "b", "c", "d", "e", "f"]

    def test_shared_nodes_survive(self, app_store):
        """Shared node must survive if any snapshot still references it."""
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        app_store.save_batch({"v1": v1, "v2": v2})
        nodes_before = app_store.node_count()
        app_store.delete("v1")

        subprocess.run(
            ["bash", "/app/compact.sh", "/app/store.db"],
            capture_output=True, text=True
        )

        store2 = SnapStore("/app/store.db")
        store2.init_db("/app/schema.sql")
        loaded = store2.load("v2")
        assert list(loaded) == ["X", "b", "c", "d", "e", "f"]
        assert store2.node_count() <= nodes_before


# ---------------------------------------------------------------------------
# export.sh (subprocess)
# ---------------------------------------------------------------------------

class TestExportSh:
    def test_export_json(self, app_store):
        v = PersistentVector.from_list(["hello", "world", "foo", "bar"])
        app_store.save("test_snap", v)

        result = subprocess.run(
            ["bash", "/app/export.sh", "/app/store.db", "test_snap"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"export.sh failed: {result.stderr}"

        data = json.loads(result.stdout)
        assert data["name"] == "test_snap"
        assert data["size"] == 4
        assert data["elements"] == ["hello", "world", "foo", "bar"]

    def test_export_nonexistent(self, app_store):
        result = subprocess.run(
            ["bash", "/app/export.sh", "/app/store.db", "nope"],
            capture_output=True, text=True
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# Pool Serialization (pool_serializer.py)
# ---------------------------------------------------------------------------

class TestPoolSerialize:
    def test_round_trip_basic(self):
        v = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        pool = serialize_to_pools([v])
        [loaded] = deserialize_from_pools(pool)
        assert list(loaded) == ["a", "b", "c", "d", "e", "f"]

    def test_numeric_round_trip(self):
        v = PersistentVector.from_list([10, 20, 30, 40, 50, 60])
        pool = serialize_to_pools([v])
        [loaded] = deserialize_from_pools(pool)
        assert list(loaded) == [10, 20, 30, 40, 50, 60]

    def test_sharing_preserved_round_trip(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        pool = serialize_to_pools([v1, v2])
        [l1, l2] = deserialize_from_pools(pool)
        assert list(l1) == ["a", "b", "c", "d", "e", "f"]
        assert list(l2) == ["X", "b", "c", "d", "e", "f"]
        assert l1.root.children[1] is l2.root.children[1], \
            "Shared subtrees must be the same Python object after pool round-trip"

    def test_pool_no_duplicate_ids(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        pool = serialize_to_pools([v1, v2])
        all_ids = []
        for nid, _ in pool["leaves"]:
            all_ids.append(nid)
        for nid, _ in pool["inners"]:
            all_ids.append(nid)
        assert len(all_ids) == len(set(all_ids)), "Node IDs must be unique"

    def test_shared_nodes_appear_once(self):
        """Pool must deduplicate: shared nodes appear once, not per-vector."""
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        pool = serialize_to_pools([v1, v2])
        total_pool_nodes = len(pool["leaves"]) + len(pool["inners"])
        unique_in_memory = count_unique_tree_nodes(v1.root, v2.root)
        assert total_pool_nodes == unique_in_memory, (
            f"Pool has {total_pool_nodes} nodes but {unique_in_memory} unique "
            f"nodes exist in memory — shared nodes must appear exactly once"
        )

    def test_empty_vector(self):
        v = PersistentVector()
        pool = serialize_to_pools([v])
        [loaded] = deserialize_from_pools(pool)
        assert list(loaded) == []
        assert len(loaded) == 0

    def test_tail_only(self):
        v = PersistentVector.from_list(["x"])
        pool = serialize_to_pools([v])
        [loaded] = deserialize_from_pools(pool)
        assert list(loaded) == ["x"]

    def test_pool_format_structure(self):
        v = PersistentVector.from_list(["a", "b", "c", "d"])
        pool = serialize_to_pools([v])
        assert pool["B"] == BITS
        assert isinstance(pool["leaves"], list)
        assert isinstance(pool["inners"], list)
        assert isinstance(pool["vectors"], list)
        assert len(pool["vectors"]) == 1
        vd = pool["vectors"][0]
        assert vd["size"] == 4
        assert "root" in vd
        assert "tail" in vd
        assert "shift" in vd

    def test_diamond_sharing_pool(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        v3 = v1.set(2, "Y")
        pool = serialize_to_pools([v1, v2, v3])
        [l1, l2, l3] = deserialize_from_pools(pool)
        assert list(l1) == ["a", "b", "c", "d", "e", "f"]
        assert list(l2) == ["X", "b", "c", "d", "e", "f"]
        assert list(l3) == ["a", "b", "Y", "d", "e", "f"]

    def test_identical_vectors_share_root(self):
        v = PersistentVector.from_list(["a", "b", "c", "d"])
        pool = serialize_to_pools([v, v])
        [l1, l2] = deserialize_from_pools(pool)
        if l1.root is not None:
            assert l1.root is l2.root

    def test_large_vector_pool(self):
        items = list(range(20))
        v = PersistentVector.from_list(items)
        pool = serialize_to_pools([v])
        [loaded] = deserialize_from_pools(pool)
        assert list(loaded) == items


# ---------------------------------------------------------------------------
# Pool Transform
# ---------------------------------------------------------------------------

class TestTransformPool:
    def test_transform_leaf_values(self):
        v = PersistentVector.from_list(["a", "b", "c", "d"])
        pool = serialize_to_pools([v])
        transformed = transform_pool(pool, str.upper)
        [loaded] = deserialize_from_pools(transformed)
        assert list(loaded) == ["A", "B", "C", "D"]

    def test_no_mutation_of_original(self):
        v = PersistentVector.from_list(["a", "b", "c", "d"])
        pool = serialize_to_pools([v])
        _ = transform_pool(pool, str.upper)
        # If original was mutated, deserializing it gives uppercase
        [check] = deserialize_from_pools(pool)
        assert list(check) == ["a", "b", "c", "d"], \
            "transform_pool must not mutate the original pool"

    def test_transform_preserves_structure(self):
        v1 = PersistentVector.from_list([1, 2, 3, 4, 5, 6])
        v2 = v1.set(0, 10)
        pool = serialize_to_pools([v1, v2])
        transformed = transform_pool(pool, lambda x: x * 100)
        [l1, l2] = deserialize_from_pools(transformed)
        assert list(l1) == [100, 200, 300, 400, 500, 600]
        assert list(l2) == [1000, 200, 300, 400, 500, 600]
        assert len(transformed["inners"]) == len(pool["inners"])
        assert len(transformed["leaves"]) == len(pool["leaves"])

    def test_transform_tail_values(self):
        v = PersistentVector.from_list(["a"])
        pool = serialize_to_pools([v])
        transformed = transform_pool(pool, str.upper)
        [loaded] = deserialize_from_pools(transformed)
        assert list(loaded) == ["A"]


# ---------------------------------------------------------------------------
# Compute Shared Diff (pool_serializer)
# ---------------------------------------------------------------------------

class TestComputeSharedDiff:
    def test_identical_vectors_skip_all(self):
        v = PersistentVector.from_list(["a", "b", "c", "d"])
        result = compute_shared_diff(v, v)
        assert result["changed"] == []
        assert result["added"] == []
        assert result["removed"] == []
        assert result["nodes_visited"] == 0

    def test_single_change_detected(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        result = compute_shared_diff(v1, v2)
        assert (0, "a", "X") in result["changed"]
        assert len(result["changed"]) == 1

    def test_sharing_reduces_visited_nodes(self):
        items = list(range(16))
        v1 = PersistentVector.from_list(items)
        v2 = v1.set(0, 999)
        result = compute_shared_diff(v1, v2)
        total = count_tree_nodes(v1.root)
        assert result["nodes_visited"] < total, \
            f"Should skip shared subtrees ({result['nodes_visited']} vs {total})"

    def test_added_elements_detected(self):
        v1 = PersistentVector.from_list(["a", "b"])
        v2 = PersistentVector.from_list(["a", "b", "c", "d"])
        result = compute_shared_diff(v1, v2)
        added_indices = [idx for idx, _ in result["added"]]
        assert 2 in added_indices
        assert 3 in added_indices

    def test_removed_elements_detected(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d"])
        v2 = PersistentVector.from_list(["a", "b"])
        result = compute_shared_diff(v1, v2)
        removed_indices = [idx for idx, _ in result["removed"]]
        assert 2 in removed_indices
        assert 3 in removed_indices

    def test_multiple_changes(self):
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X").set(2, "Z")
        result = compute_shared_diff(v1, v2)
        changed_indices = [idx for idx, _, _ in result["changed"]]
        assert 0 in changed_indices
        assert 2 in changed_indices


# ---------------------------------------------------------------------------
# Cross-layer Integration
# ---------------------------------------------------------------------------

class TestCrossIntegration:
    def test_pool_to_db_preserves_sharing(self, store):
        """Vectors reconstructed from pool must retain sharing through DB."""
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(0, "X")
        pool = serialize_to_pools([v1, v2])
        [p1, p2] = deserialize_from_pools(pool)
        store.save_batch({"p1": p1, "p2": p2})
        loaded = store.load_batch(["p1", "p2"])
        assert list(loaded["p1"]) == ["a", "b", "c", "d", "e", "f"]
        assert list(loaded["p2"]) == ["X", "b", "c", "d", "e", "f"]
        assert loaded["p1"].root.children[1] is loaded["p2"].root.children[1]

    def test_transform_then_store(self, store):
        """Transformed pool values must survive DB round-trip."""
        v = PersistentVector.from_list([1, 2, 3, 4])
        pool = serialize_to_pools([v])
        transformed = transform_pool(pool, lambda x: x * 10)
        [tv] = deserialize_from_pools(transformed)
        store.save("transformed", tv)
        loaded = store.load("transformed")
        assert list(loaded) == [10, 20, 30, 40]

    def test_db_diff_matches_pool_diff(self, store):
        """DB-level diff and pool-level diff must agree on changes."""
        v1 = PersistentVector.from_list(["a", "b", "c", "d", "e", "f"])
        v2 = v1.set(2, "Z")
        store.save_batch({"v1": v1, "v2": v2})
        db_diff = store.diff("v1", "v2")
        pool_diff = compute_shared_diff(v1, v2)
        assert set(map(tuple, db_diff["changed"])) == set(map(tuple, pool_diff["changed"]))
