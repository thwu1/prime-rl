"""
Tests for the hitchhiker tree messaging layer and Redis persistence.

Verifies that the messaging layer correctly buffers operations and
produces results identical to a plain Python dict used as reference.
Also verifies Redis persistence of complete tree state.
"""


import sys
import random
import subprocess

sys.path.insert(0, "/app")

import redis
from hitchhiker.core import Config, new_tree, DataNode, IndexNode
from hitchhiker import messaging


# ---- Basic operations ------------------------------------------------------

class TestBasicOperations:
    def test_insert_single(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        tree = messaging.insert(tree, 1, "a")
        assert messaging.lookup(tree, 1) == "a"

    def test_insert_multiple(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(10):
            tree = messaging.insert(tree, i, str(i))
        for i in range(10):
            assert messaging.lookup(tree, i) == str(i)

    def test_insert_overwrite(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        tree = messaging.insert(tree, 1, "a")
        tree = messaging.insert(tree, 1, "b")
        assert messaging.lookup(tree, 1) == "b"

    def test_lookup_missing(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        tree = messaging.insert(tree, 1, "a")
        assert messaging.lookup(tree, 2) is None
        assert messaging.lookup(tree, 2, "default") == "default"

    def test_delete_basic(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(10):
            tree = messaging.insert(tree, i, str(i))
        tree = messaging.delete(tree, 5)
        assert messaging.lookup(tree, 5) is None
        for i in range(10):
            if i != 5:
                assert messaging.lookup(tree, i) == str(i)

    def test_delete_nonexistent(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        tree = messaging.insert(tree, 1, "a")
        tree = messaging.delete(tree, 999)
        assert messaging.lookup(tree, 1) == "a"

    def test_insert_delete_reinsert(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        tree = messaging.insert(tree, 1, "first")
        tree = messaging.delete(tree, 1)
        assert messaging.lookup(tree, 1) is None
        tree = messaging.insert(tree, 1, "second")
        assert messaging.lookup(tree, 1) == "second"

    def test_empty_tree_operations(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        assert messaging.lookup(tree, 42) is None
        tree = messaging.delete(tree, 42)
        assert messaging.lookup(tree, 42) is None


# ---- Bulk operations -------------------------------------------------------

class TestBulkOperations:
    def test_sequential_insert(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        n = 200
        for i in range(n):
            tree = messaging.insert(tree, i, i * 10)
        for i in range(n):
            assert messaging.lookup(tree, i) == i * 10, f"key {i}"

    def test_reverse_insert(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        n = 200
        for i in range(n - 1, -1, -1):
            tree = messaging.insert(tree, i, i * 10)
        for i in range(n):
            assert messaging.lookup(tree, i) == i * 10, f"key {i}"

    def test_random_insert(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        rng = random.Random(42)
        keys = list(range(500))
        rng.shuffle(keys)
        for k in keys:
            tree = messaging.insert(tree, k, k * 7)
        for k in keys:
            assert messaging.lookup(tree, k) == k * 7, f"key {k}"

    def test_bulk_delete(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        n = 200
        for i in range(n):
            tree = messaging.insert(tree, i, i)
        for i in range(0, n, 2):
            tree = messaging.delete(tree, i)
        for i in range(n):
            if i % 2 == 0:
                assert messaging.lookup(tree, i) is None, f"key {i} deleted"
            else:
                assert messaging.lookup(tree, i) == i, f"key {i} exists"

    def test_delete_all(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        n = 100
        for i in range(n):
            tree = messaging.insert(tree, i, i)
        for i in range(n):
            tree = messaging.delete(tree, i)
        for i in range(n):
            assert messaging.lookup(tree, i) is None


# ---- Mixed operations (reference comparison) -------------------------------

class TestMixedOperations:
    def test_random_mixed(self):
        """Random inserts, deletes, lookups compared with a dict."""
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(123)

        for _ in range(2000):
            op = rng.choice(["insert", "insert", "insert", "delete", "lookup"])
            key = rng.randint(0, 200)

            if op == "insert":
                val = rng.randint(0, 10000)
                tree = messaging.insert(tree, key, val)
                ref[key] = val
            elif op == "delete":
                tree = messaging.delete(tree, key)
                ref.pop(key, None)
            else:
                assert messaging.lookup(tree, key) == ref.get(key), (
                    f"key {key}")

        for key in range(201):
            assert messaging.lookup(tree, key) == ref.get(key), (
                f"final key {key}")

    def test_overwrite_many_times(self):
        """Repeatedly update the same key; latest value must win."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        for i in range(30):
            tree = messaging.insert(tree, i, i)
        for v in range(100):
            tree = messaging.insert(tree, 15, f"v{v}")
        assert messaging.lookup(tree, 15) == "v99"

    def test_interleaved_read_write(self):
        """Reads interleaved with writes must always be consistent."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(999)

        for step in range(1000):
            k = rng.randint(0, 50)
            if rng.random() < 0.6:
                v = step
                tree = messaging.insert(tree, k, v)
                ref[k] = v
            else:
                tree = messaging.delete(tree, k)
                ref.pop(k, None)
            # verify a random key on every step
            qk = rng.randint(0, 50)
            assert messaging.lookup(tree, qk) == ref.get(qk), (
                f"step {step} key {qk}")


# ---- Forward iterator ------------------------------------------------------

class TestForwardIterator:
    def test_basic_iteration(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(20):
            tree = messaging.insert(tree, i, i * 10)
        result = list(messaging.forward_iterator(tree, 0))
        assert len(result) == 20
        for i, (k, v) in enumerate(result):
            assert k == i and v == i * 10

    def test_iteration_from_middle(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(20):
            tree = messaging.insert(tree, i, i * 10)
        result = list(messaging.forward_iterator(tree, 10))
        assert len(result) == 10
        for i, (k, v) in enumerate(result):
            assert k == i + 10 and v == (i + 10) * 10

    def test_iteration_with_deletes(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(20):
            tree = messaging.insert(tree, i, i)
        for i in range(0, 20, 2):
            tree = messaging.delete(tree, i)
        result = list(messaging.forward_iterator(tree, 0))
        expected = [(i, i) for i in range(1, 20, 2)]
        assert result == expected

    def test_iteration_empty(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        assert list(messaging.forward_iterator(tree, 0)) == []

    def test_iteration_sorted_order(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        rng = random.Random(99)
        keys = list(range(300))
        rng.shuffle(keys)
        for k in keys:
            tree = messaging.insert(tree, k, k)
        result = list(messaging.forward_iterator(tree, 100))
        expected = [(k, k) for k in range(100, 300)]
        assert result == expected

    def test_iteration_matches_dict(self):
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(77)
        for _ in range(500):
            k = rng.randint(0, 100)
            if rng.random() < 0.7:
                v = rng.randint(0, 10000)
                tree = messaging.insert(tree, k, v)
                ref[k] = v
            else:
                tree = messaging.delete(tree, k)
                ref.pop(k, None)
        result = dict(messaging.forward_iterator(tree, 0))
        assert result == ref


# ---- Different configurations ----------------------------------------------

class TestDifferentConfigs:
    def test_tiny_buffer(self):
        """op_buf_size=1 forces immediate overflow on every buffered write."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=1)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(55)
        for _ in range(500):
            k = rng.randint(0, 100)
            v = rng.randint(0, 1000)
            tree = messaging.insert(tree, k, v)
            ref[k] = v
        for k, v in ref.items():
            assert messaging.lookup(tree, k) == v, f"key {k}"

    def test_large_buffer(self):
        cfg = Config(index_b=5, data_b=5, op_buf_size=8)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(66)
        for _ in range(1000):
            k = rng.randint(0, 300)
            if rng.random() < 0.65:
                v = rng.randint(0, 10000)
                tree = messaging.insert(tree, k, v)
                ref[k] = v
            else:
                tree = messaging.delete(tree, k)
                ref.pop(k, None)
        for k in range(301):
            assert messaging.lookup(tree, k) == ref.get(k), f"key {k}"


# ---- Structural invariants -------------------------------------------------

class TestStructuralInvariants:
    def _check(self, node, is_root=True):
        if node.is_data():
            assert not node.overflow(), (
                f"DataNode overflow: {len(node.children)}")
            return
        assert len(node.children) >= 2, "IndexNode needs >=2 children"
        if not is_root:
            assert not node.underflow(), (
                f"IndexNode underflow: {len(node.children)}")
        assert not node.overflow(), (
            f"IndexNode overflow: {len(node.children)}")
        sep = node.separator_keys()
        for j in range(len(sep) - 1):
            assert sep[j] <= sep[j + 1], f"separator order: {sep}"
        for child in node.children:
            self._check(child, is_root=False)

    def test_after_inserts(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(300):
            tree = messaging.insert(tree, i, i)
        self._check(tree)

    def test_after_mixed(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        rng = random.Random(88)
        for _ in range(500):
            if rng.random() < 0.7:
                tree = messaging.insert(tree, rng.randint(0, 100),
                                        rng.randint(0, 999))
            else:
                tree = messaging.delete(tree, rng.randint(0, 100))
        self._check(tree)


# ---- Stress test -----------------------------------------------------------

class TestStress:
    def test_large_scale_correctness(self):
        cfg = Config(index_b=4, data_b=4, op_buf_size=4)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(2024)

        for _ in range(5000):
            op = rng.choice(["ins", "ins", "ins", "del"])
            k = rng.randint(0, 500)
            if op == "ins":
                v = rng.randint(0, 100000)
                tree = messaging.insert(tree, k, v)
                ref[k] = v
            else:
                tree = messaging.delete(tree, k)
                ref.pop(k, None)

        for k in range(501):
            assert messaging.lookup(tree, k) == ref.get(k), (
                f"stress key {k}")

        result = dict(messaging.forward_iterator(tree, 0))
        assert result == ref, "iterator mismatch"


# ---- Redis persistence -----------------------------------------------------

class TestRedisPersistence:
    def setup_method(self):
        self.r = redis.Redis(host='localhost', port=6379, db=1)
        self.r.flushdb()

    def teardown_method(self):
        self.r.flushdb()
        self.r.close()

    def test_save_and_load_basic(self):
        """Save a tree to Redis and load it back; all data must be intact."""
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(50):
            tree = messaging.insert(tree, i, i * 10)

        root_key = messaging.save_tree(tree, self.r)
        assert isinstance(root_key, str) and len(root_key) > 0

        loaded = messaging.load_tree(root_key, self.r)
        for i in range(50):
            assert messaging.lookup(loaded, i) == i * 10, f"key {i}"

    def test_persistence_preserves_buffers(self):
        """Tree with pending ops in buffers must roundtrip correctly."""
        cfg = Config(index_b=4, data_b=4, op_buf_size=10)
        tree = new_tree(cfg)
        for i in range(50):
            tree = messaging.insert(tree, i, i)

        root_key = messaging.save_tree(tree, self.r)
        loaded = messaging.load_tree(root_key, self.r)
        for i in range(50):
            assert messaging.lookup(loaded, i) == i, f"key {i}"

    def test_operations_after_load(self):
        """Loaded tree must support further insert/delete/lookup."""
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        ref = {}
        for i in range(30):
            tree = messaging.insert(tree, i, i)
            ref[i] = i

        root_key = messaging.save_tree(tree, self.r)
        loaded = messaging.load_tree(root_key, self.r)

        for i in range(30, 60):
            loaded = messaging.insert(loaded, i, i * 2)
            ref[i] = i * 2
        for i in range(0, 30, 3):
            loaded = messaging.delete(loaded, i)
            ref.pop(i, None)

        for k, v in ref.items():
            assert messaging.lookup(loaded, k) == v, f"key {k}"

    def test_save_load_save(self):
        """Multiple roundtrips must maintain correctness."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(42)

        for _ in range(100):
            k = rng.randint(0, 50)
            v = rng.randint(0, 1000)
            tree = messaging.insert(tree, k, v)
            ref[k] = v

        key1 = messaging.save_tree(tree, self.r)
        tree = messaging.load_tree(key1, self.r)

        for _ in range(100):
            k = rng.randint(0, 50)
            if rng.random() < 0.5:
                v = rng.randint(0, 1000)
                tree = messaging.insert(tree, k, v)
                ref[k] = v
            else:
                tree = messaging.delete(tree, k)
                ref.pop(k, None)

        self.r.flushdb()
        key2 = messaging.save_tree(tree, self.r)
        tree = messaging.load_tree(key2, self.r)

        for k in range(51):
            assert messaging.lookup(tree, k) == ref.get(k), f"key {k}"

    def test_iterator_after_load(self):
        """Forward iteration must work on a loaded tree."""
        cfg = Config(index_b=4, data_b=4, op_buf_size=3)
        tree = new_tree(cfg)
        for i in range(100):
            tree = messaging.insert(tree, i, i)

        key = messaging.save_tree(tree, self.r)
        loaded = messaging.load_tree(key, self.r)

        result = list(messaging.forward_iterator(loaded, 50))
        expected = [(i, i) for i in range(50, 100)]
        assert result == expected

    def test_node_level_storage(self):
        """Each tree node must be stored as a separate Redis entry."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        for i in range(50):
            tree = messaging.insert(tree, i, i)

        keys_before = self.r.dbsize()
        root_key = messaging.save_tree(tree, self.r)
        keys_after = self.r.dbsize()

        new_keys = keys_after - keys_before
        assert new_keys >= 5, (
            f"Tree with 50 items should produce multiple Redis keys "
            f"(got {new_keys}). Each tree node must be stored separately."
        )

    def test_cross_process_persistence(self):
        """Data written by one process must be readable by another."""
        write_script = '''
import sys
sys.path.insert(0, "/app")
import redis
from hitchhiker.core import Config, new_tree
from hitchhiker import messaging

r = redis.Redis(host='localhost', port=6379, db=1)
cfg = Config(index_b=4, data_b=4, op_buf_size=3)
tree = new_tree(cfg)
for i in range(200):
    tree = messaging.insert(tree, i, i * 7)
key = messaging.save_tree(tree, r)
print(key)
'''
        result = subprocess.run(
            ['python3', '-c', write_script],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Write subprocess failed: {result.stderr}")
        root_key = result.stdout.strip()
        assert len(root_key) > 0, "No root key returned from subprocess"

        loaded = messaging.load_tree(root_key, self.r)
        for i in range(200):
            assert messaging.lookup(loaded, i) == i * 7, f"key {i}"

    def test_mixed_ops_persistence(self):
        """Tree with interleaved inserts/deletes persists correctly."""
        cfg = Config(index_b=3, data_b=3, op_buf_size=2)
        tree = new_tree(cfg)
        ref = {}
        rng = random.Random(314)

        for _ in range(300):
            k = rng.randint(0, 80)
            if rng.random() < 0.65:
                v = rng.randint(0, 5000)
                tree = messaging.insert(tree, k, v)
                ref[k] = v
            else:
                tree = messaging.delete(tree, k)
                ref.pop(k, None)

        root_key = messaging.save_tree(tree, self.r)
        loaded = messaging.load_tree(root_key, self.r)

        for k in range(81):
            assert messaging.lookup(loaded, k) == ref.get(k), f"key {k}"

        result = dict(messaging.forward_iterator(loaded, 0))
        assert result == ref
