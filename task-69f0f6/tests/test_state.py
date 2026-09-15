
"""
Tests for the key-value store implementation.
"""

import sys
import os
sys.path.insert(0, "/app")

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from bplustree import Config, new_tree, DataNode, IndexNode, lookup_path, right_successor_path
from ops import InsertOp, DeleteOp
import hitchhiker

try:
    import redis as redis_lib
except ImportError:
    redis_lib = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CFG_SMALL = Config(index_b=3, data_b=3, op_buf_size=2)
CFG_MEDIUM = Config(index_b=4, data_b=4, op_buf_size=3)
CFG_WIDE = Config(index_b=10, data_b=10, op_buf_size=5)


def reference_apply(ops_sequence, universe=None):
    """Apply a mixed sequence of (op_type, key, value?) to a plain dict."""
    d = {}
    for op in ops_sequence:
        if op[0] == "insert":
            d[op[1]] = op[2]
        elif op[0] == "delete":
            d.pop(op[1], None)
    return d


def tree_to_sorted_list(tree, min_key=-10**18):
    """Use forward_iter to get all elements from the tree."""
    return list(hitchhiker.forward_iter(tree, min_key))


def check_balanced(node, depth=0):
    """Verify B+ tree balance invariants recursively."""
    if isinstance(node, DataNode):
        return depth
    assert isinstance(node, IndexNode), f"Unknown node type: {type(node)}"
    child_depths = []
    for child in node.children:
        child_depths.append(check_balanced(child, depth + 1))
    # All children must be at same depth
    assert len(set(child_depths)) == 1, (
        f"Unbalanced tree at depth {depth}: child depths = {child_depths}"
    )
    return child_depths[0]


def count_buffered_ops(node):
    """Count total ops in all op_buf fields in the tree."""
    if isinstance(node, DataNode):
        return 0
    total = len(node.op_buf)
    for child in node.children:
        total += count_buffered_ops(child)
    return total


# ---------------------------------------------------------------------------
# Test: basic insert and lookup
# ---------------------------------------------------------------------------

class TestBasicOperations:
    def test_single_insert_lookup(self):
        tree = new_tree(CFG_SMALL)
        tree = hitchhiker.insert(tree, 42, "hello")
        assert hitchhiker.lookup(tree, 42) == "hello"
        assert hitchhiker.lookup(tree, 99) is None

    def test_multiple_inserts(self):
        tree = new_tree(CFG_SMALL)
        for i in range(20):
            tree = hitchhiker.insert(tree, i, i * 10)
        for i in range(20):
            assert hitchhiker.lookup(tree, i) == i * 10, f"Failed for key {i}"

    def test_insert_overwrite(self):
        tree = new_tree(CFG_SMALL)
        tree = hitchhiker.insert(tree, 5, "first")
        tree = hitchhiker.insert(tree, 5, "second")
        assert hitchhiker.lookup(tree, 5) == "second"

    def test_delete_existing(self):
        tree = new_tree(CFG_SMALL)
        tree = hitchhiker.insert(tree, 10, "a")
        tree = hitchhiker.insert(tree, 20, "b")
        tree = hitchhiker.delete(tree, 10)
        assert hitchhiker.lookup(tree, 10) is None
        assert hitchhiker.lookup(tree, 20) == "b"

    def test_delete_nonexistent(self):
        tree = new_tree(CFG_SMALL)
        tree = hitchhiker.insert(tree, 1, "x")
        tree = hitchhiker.delete(tree, 999)  # should not error
        assert hitchhiker.lookup(tree, 1) == "x"

    def test_insert_delete_same_key(self):
        tree = new_tree(CFG_SMALL)
        tree = hitchhiker.insert(tree, 7, "val")
        tree = hitchhiker.delete(tree, 7)
        tree = hitchhiker.insert(tree, 7, "new_val")
        assert hitchhiker.lookup(tree, 7) == "new_val"


# ---------------------------------------------------------------------------
# Test: forward iteration
# ---------------------------------------------------------------------------

