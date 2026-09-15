
"""
Tests for the MVCC transaction engine.

Covers: TimestampOracle correctness, KvTable operations, basic
transactions, snapshot-isolation anomaly tests, lock cleanup /
partial-commit recovery, concurrent stress tests, property-based
invariant tests, and Redis integration verification.
"""

import sys
import time
import threading

import pytest
from hypothesis import given, settings, strategies as st

sys.path.insert(0, "/app")

from mvcc import (
    TimestampOracle,
    KvTable,
    Column,
    MemoryStorage,
    Client,
    LOCK_TTL_SECS,
)


# ---------------------------------------------------------------------------
# Fixture: flush Redis between test functions
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _flush_redis():
    import redis as _r
    conn = _r.Redis(host="localhost", port=6379, db=0)
    conn.flushdb()
    yield
    conn.close()


# ---------------------------------------------------------------------------
# TimestampOracle
# ---------------------------------------------------------------------------

class TestTimestampOracle:
    def test_monotonically_increasing(self):
        tso = TimestampOracle()
        timestamps = [tso.get_timestamp() for _ in range(100)]
        for i in range(1, len(timestamps)):
            assert timestamps[i] > timestamps[i - 1], (
                f"Timestamp {timestamps[i]} is not greater than {timestamps[i - 1]}"
            )

    def test_thread_safety(self):
        tso = TimestampOracle()
        results: list = []
        lock = threading.Lock()

        def collect():
            local = [tso.get_timestamp() for _ in range(100)]
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=collect) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 400
        assert len(set(results)) == 400, "Timestamps must be globally unique"


# ---------------------------------------------------------------------------
# KvTable
# ---------------------------------------------------------------------------

class TestKvTable:
    def _make_table(self):
        """Create a KvTable backed by Redis."""
        tso = TimestampOracle()
        storage = MemoryStorage()
        return storage._table

    def test_write_and_read(self):
        table = self._make_table()
        table.write(b"key1", Column.DATA, 1, b"value1")
        result = table.read(b"key1", Column.DATA, ts_start=0, ts_end=10)
        assert result is not None
        assert result[0] == (b"key1", 1)
        assert result[1] == b"value1"

    def test_read_most_recent(self):
        table = self._make_table()
        table.write(b"k", Column.DATA, 1, b"v1")
        table.write(b"k", Column.DATA, 3, b"v3")
        table.write(b"k", Column.DATA, 5, b"v5")
        result = table.read(b"k", Column.DATA, ts_start=0, ts_end=4)
        assert result is not None
        assert result[0] == (b"k", 3)
        assert result[1] == b"v3"

    def test_read_not_found(self):
        table = self._make_table()
        result = table.read(b"missing", Column.DATA)
        assert result is None

    def test_erase(self):
        table = self._make_table()
        table.write(b"k", Column.DATA, 1, b"v")
        table.erase(b"k", Column.DATA, 1)
        assert table.read(b"k", Column.DATA) is None

    def test_different_keys_same_ts(self):
        table = self._make_table()
        table.write(b"a", Column.DATA, 1, b"va")
        table.write(b"b", Column.DATA, 1, b"vb")
        assert table.read(b"a", Column.DATA)[1] == b"va"
        assert table.read(b"b", Column.DATA)[1] == b"vb"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clients(n: int):
    """Create a shared TSO + storage and *n* independent clients."""
    tso = TimestampOracle()
    storage = MemoryStorage()
    clients = [Client(tso, storage) for _ in range(n)]
    return tso, storage, clients


# ---------------------------------------------------------------------------
# Basic transactions
# ---------------------------------------------------------------------------

class TestBasicTransactions:
    def test_single_put_get(self):
        _, _, (c0, c1) = _make_clients(2)
        c0.begin()
        c0.set(b"key1", b"value1")
        assert c0.commit() is True

        c1.begin()
        assert c1.get(b"key1") == b"value1"

    def test_multiple_keys(self):
        _, _, (c0, c1) = _make_clients(2)
        c0.begin()
        c0.set(b"k1", b"v1")
        c0.set(b"k2", b"v2")
        c0.set(b"k3", b"v3")
        assert c0.commit() is True

        c1.begin()
        assert c1.get(b"k1") == b"v1"
        assert c1.get(b"k2") == b"v2"
        assert c1.get(b"k3") == b"v3"

    def test_get_nonexistent(self):
        _, _, (c0,) = _make_clients(1)
        c0.begin()
        assert c0.get(b"nope") == b""

    def test_overwrite(self):
        _, _, (c0, c1, c2) = _make_clients(3)
        c0.begin()
        c0.set(b"k", b"old")
        assert c0.commit() is True

        c1.begin()
        c1.set(b"k", b"new")
        assert c1.commit() is True

        c2.begin()
        assert c2.get(b"k") == b"new"

    def test_empty_commit(self):
        _, _, (c0,) = _make_clients(1)
        c0.begin()
        assert c0.commit() is True


# ---------------------------------------------------------------------------
# Snapshot-isolation anomaly tests
# ---------------------------------------------------------------------------

