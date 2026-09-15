"""
Tests for left-right concurrent multi-value map.

Verifies correctness of the left-right concurrency pattern implementation
including snapshot isolation, epoch tracking, oplog management, and
concurrent safety.
"""

import sys
import threading
import time

sys.path.insert(0, "/app")

import pytest
from left_right_map import LeftRightMap, ReadHandle, ReadGuard, WriteHandle


# ---------------------------------------------------------------------------
# Basic CRUD operations
# ---------------------------------------------------------------------------

class TestBasicOperations:
    def test_create_returns_handles(self):
        w, r = LeftRightMap.new()
        assert isinstance(w, WriteHandle)
        assert isinstance(r, ReadHandle)

    def test_empty_map(self):
        w, r = LeftRightMap.new()
        w.publish()
        assert r.len() == 0
        assert r.get("x") is None
        assert r.contains_key("x") is False
        assert r.keys() == []

    def test_insert_and_get(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        assert r.get("a") == [1]

    def test_multi_value_insert(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("a", 2)
        w.insert("a", 3)
        w.publish()
        assert sorted(r.get("a")) == [1, 2, 3]

    def test_multi_key(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("b", 2)
        w.insert("c", 3)
        w.publish()
        assert r.get("a") == [1]
        assert r.get("b") == [2]
        assert r.get("c") == [3]
        assert r.len() == 3
        assert sorted(r.keys()) == ["a", "b", "c"]

    def test_remove_value(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("a", 2)
        w.insert("a", 3)
        w.publish()
        assert sorted(r.get("a")) == [1, 2, 3]
        w.remove_value("a", 2)
        w.publish()
        assert sorted(r.get("a")) == [1, 3]

    def test_remove_value_last(self):
        """Removing the last value for a key should remove the key entirely."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        w.remove_value("a", 1)
        w.publish()
        assert r.get("a") is None
        assert not r.contains_key("a")

    def test_remove_entry(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("a", 2)
        w.insert("b", 3)
        w.publish()
        w.remove_entry("a")
        w.publish()
        assert r.get("a") is None
        assert r.get("b") == [3]
        assert r.len() == 1

    def test_clear(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("b", 2)
        w.insert("c", 3)
        w.publish()
        assert r.len() == 3
        w.clear()
        w.publish()
        assert r.len() == 0
        assert r.get("a") is None

    def test_contains_key(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        assert r.contains_key("a")
        assert not r.contains_key("b")

    def test_remove_nonexistent_value(self):
        """Removing a value that doesn't exist should be a no-op."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        w.remove_value("a", 999)
        w.publish()
        assert r.get("a") == [1]

    def test_remove_nonexistent_key(self):
        """Removing an entry for a nonexistent key should be a no-op."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        w.remove_entry("zzz")
        w.publish()
        assert r.get("a") == [1]


# ---------------------------------------------------------------------------
# Publish semantics
# ---------------------------------------------------------------------------

class TestPublishSemantics:
    def test_unpublished_writes_invisible(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        # No publish yet -- reader must not see the write
        assert r.get("a") is None
        w.publish()
        assert r.get("a") == [1]

    def test_multiple_publishes(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        assert r.get("a") == [1]

        w.insert("a", 2)
        w.publish()
        assert sorted(r.get("a")) == [1, 2]

        w.insert("b", 10)
        w.publish()
        assert sorted(r.get("a")) == [1, 2]
        assert r.get("b") == [10]

    def test_has_pending(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        assert not w.has_pending()
        w.insert("b", 2)
        assert w.has_pending()
        w.publish()
        assert not w.has_pending()

    def test_empty_publish(self):
        """Publishing with no pending operations should be safe."""
        w, r = LeftRightMap.new()
        w.publish()
        w.publish()
        w.publish()
        assert r.len() == 0

    def test_batch_atomicity(self):
        """Multiple operations before a single publish appear atomically."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        assert r.get("a") == [1]

        # Batch: remove old + add new
        w.remove_entry("a")
        w.insert("b", 2)
        # Before publish, reader sees old state
        assert r.get("a") == [1]
        assert r.get("b") is None
        w.publish()
        # After publish, reader sees new state
        assert r.get("a") is None
        assert r.get("b") == [2]


# ---------------------------------------------------------------------------
# First-publish optimization & oplog correctness
# ---------------------------------------------------------------------------

class TestOplogCorrectness:
    def test_first_publish_optimization(self):
        """Operations before first publish bypass the oplog."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("b", 2)
        w.publish()
        assert r.get("a") == [1]
        assert r.get("b") == [2]
        # Now oplog path
        w.insert("c", 3)
        w.publish()
        assert r.get("a") == [1]
        assert r.get("b") == [2]
        assert r.get("c") == [3]

    def test_insert_not_doubled(self):
        """Each insert must add exactly one value, not duplicated across copies."""
        w, r = LeftRightMap.new()
        w.insert("k", 1)
        w.publish()
        assert r.get("k") == [1]

        w.insert("k", 2)
        w.publish()
        assert sorted(r.get("k")) == [1, 2]

        w.insert("k", 3)
        w.publish()
        assert sorted(r.get("k")) == [1, 2, 3]

    def test_remove_not_doubled(self):
        """Each remove_value must remove exactly one occurrence."""
        w, r = LeftRightMap.new()
        w.insert("k", 1)
        w.insert("k", 2)
        w.insert("k", 3)
        w.publish()

        w.remove_value("k", 2)
        w.publish()
        assert sorted(r.get("k")) == [1, 3]

        w.remove_value("k", 1)
        w.publish()
        assert r.get("k") == [3]

    def test_many_publish_cycles(self):
        """Data stays correct across many publish cycles."""
        w, r = LeftRightMap.new()
        for i in range(50):
            w.insert("key", i)
            w.publish()
        vals = r.get("key")
        assert sorted(vals) == list(range(50))

    def test_interleaved_insert_remove(self):
        """Mixed insert and remove across multiple cycles."""
        w, r = LeftRightMap.new()
        # Cycle 1: insert 0..9
        for i in range(10):
            w.insert("k", i)
        w.publish()
        assert sorted(r.get("k")) == list(range(10))

        # Cycle 2: remove evens
        for i in range(0, 10, 2):
            w.remove_value("k", i)
        w.publish()
        assert sorted(r.get("k")) == [1, 3, 5, 7, 9]

        # Cycle 3: add new values
        for i in range(10, 15):
            w.insert("k", i)
        w.publish()
        assert sorted(r.get("k")) == [1, 3, 5, 7, 9, 10, 11, 12, 13, 14]

    def test_multiple_ops_before_first_publish(self):
        """Multiple operations, including removes, before first publish."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.insert("a", 2)
        w.remove_value("a", 1)
        w.insert("b", 10)
        w.publish()
        assert r.get("a") == [2]
        assert r.get("b") == [10]


# ---------------------------------------------------------------------------
# Snapshot isolation
# ---------------------------------------------------------------------------

class TestSnapshotIsolation:
    def test_guard_sees_frozen_snapshot(self):
        """A ReadGuard sees a snapshot that doesn't change across publishes."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()

        guard = r.enter()
        assert guard is not None
        assert guard.get("a") == [1]

        # Writer publishes new data while guard is held
        w.insert("a", 2)
        w.publish()

        # Guard still sees the old snapshot
        assert guard.get("a") == [1]
        guard.release()

        # New read sees the updated data
        assert sorted(r.get("a")) == [1, 2]

    def test_guard_context_manager(self):
        w, r = LeftRightMap.new()
        w.insert("x", 42)
        w.publish()

        with r.enter() as guard:
            assert guard.get("x") == [42]
            assert guard.len() == 1
            assert guard.keys() == ["x"]
            assert guard.contains_key("x")

    def test_snapshot_isolation_threaded(self):
        """Snapshot isolation across threads."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()

        entered = threading.Event()
        can_release = threading.Event()
        result = {}

        def reader_fn():
            r2 = r.clone()
            guard = r2.enter()
            result["before"] = guard.get("a")
            entered.set()
            can_release.wait(timeout=5)
            result["still"] = guard.get("a")
            guard.release()
            result["after"] = r2.get("a")

        t = threading.Thread(target=reader_fn)
        t.start()

        entered.wait(timeout=5)

        # Writer publishes while reader holds guard
        w.insert("a", 2)
        w.publish()

        can_release.set()
        t.join(timeout=10)

        assert result["before"] == [1]
        assert result["still"] == [1]  # snapshot unchanged
        assert sorted(result["after"]) == [1, 2]

    def test_get_returns_copy(self):
        """get() must return a copy, not a reference to internal state."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()

        vals = r.get("a")
        vals.append(999)  # mutate the returned list

        # Internal state must not be affected
        assert r.get("a") == [1]


# ---------------------------------------------------------------------------
# Writer lifecycle
# ---------------------------------------------------------------------------

class TestWriterLifecycle:
    def test_writer_destroy(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()
        assert r.get("a") == [1]

        w.destroy()
        assert r.was_dropped()
        assert r.enter() is None
        assert r.get("a") is None
        assert r.len() == 0

    def test_clone_reader(self):
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()

        r2 = r.clone()
        assert r2.get("a") == [1]

        w.insert("b", 2)
        w.publish()

        assert sorted(r.keys()) == ["a", "b"]
        assert sorted(r2.keys()) == ["a", "b"]

    def test_guard_survives_destroy(self):
        """Existing guards remain valid after destroy."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()

        guard = r.enter()
        assert guard.get("a") == [1]

        w.destroy()

        # Guard still works (references old copy)
        assert guard.get("a") == [1]
        guard.release()


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_readers(self):
        """Multiple reader threads operate without interfering."""
        w, r = LeftRightMap.new()
        for i in range(100):
            w.insert("key", i)
        w.publish()

        errors = []

        def reader_fn(r_clone, tid):
            try:
                for _ in range(500):
                    vals = r_clone.get("key")
                    assert vals is not None, f"thread {tid}: got None"
                    assert len(vals) == 100, f"thread {tid}: len={len(vals)}"
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(8):
            t = threading.Thread(target=reader_fn, args=(r.clone(), i))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"Errors: {errors}"

    def test_concurrent_reader_writer(self):
        """Writer and readers operate concurrently with consistent snapshots."""
        w, r = LeftRightMap.new()
        stop = threading.Event()
        errors = []

        def reader_fn(r_clone, tid):
            try:
                while not stop.is_set():
                    vals = r_clone.get("k")
                    if vals is not None:
                        # Values should be a contiguous prefix [0, 1, ..., n-1]
                        expected = list(range(len(vals)))
                        assert sorted(vals) == expected, (
                            f"thread {tid}: got {sorted(vals)} expected {expected}"
                        )
                    time.sleep(0.0001)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(4):
            t = threading.Thread(target=reader_fn, args=(r.clone(), i))
            threads.append(t)
            t.start()

        for i in range(100):
            w.insert("k", i)
            w.publish()
            time.sleep(0.0001)

        stop.set()
        for t in threads:
            t.join(timeout=30)

        assert errors == [], f"Errors: {errors}"
        assert sorted(r.get("k")) == list(range(100))

    def test_publish_waits_for_guard(self):
        """Writer publish blocks until a guard on the stale copy is released."""
        w, r = LeftRightMap.new()
        w.insert("a", 1)
        w.publish()  # swap 1

        w.insert("a", 2)
        w.publish()  # swap 2: now read_copy has [1,2]

        # Reader enters -- guard is on the current read_copy
        r2 = r.clone()
        guard = r2.enter()
        assert sorted(guard.get("a")) == [1, 2]

        # swap 3: the guard's copy becomes the new write_copy
        w.insert("a", 3)
        w.publish()  # should succeed (guard entered after swap 2's epoch recording)

        # NOW last_epochs has r2's odd epoch captured.
        # The next publish MUST block because r2 hasn't released.
        publish_done = threading.Event()

        def writer_fn():
            w.insert("a", 4)
            w.publish()  # should block until guard is released
            publish_done.set()

        t = threading.Thread(target=writer_fn)
        t.start()

        time.sleep(0.3)
        assert not publish_done.is_set(), "publish should be blocked"

        guard.release()

        t.join(timeout=10)
        assert publish_done.is_set(), "publish should complete after guard release"

        assert sorted(r.get("a")) == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Stress test
# ---------------------------------------------------------------------------

class TestStress:
    def test_stress_mixed_operations(self):
        """Stress test with many mixed operations and publish cycles."""
        w, r = LeftRightMap.new()

        # Phase 1: bulk insert
        for i in range(200):
            w.insert(f"key_{i % 20}", i)
        w.publish()

        assert r.len() == 20
        for k_idx in range(20):
            vals = r.get(f"key_{k_idx}")
            assert vals is not None
            assert len(vals) == 10  # 200 / 20

        # Phase 2: selective removes
        for i in range(0, 200, 3):
            w.remove_value(f"key_{i % 20}", i)
        w.publish()

        # Phase 3: clear and rebuild
        w.clear()
        w.publish()
        assert r.len() == 0

        for i in range(50):
            w.insert("fresh", i)
        w.publish()
        assert sorted(r.get("fresh")) == list(range(50))

    def test_rapid_publish_cycles(self):
        """Many rapid publish cycles with single-item additions."""
        w, r = LeftRightMap.new()
        for i in range(500):
            w.insert("x", i)
            w.publish()

        vals = r.get("x")
        assert len(vals) == 500
        assert sorted(vals) == list(range(500))