class TestForwardIter:
    def test_empty_tree(self):
        tree = new_tree(CFG_SMALL)
        assert tree_to_sorted_list(tree) == []

    def test_small_forward_iter(self):
        tree = new_tree(CFG_SMALL)
        keys = [5, 3, 8, 1, 9, 2, 7, 4, 6]
        for k in keys:
            tree = hitchhiker.insert(tree, k, k * 100)
        result = tree_to_sorted_list(tree, 0)
        expected = [(k, k * 100) for k in sorted(keys)]
        assert result == expected

    def test_forward_iter_from_midpoint(self):
        tree = new_tree(CFG_SMALL)
        for i in range(1, 11):
            tree = hitchhiker.insert(tree, i, i)
        result = list(hitchhiker.forward_iter(tree, 5))
        expected = [(i, i) for i in range(5, 11)]
        assert result == expected

    def test_forward_iter_with_deletes(self):
        tree = new_tree(CFG_SMALL)
        for i in range(10):
            tree = hitchhiker.insert(tree, i, i)
        for i in [2, 4, 6, 8]:
            tree = hitchhiker.delete(tree, i)
        result = tree_to_sorted_list(tree, 0)
        expected = [(i, i) for i in [0, 1, 3, 5, 7, 9]]
        assert result == expected


# ---------------------------------------------------------------------------
# Test: tree balance invariants are maintained
# ---------------------------------------------------------------------------

class TestBalance:
    def test_balanced_after_inserts(self):
        tree = new_tree(CFG_SMALL)
        for i in range(50):
            tree = hitchhiker.insert(tree, i, i)
        check_balanced(tree)

    def test_balanced_after_mixed_ops(self):
        tree = new_tree(CFG_SMALL)
        for i in range(100):
            tree = hitchhiker.insert(tree, i, i)
        for i in range(0, 100, 3):
            tree = hitchhiker.delete(tree, i)
        check_balanced(tree)


# ---------------------------------------------------------------------------
# Test: buffer overflow cascading
# ---------------------------------------------------------------------------