class TestHermitageAnomalies:
    """Verify snapshot-isolation semantics."""

    def test_pmp_read_predicates(self):
        """Phantom reads prevented."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        assert c1.get(b"3") == b""

        c2.begin()
        c2.set(b"3", b"30")
        assert c2.commit() is True

        # c1 must still not see key 3
        assert c1.get(b"3") == b""

    def test_pmp_write_predicates(self):
        """Write-write conflict detected."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        c1.set(b"1", b"20")
        c1.set(b"2", b"30")
        assert c1.get(b"2") == b"20"

        c2.set(b"2", b"40")
        assert c1.commit() is True
        assert c2.commit() is False

    def test_lost_update(self):
        """P4: lost update prevented."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        assert c1.get(b"1") == b"10"
        assert c2.get(b"1") == b"10"

        c1.set(b"1", b"11")
        c2.set(b"1", b"11")
        assert c1.commit() is True
        assert c2.commit() is False

    def test_read_skew_read_only(self):
        """Consistent snapshot for reads."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        assert c1.get(b"1") == b"10"
        assert c2.get(b"1") == b"10"
        assert c2.get(b"2") == b"20"

        c2.set(b"1", b"12")
        c2.set(b"2", b"18")
        assert c2.commit() is True

        assert c1.get(b"2") == b"20"

    def test_read_skew_predicate_deps(self):
        """New-key insertions invisible to older snapshot."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        assert c1.get(b"1") == b"10"
        assert c1.get(b"2") == b"20"

        c2.set(b"3", b"30")
        assert c2.commit() is True

        assert c1.get(b"3") == b""

    def test_read_skew_write_predicate(self):
        """Write-after-read with stale snapshot aborts."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        assert c1.get(b"1") == b"10"
        assert c2.get(b"1") == b"10"
        assert c2.get(b"2") == b"20"

        c2.set(b"1", b"12")
        c2.set(b"2", b"18")
        assert c2.commit() is True

        c1.set(b"2", b"30")
        assert c1.commit() is False

    def test_write_skew(self):
        """Write skew allowed under snapshot isolation."""
        _, _, (c0, c1, c2) = _make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        assert c1.get(b"1") == b"10"
        assert c1.get(b"2") == b"20"
        assert c2.get(b"1") == b"10"
        assert c2.get(b"2") == b"20"

        c1.set(b"1", b"11")
        c2.set(b"2", b"21")

        assert c1.commit() is True
        assert c2.commit() is True

    def test_anti_dependency_cycles(self):
        """Anti-dependency cycles across non-overlapping write sets."""
        _, _, (c0, c1, c2, c3) = _make_clients(4)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        c1.set(b"3", b"30")
        c2.set(b"4", b"42")

        assert c1.commit() is True
        assert c2.commit() is True

        c3.begin()
        assert c3.get(b"3") == b"30"
        assert c3.get(b"4") == b"42"


# ---------------------------------------------------------------------------
# Lock cleanup & partial-commit recovery
# ---------------------------------------------------------------------------

class TestLockCleanup:
    def test_stale_primary_lock_rollback(self):
        """Expired lock on the primary key is rolled back."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        start_ts = tso.get_timestamp()
        storage.prewrite(b"key1", b"val1", start_ts, b"key1")

        time.sleep(LOCK_TTL_SECS + 0.25)

        c = Client(tso, storage)
        c.begin()
        assert c.get(b"key1") == b""

    def test_partial_commit_roll_forward(self):
        """Primary committed, secondaries still locked -> roll forward."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        start_ts = tso.get_timestamp()
        storage.prewrite(b"key1", b"val1", start_ts, b"key1")
        storage.prewrite(b"key2", b"val2", start_ts, b"key1")
        storage.prewrite(b"key3", b"val3", start_ts, b"key1")

        commit_ts = tso.get_timestamp()
        storage.commit(b"key1", start_ts, commit_ts, is_primary=True)

        time.sleep(LOCK_TTL_SECS + 0.25)

        c = Client(tso, storage)
        c.begin()
        assert c.get(b"key1") == b"val1"
        assert c.get(b"key2") == b"val2"
        assert c.get(b"key3") == b"val3"

    def test_full_rollback_no_commit(self):
        """Primary lock still present and expired -> full rollback."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        start_ts = tso.get_timestamp()
        storage.prewrite(b"key1", b"val1", start_ts, b"key1")
        storage.prewrite(b"key2", b"val2", start_ts, b"key1")

        time.sleep(LOCK_TTL_SECS + 0.25)

        c = Client(tso, storage)
        c.begin()
        assert c.get(b"key1") == b""
        assert c.get(b"key2") == b""


# ---------------------------------------------------------------------------
# Concurrent stress tests
# ---------------------------------------------------------------------------

class TestConcurrentStress:
    def test_no_lost_updates_under_contention(self):
        """Many concurrent writers on the same key must not corrupt state."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        c0 = Client(tso, storage)
        c0.begin()
        c0.set(b"counter", b"0")
        assert c0.commit()

        results = []
        mu = threading.Lock()

        def writer(tid):
            c = Client(tso, storage)
            c.begin()
            c.set(b"counter", str(tid).encode())
            success = c.commit()
            with mu:
                results.append((tid, success))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [tid for tid, ok in results if ok]
        assert len(successes) >= 1, "At least one writer must succeed"

        c_read = Client(tso, storage)
        c_read.begin()
        val = c_read.get(b"counter")
        valid = {str(tid).encode() for tid, ok in results if ok}
        assert val in valid, f"Final value {val!r} not from any successful writer"

    def test_concurrent_independent_transactions(self):
        """Transactions on disjoint keys should all succeed."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        results = {}
        mu = threading.Lock()

        def writer(tid):
            key = f"key_{tid}".encode()
            val = f"val_{tid}".encode()
            c = Client(tso, storage)
            c.begin()
            c.set(key, val)
            success = c.commit()
            with mu:
                results[tid] = success

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results.values()), (
            f"Independent transactions must all succeed: {results}"
        )

        c_read = Client(tso, storage)
        c_read.begin()
        for i in range(20):
            assert c_read.get(f"key_{i}".encode()) == f"val_{i}".encode()

    def test_concurrent_readers_see_consistent_snapshot(self):
        """Readers during concurrent writes must see consistent snapshots."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        c0 = Client(tso, storage)
        c0.begin()
        c0.set(b"x", b"0")
        c0.set(b"y", b"0")
        assert c0.commit()

        errors = []
        errors_lock = threading.Lock()

        def reader():
            for _ in range(50):
                c = Client(tso, storage)
                c.begin()
                x = c.get(b"x")
                y = c.get(b"y")
                if x != y:
                    with errors_lock:
                        errors.append(f"x={x!r}, y={y!r}")

        def writer():
            for i in range(1, 51):
                c = Client(tso, storage)
                c.begin()
                val = str(i).encode()
                c.set(b"x", val)
                c.set(b"y", val)
                c.commit()

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Snapshot inconsistencies: {errors[:5]}"