class TestBufferCascading:
    def test_overflow_triggers_cascade(self):
        """With op_buf_size=2, inserting 3+ items must trigger cascading."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        for i in range(10):
            tree = hitchhiker.insert(tree, i, i)
        for i in range(10):
            assert hitchhiker.lookup(tree, i) == i, f"Lost key {i} after cascading"

    def test_deep_cascade(self):
        """Force multi-level cascading with tiny buffers."""
        cfg = Config(index_b=2, data_b=2, op_buf_size=1)
        tree = new_tree(cfg)
        for i in range(30):
            tree = hitchhiker.insert(tree, i, i * 2)
        for i in range(30):
            assert hitchhiker.lookup(tree, i) == i * 2, f"Failed for key {i}"
        check_balanced(tree)

    def test_large_buffer_fewer_cascades(self):
        """With large buffers, ops should be buffered without immediate cascading."""
        cfg = Config(index_b=5, data_b=5, op_buf_size=20)
        tree = new_tree(cfg)
        for i in range(100):
            tree = hitchhiker.insert(tree, i, i)
        for i in range(100):
            assert hitchhiker.lookup(tree, i) == i


# ---------------------------------------------------------------------------
# Property-based: equivalence with reference dict
# ---------------------------------------------------------------------------

op_strategy = st.one_of(
    st.tuples(st.just("insert"), st.integers(-500, 500), st.integers(-1000, 1000)),
    st.tuples(st.just("delete"), st.integers(-500, 500)),
)


class TestPropertyBased:
    @given(ops=st.lists(op_strategy, min_size=1, max_size=500))
    @settings(max_examples=80, deadline=30000, suppress_health_check=[HealthCheck.too_slow])
    def test_equivalence_small_config(self, ops):
        """Hitchhiker tree must match a reference dict for any sequence of ops."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        ref = {}

        for op in ops:
            if op[0] == "insert":
                tree = hitchhiker.insert(tree, op[1], op[2])
                ref[op[1]] = op[2]
            else:
                tree = hitchhiker.delete(tree, op[1])
                ref.pop(op[1], None)

        # Check forward iteration matches reference
        tree_items = tree_to_sorted_list(tree, -10**18)
        ref_items = sorted(ref.items())
        assert tree_items == ref_items, (
            f"Mismatch: tree has {len(tree_items)} items, ref has {len(ref_items)}"
        )

    @given(ops=st.lists(op_strategy, min_size=1, max_size=300))
    @settings(max_examples=50, deadline=30000, suppress_health_check=[HealthCheck.too_slow])
    def test_equivalence_medium_config(self, ops):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        ref = {}

        for op in ops:
            if op[0] == "insert":
                tree = hitchhiker.insert(tree, op[1], op[2])
                ref[op[1]] = op[2]
            else:
                tree = hitchhiker.delete(tree, op[1])
                ref.pop(op[1], None)

        tree_items = tree_to_sorted_list(tree, -10**18)
        ref_items = sorted(ref.items())
        assert tree_items == ref_items

    @given(ops=st.lists(op_strategy, min_size=1, max_size=200))
    @settings(max_examples=40, deadline=30000, suppress_health_check=[HealthCheck.too_slow])
    def test_equivalence_tiny_buffer(self, ops):
        """Tiny buffer size = 1 forces maximum cascading."""
        cfg = Config(index_b=2, data_b=2, op_buf_size=1)
        tree = new_tree(cfg)
        ref = {}

        for op in ops:
            if op[0] == "insert":
                tree = hitchhiker.insert(tree, op[1], op[2])
                ref[op[1]] = op[2]
            else:
                tree = hitchhiker.delete(tree, op[1])
                ref.pop(op[1], None)

        tree_items = tree_to_sorted_list(tree, -10**18)
        ref_items = sorted(ref.items())
        assert tree_items == ref_items

    @given(ops=st.lists(op_strategy, min_size=50, max_size=400))
    @settings(max_examples=40, deadline=30000, suppress_health_check=[HealthCheck.too_slow])
    def test_balance_after_random_ops(self, ops):
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        for op in ops:
            if op[0] == "insert":
                tree = hitchhiker.insert(tree, op[1], op[2])
            else:
                tree = hitchhiker.delete(tree, op[1])
        check_balanced(tree)

    @given(ops=st.lists(op_strategy, min_size=10, max_size=200))
    @settings(max_examples=50, deadline=30000, suppress_health_check=[HealthCheck.too_slow])
    def test_individual_lookups(self, ops):
        """Every key lookup must match the reference after a random op sequence."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        ref = {}

        for op in ops:
            if op[0] == "insert":
                tree = hitchhiker.insert(tree, op[1], op[2])
                ref[op[1]] = op[2]
            else:
                tree = hitchhiker.delete(tree, op[1])
                ref.pop(op[1], None)

        # Spot-check all keys that were ever mentioned
        all_keys = set()
        for op in ops:
            all_keys.add(op[1])

        for k in all_keys:
            tree_val = hitchhiker.lookup(tree, k)
            ref_val = ref.get(k)
            assert tree_val == ref_val, (
                f"Key {k}: tree={tree_val}, ref={ref_val}"
            )


# ---------------------------------------------------------------------------
# Test: deterministic regression scenarios
# ---------------------------------------------------------------------------

class TestDeterministic:
    def test_ascending_insert_sequence(self):
        tree = new_tree(CFG_SMALL)
        for i in range(100):
            tree = hitchhiker.insert(tree, i, f"v{i}")
        for i in range(100):
            assert hitchhiker.lookup(tree, i) == f"v{i}"
        check_balanced(tree)

    def test_descending_insert_sequence(self):
        tree = new_tree(CFG_SMALL)
        for i in range(99, -1, -1):
            tree = hitchhiker.insert(tree, i, i)
        items = tree_to_sorted_list(tree, -1)
        expected = [(i, i) for i in range(100)]
        assert items == expected

    def test_delete_all_then_reinsert(self):
        tree = new_tree(CFG_SMALL)
        for i in range(20):
            tree = hitchhiker.insert(tree, i, i)
        for i in range(20):
            tree = hitchhiker.delete(tree, i)
        assert tree_to_sorted_list(tree) == []
        for i in range(20):
            tree = hitchhiker.insert(tree, i, i + 100)
        for i in range(20):
            assert hitchhiker.lookup(tree, i) == i + 100

    def test_interleaved_insert_delete(self):
        """Insert and delete interleaved — stresses buffer with mixed op types."""
        tree = new_tree(CFG_SMALL)
        ref = {}
        for i in range(200):
            tree = hitchhiker.insert(tree, i, i)
            ref[i] = i
            if i % 3 == 0 and i > 0:
                del_key = i // 2
                tree = hitchhiker.delete(tree, del_key)
                ref.pop(del_key, None)

        tree_items = tree_to_sorted_list(tree, -1)
        ref_items = sorted(ref.items())
        assert tree_items == ref_items

    def test_negative_keys(self):
        tree = new_tree(CFG_SMALL)
        keys = list(range(-50, 50))
        for k in keys:
            tree = hitchhiker.insert(tree, k, k * 3)
        for k in keys:
            assert hitchhiker.lookup(tree, k) == k * 3

    def test_string_keys(self):
        tree = new_tree(CFG_MEDIUM)
        words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot",
                 "golf", "hotel", "india", "juliet", "kilo", "lima"]
        for w in words:
            tree = hitchhiker.insert(tree, w, w.upper())
        for w in words:
            assert hitchhiker.lookup(tree, w) == w.upper()
        items = tree_to_sorted_list(tree, "")
        assert [k for k, v in items] == sorted(words)

    def test_duplicate_ops_in_batch(self):
        """Enqueue multiple ops for the same key in one batch."""
        tree = new_tree(CFG_SMALL)
        for i in range(10):
            tree = hitchhiker.insert(tree, i, i)
        ops = [
            DeleteOp(key=5),
            InsertOp(key=5, value=555),
        ]
        tree = hitchhiker.enqueue(tree, ops)
        assert hitchhiker.lookup(tree, 5) == 555

    def test_wide_tree_many_ops(self):
        """Test with wider branching factor."""
        cfg = Config(index_b=10, data_b=10, op_buf_size=5)
        tree = new_tree(cfg)
        for i in range(500):
            tree = hitchhiker.insert(tree, i, i)
        items = tree_to_sorted_list(tree, -1)
        assert len(items) == 500
        assert items[0] == (0, 0)
        assert items[-1] == (499, 499)
        check_balanced(tree)


# ---------------------------------------------------------------------------
# Test: buffer utilization (structural)
# ---------------------------------------------------------------------------

class TestBufferUtilization:
    def test_ops_buffered_in_index_nodes(self):
        """After inserts on a tree with large buffers, operations should be
        pending in op_buf fields rather than immediately applied to leaves."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=100)
        tree = new_tree(cfg)
        for i in range(50):
            tree = hitchhiker.insert(tree, i, i)
        assert isinstance(tree, IndexNode), "Tree should have index nodes after 50 inserts"
        total_buffered = count_buffered_ops(tree)
        assert total_buffered > 0, (
            "Expected some operations to be buffered in index node op_buf fields"
        )

    def test_buffer_size_affects_buffering(self):
        """Larger op_buf_size should result in more buffered ops."""
        tree_small = new_tree(Config(index_b=3, data_b=3, op_buf_size=2))
        tree_large = new_tree(Config(index_b=3, data_b=3, op_buf_size=50))

        for i in range(40):
            tree_small = hitchhiker.insert(tree_small, i, i)
            tree_large = hitchhiker.insert(tree_large, i, i)

        buf_small = count_buffered_ops(tree_small)
        buf_large = count_buffered_ops(tree_large)

        assert buf_large > buf_small, (
            f"Larger buffer size should retain more ops: small={buf_small}, large={buf_large}"
        )

    def test_correctness_with_heavy_buffering(self):
        """Large buffer should still produce correct results via lookup and iter."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=200)
        tree = new_tree(cfg)
        ref = {}
        for i in range(100):
            tree = hitchhiker.insert(tree, i, i * 7)
            ref[i] = i * 7
        for i in range(0, 100, 3):
            tree = hitchhiker.delete(tree, i)
            del ref[i]

        for k, v in ref.items():
            assert hitchhiker.lookup(tree, k) == v
        items = tree_to_sorted_list(tree, -1)
        assert items == sorted(ref.items())

    def test_buffered_lookups_match_reference(self):
        """Lookups on a heavily buffered tree must account for pending ops."""
        cfg = Config(index_b=4, data_b=4, op_buf_size=500)
        tree = new_tree(cfg)
        ref = {}
        # Build tree large enough to have index nodes
        for i in range(20):
            tree = hitchhiker.insert(tree, i, i)
            ref[i] = i
        # Now add many more ops that should stay buffered
        for i in range(20, 200):
            tree = hitchhiker.insert(tree, i, i * 3)
            ref[i] = i * 3
        # Delete some
        for i in range(50, 100):
            tree = hitchhiker.delete(tree, i)
            ref.pop(i, None)

        # Verify buffered ops are present
        assert count_buffered_ops(tree) > 0, "Expected pending buffered ops"

        # Verify every lookup matches reference
        for k in range(200):
            assert hitchhiker.lookup(tree, k) == ref.get(k), f"Mismatch at key {k}"


# ---------------------------------------------------------------------------
# Test: Redis persistence
# ---------------------------------------------------------------------------

class TestRedisPersistence:
    @pytest.fixture(autouse=True)
    def setup_redis(self):
        """Ensure Redis is available and clean before each test."""
        if redis_lib is None:
            pytest.fail("redis package not installed — run: pip3 install redis")
        self.r = redis_lib.Redis(host="localhost", port=6379)
        try:
            self.r.ping()
        except Exception:
            pytest.fail("Redis server not reachable at localhost:6379")
        self.r.flushdb()
        yield
        self.r.flushdb()

    def test_save_and_load_basic(self):
        """Basic round-trip: insert data, save, load, verify."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=10)
        tree = new_tree(cfg)
        for i in range(50):
            tree = hitchhiker.insert(tree, i, i * 10)

        hitchhiker.save_tree(tree, "test_basic")
        loaded = hitchhiker.load_tree("test_basic")

        for i in range(50):
            assert hitchhiker.lookup(loaded, i) == i * 10, f"Key {i} wrong after load"

        items = list(hitchhiker.forward_iter(loaded, 0))
        assert len(items) == 50
        assert items[0] == (0, 0)
        assert items[-1] == (49, 490)

    def test_save_preserves_buffered_ops(self):
        """Save/load must preserve pending operations in buffers."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=50)
        tree = new_tree(cfg)
        for i in range(30):
            tree = hitchhiker.insert(tree, i, i)

        hitchhiker.save_tree(tree, "test_buffered")
        loaded = hitchhiker.load_tree("test_buffered")

        for i in range(30):
            assert hitchhiker.lookup(loaded, i) == i, f"Key {i} lost after save/load"

        items = list(hitchhiker.forward_iter(loaded, 0))
        assert len(items) == 30

    def test_multiple_named_trees(self):
        """Different trees saved under different names are independent."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=5)
        tree1 = new_tree(cfg)
        tree2 = new_tree(cfg)

        for i in range(20):
            tree1 = hitchhiker.insert(tree1, i, "tree1")
            tree2 = hitchhiker.insert(tree2, i, "tree2")

        hitchhiker.save_tree(tree1, "test_multi_1")
        hitchhiker.save_tree(tree2, "test_multi_2")

        loaded1 = hitchhiker.load_tree("test_multi_1")
        loaded2 = hitchhiker.load_tree("test_multi_2")

        for i in range(20):
            assert hitchhiker.lookup(loaded1, i) == "tree1"
            assert hitchhiker.lookup(loaded2, i) == "tree2"

    def test_overwrite_save(self):
        """Saving under the same name overwrites previous data."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=5)
        tree = new_tree(cfg)
        for i in range(10):
            tree = hitchhiker.insert(tree, i, "v1")
        hitchhiker.save_tree(tree, "test_overwrite")

        tree2 = new_tree(cfg)
        for i in range(10):
            tree2 = hitchhiker.insert(tree2, i, "v2")
        hitchhiker.save_tree(tree2, "test_overwrite")

        loaded = hitchhiker.load_tree("test_overwrite")
        for i in range(10):
            assert hitchhiker.lookup(loaded, i) == "v2"

    def test_load_nonexistent_raises(self):
        """Loading a nonexistent tree must raise an exception."""
        with pytest.raises(Exception):
            hitchhiker.load_tree("test_nonexistent_xyz_42")

    def test_persistence_with_deletes(self):
        """Trees with deletions should persist and load correctly."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=5)
        tree = new_tree(cfg)
        for i in range(30):
            tree = hitchhiker.insert(tree, i, i)
        for i in range(0, 30, 2):
            tree = hitchhiker.delete(tree, i)

        hitchhiker.save_tree(tree, "test_deletes")
        loaded = hitchhiker.load_tree("test_deletes")

        for i in range(30):
            expected = i if i % 2 == 1 else None
            assert hitchhiker.lookup(loaded, i) == expected, (
                f"Key {i}: expected {expected}, got {hitchhiker.lookup(loaded, i)}"
            )

    def test_loaded_tree_supports_further_mutations(self):
        """A loaded tree must support further inserts/deletes/lookups."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=5)
        tree = new_tree(cfg)
        for i in range(20):
            tree = hitchhiker.insert(tree, i, i)

        hitchhiker.save_tree(tree, "test_mutations")
        loaded = hitchhiker.load_tree("test_mutations")

        # Mutate the loaded tree
        for i in range(20, 40):
            loaded = hitchhiker.insert(loaded, i, i * 2)
        for i in range(5, 15):
            loaded = hitchhiker.delete(loaded, i)

        # Verify correctness
        for i in range(0, 5):
            assert hitchhiker.lookup(loaded, i) == i
        for i in range(5, 15):
            assert hitchhiker.lookup(loaded, i) is None
        for i in range(15, 20):
            assert hitchhiker.lookup(loaded, i) == i
        for i in range(20, 40):
            assert hitchhiker.lookup(loaded, i) == i * 2