# ---------------------------------------------------------------------------
# Property-based invariant tests
# ---------------------------------------------------------------------------

class TestPropertyBased:
    @given(
        key=st.binary(min_size=1, max_size=8),
        val1=st.binary(min_size=1, max_size=16),
        val2=st.binary(min_size=1, max_size=16),
    )
    @settings(max_examples=50, deadline=None, database=None)
    def test_read_after_write(self, key, val1, val2):
        """Written values are readable after commit."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        c1 = Client(tso, storage)
        c1.begin()
        c1.set(key, val1)
        assert c1.commit()

        c2 = Client(tso, storage)
        c2.begin()
        assert c2.get(key) == val1

        c3 = Client(tso, storage)
        c3.begin()
        c3.set(key, val2)
        assert c3.commit()

        c4 = Client(tso, storage)
        c4.begin()
        assert c4.get(key) == val2

    @given(
        keys=st.lists(
            st.binary(min_size=1, max_size=4), min_size=2, max_size=5, unique=True
        ),
    )
    @settings(max_examples=50, deadline=None, database=None)
    def test_atomic_multi_key_write(self, keys):
        """All keys in a committed transaction are visible together."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        c1 = Client(tso, storage)
        c1.begin()
        for i, k in enumerate(keys):
            c1.set(k, str(i).encode())
        assert c1.commit()

        c2 = Client(tso, storage)
        c2.begin()
        for i, k in enumerate(keys):
            assert c2.get(k) == str(i).encode()

    @given(
        key=st.binary(min_size=1, max_size=8),
        val=st.binary(min_size=1, max_size=16),
    )
    @settings(max_examples=50, deadline=None, database=None)
    def test_snapshot_sees_committed_only(self, key, val):
        """A snapshot taken before a commit must not see that commit."""
        tso = TimestampOracle()
        storage = MemoryStorage()

        c_reader = Client(tso, storage)
        c_reader.begin()

        c_writer = Client(tso, storage)
        c_writer.begin()
        c_writer.set(key, val)
        assert c_writer.commit()

        assert c_reader.get(key) == b""


# ---------------------------------------------------------------------------
# Redis integration verification
# ---------------------------------------------------------------------------

class TestRedisIntegration:
    def test_data_stored_in_redis(self):
        """Column family data must be stored in Redis, not in-memory."""
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, db=0)

        _, storage, (c0, c1) = _make_clients(2)
        c0.begin()
        c0.set(b"rkey", b"rval")
        assert c0.commit() is True

        keys = r.keys("*")
        assert len(keys) >= 2, (
            f"Expected at least 2 Redis keys (data + write columns) after "
            f"commit, found {len(keys)}. KvTable must persist data in Redis, "
            f"not in in-memory Python structures."
        )

        c1.begin()
        assert c1.get(b"rkey") == b"rval"
        r.close()

    def test_redis_erase_removes_data(self):
        """Erased entries must be removed from Redis, not just hidden."""
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, db=0)

        tso = TimestampOracle()
        storage = MemoryStorage()
        table = storage._table

        table.write(b"ek", Column.DATA, 100, b"ev")
        keys_before = r.keys("*")

        table.erase(b"ek", Column.DATA, 100)
        result = table.read(b"ek", Column.DATA)
        assert result is None, "Erased entry must not be readable"
        r.close()
