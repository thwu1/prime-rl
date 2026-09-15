"""
Tests for snapshot-isolated transactional key-value store.

Verifies timestamp oracle properties, snapshot isolation semantics,
transaction anomaly handling, partial commit recovery, and lock cleanup.
"""


import sys
sys.path.insert(0, "/app")

import time
import threading
import subprocess
import pytest

from mvcc import TimestampOracle, MemoryStorage, Transaction, Column, LOCK_TTL_MS


# ---------------------------------------------------------------------------
# Timestamp Oracle
# ---------------------------------------------------------------------------

class TestTimestampOracle:
    def test_monotonic_and_unique(self):
        oracle = TimestampOracle()
        ts = [oracle.get_timestamp() for _ in range(1000)]
        assert ts == sorted(ts), "timestamps must be monotonically increasing"
        assert len(set(ts)) == 1000, "each timestamp must be unique"

    def test_concurrent_uniqueness(self):
        oracle = TimestampOracle()
        results = []
        lock = threading.Lock()

        def gather(n):
            local = [oracle.get_timestamp() for _ in range(100)]
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=gather, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1000
        assert len(set(results)) == 1000

    def test_cross_process_uniqueness(self):
        """Timestamps must be globally unique across independent OS processes."""
        script = (
            "import sys; sys.path.insert(0, '/app'); "
            "from mvcc import TimestampOracle; o = TimestampOracle(); "
            "print(','.join(str(o.get_timestamp()) for _ in range(50)))"
        )

        proc1 = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, timeout=10
        )
        assert proc1.returncode == 0, f"Process 1 failed: {proc1.stderr}"
        ts1 = list(map(int, proc1.stdout.strip().split(',')))

        proc2 = subprocess.run(
            ["python3", "-c", script],
            capture_output=True, text=True, timeout=10
        )
        assert proc2.returncode == 0, f"Process 2 failed: {proc2.stderr}"
        ts2 = list(map(int, proc2.stdout.strip().split(',')))

        all_ts = ts1 + ts2
        assert len(set(all_ts)) == 100, (
            f"Timestamps must be globally unique across processes "
            f"(got {len(set(all_ts))} unique out of 100)"
        )


# ---------------------------------------------------------------------------
# Basic Operations
# ---------------------------------------------------------------------------

class TestBasicOperations:
    @staticmethod
    def _env():
        o = TimestampOracle()
        s = MemoryStorage()
        return o, s

    def test_put_and_get(self):
        o, s = self._env()
        t = Transaction(o, s)
        t.begin()
        t.set(b"key1", b"val1")
        assert t.commit() is True

        r = Transaction(o, s)
        r.begin()
        assert r.get(b"key1") == b"val1"

    def test_read_nonexistent_key(self):
        o, s = self._env()
        t = Transaction(o, s)
        t.begin()
        assert t.get(b"no_such_key") == b""

    def test_overwrite(self):
        o, s = self._env()

        t1 = Transaction(o, s)
        t1.begin()
        t1.set(b"k", b"first")
        assert t1.commit() is True

        t2 = Transaction(o, s)
        t2.begin()
        t2.set(b"k", b"second")
        assert t2.commit() is True

        r = Transaction(o, s)
        r.begin()
        assert r.get(b"k") == b"second"

    def test_multi_key_commit(self):
        o, s = self._env()
        t = Transaction(o, s)
        t.begin()
        t.set(b"a", b"1")
        t.set(b"b", b"2")
        t.set(b"c", b"3")
        assert t.commit() is True

        r = Transaction(o, s)
        r.begin()
        assert r.get(b"a") == b"1"
        assert r.get(b"b") == b"2"
        assert r.get(b"c") == b"3"

    def test_empty_commit(self):
        o, s = self._env()
        t = Transaction(o, s)
        t.begin()
        assert t.commit() is True


# ---------------------------------------------------------------------------
# Snapshot Isolation - basic properties
# ---------------------------------------------------------------------------

class TestSnapshotIsolation:
    @staticmethod
    def _env():
        o = TimestampOracle()
        s = MemoryStorage()
        return o, s

    def test_reader_does_not_see_later_commit(self):
        """A reader's snapshot must not include writes committed after begin()."""
        o, s = self._env()

        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"k1", b"10"); assert t0.commit() is True

        reader = Transaction(o, s)
        reader.begin()

        writer = Transaction(o, s)
        writer.begin(); writer.set(b"k1", b"20"); assert writer.commit() is True

        assert reader.get(b"k1") == b"10"

    def test_get_reads_storage_not_buffer(self):
        """get() must read from the storage snapshot, not from local write buffer."""
        o, s = self._env()

        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"k", b"original"); assert t0.commit() is True

        t1 = Transaction(o, s)
        t1.begin()
        t1.set(b"k", b"buffered")
        assert t1.get(b"k") == b"original"

    def test_multi_version_reads(self):
        """Multiple readers see the snapshot consistent with their start time."""
        o, s = self._env()

        t1 = Transaction(o, s)
        t1.begin(); t1.set(b"k", b"v1"); assert t1.commit() is True

        r1 = Transaction(o, s)
        r1.begin()

        t2 = Transaction(o, s)
        t2.begin(); t2.set(b"k", b"v2"); assert t2.commit() is True

        r2 = Transaction(o, s)
        r2.begin()

        assert r1.get(b"k") == b"v1"
        assert r2.get(b"k") == b"v2"


# ---------------------------------------------------------------------------
# Hermitage: Predicate-Many-Preceders (PMP)
# ---------------------------------------------------------------------------

class TestHermitagePMP:
    """https://github.com/ept/hermitage - PMP anomaly tests."""

    @staticmethod
    def _setup():
        o = TimestampOracle(); s = MemoryStorage()
        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"1", b"10"); t0.set(b"2", b"20"); assert t0.commit()
        return o, s

    def test_read_predicates(self):
        o, s = self._setup()

        t1 = Transaction(o, s); t1.begin()
        assert t1.get(b"3") == b""

        t2 = Transaction(o, s); t2.begin()
        t2.set(b"3", b"30"); assert t2.commit() is True

        # t1 must still see an empty value for key 3
        assert t1.get(b"3") == b""

    def test_write_predicates(self):
        o, s = self._setup()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        t1.set(b"1", b"20"); t1.set(b"2", b"30")
        # get reads from storage snapshot, not local buffer
        assert t1.get(b"2") == b"20"

        t2.set(b"2", b"40")
        assert t1.commit() is True
        assert t2.commit() is False  # write-write conflict on key "2"


# ---------------------------------------------------------------------------
# Hermitage: Lost Update (P4)
# ---------------------------------------------------------------------------

class TestHermitageLostUpdate:
    def test_lost_update_prevented(self):
        o = TimestampOracle(); s = MemoryStorage()

        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"1", b"10"); t0.set(b"2", b"20"); assert t0.commit()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        assert t1.get(b"1") == b"10"
        assert t2.get(b"1") == b"10"

        t1.set(b"1", b"11")
        t2.set(b"1", b"11")
        assert t1.commit() is True
        assert t2.commit() is False


# ---------------------------------------------------------------------------
# Hermitage: Read Skew (G-single)
# ---------------------------------------------------------------------------

class TestHermitageReadSkew:
    @staticmethod
    def _setup():
        o = TimestampOracle(); s = MemoryStorage()
        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"1", b"10"); t0.set(b"2", b"20"); assert t0.commit()
        return o, s

    def test_read_only(self):
        o, s = self._setup()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        assert t1.get(b"1") == b"10"
        assert t2.get(b"1") == b"10"
        assert t2.get(b"2") == b"20"

        t2.set(b"1", b"12"); t2.set(b"2", b"18")
        assert t2.commit() is True

        assert t1.get(b"2") == b"20"  # t1 sees consistent snapshot

    def test_predicate_dependencies(self):
        o, s = self._setup()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        assert t1.get(b"1") == b"10"
        assert t1.get(b"2") == b"20"

        t2.set(b"3", b"30"); assert t2.commit() is True

        assert t1.get(b"3") == b""

    def test_write_predicate(self):
        o, s = self._setup()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        assert t1.get(b"1") == b"10"
        assert t2.get(b"1") == b"10"
        assert t2.get(b"2") == b"20"

        t2.set(b"1", b"12"); t2.set(b"2", b"18")
        assert t2.commit() is True

        t1.set(b"2", b"30")
        assert t1.commit() is False  # conflict on key "2"


# ---------------------------------------------------------------------------
# Hermitage: Write Skew (G2-item) -- ALLOWED under snapshot isolation
# ---------------------------------------------------------------------------

class TestHermitageWriteSkew:
    def test_write_skew_allowed(self):
        o = TimestampOracle(); s = MemoryStorage()

        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"1", b"10"); t0.set(b"2", b"20"); assert t0.commit()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        assert t1.get(b"1") == b"10"
        assert t1.get(b"2") == b"20"
        assert t2.get(b"1") == b"10"
        assert t2.get(b"2") == b"20"

        t1.set(b"1", b"11")
        t2.set(b"2", b"21")

        # Both commit because they write to different keys
        assert t1.commit() is True
        assert t2.commit() is True


# ---------------------------------------------------------------------------
# Hermitage: Anti-dependency Cycles (G2)
# ---------------------------------------------------------------------------

class TestHermitageAntiDependency:
    def test_anti_dependency(self):
        o = TimestampOracle(); s = MemoryStorage()

        t0 = Transaction(o, s)
        t0.begin(); t0.set(b"1", b"10"); t0.set(b"2", b"20"); assert t0.commit()

        t1 = Transaction(o, s); t1.begin()
        t2 = Transaction(o, s); t2.begin()

        t1.set(b"3", b"30")
        t2.set(b"4", b"42")

        assert t1.commit() is True
        assert t2.commit() is True

        t3 = Transaction(o, s); t3.begin()
        assert t3.get(b"3") == b"30"
        assert t3.get(b"4") == b"42"


# ---------------------------------------------------------------------------
# Partial Commit Recovery
# ---------------------------------------------------------------------------

class TestPartialCommit:
    def test_primary_committed_secondaries_dropped(self):
        """If primary commits but secondary commits are dropped, readers must
        resolve the leftover locks by rolling forward the secondaries."""
        o = TimestampOracle(); s = MemoryStorage()

        t0 = Transaction(o, s)
        t0.begin()
        t0.set(b"3", b"30"); t0.set(b"4", b"40"); t0.set(b"5", b"50")
        t0.set_commit_filter(lambda key, is_primary: is_primary)
        assert t0.commit() is True

        reader = Transaction(o, s); reader.begin()
        assert reader.get(b"3") == b"30"
        assert reader.get(b"4") == b"40"
        assert reader.get(b"5") == b"50"

    def test_primary_fail_full_rollback(self):
        """If the primary commit is dropped, all prewrites must be cleaned up."""
        o = TimestampOracle(); s = MemoryStorage()

        t0 = Transaction(o, s)
        t0.begin()
        t0.set(b"3", b"30"); t0.set(b"4", b"40"); t0.set(b"5", b"50")
        t0.set_commit_filter(lambda key, is_primary: False)
        assert t0.commit() is False

        reader = Transaction(o, s); reader.begin()
        assert reader.get(b"3") == b""
        assert reader.get(b"4") == b""
        assert reader.get(b"5") == b""

    def test_reader_resolves_secondary_locks(self):
        """Reader rolls forward uncommitted secondaries when primary is committed."""
        o = TimestampOracle(); s = MemoryStorage()

        # Write initial values
        ti = Transaction(o, s)
        ti.begin(); ti.set(b"a", b"init_a"); ti.set(b"b", b"init_b")
        assert ti.commit() is True

        # Partial commit: primary committed, secondaries dropped
        t = Transaction(o, s)
        t.begin(); t.set(b"a", b"new_a"); t.set(b"b", b"new_b")
        t.set_commit_filter(lambda key, is_primary: is_primary)
        assert t.commit() is True

        reader = Transaction(o, s); reader.begin()
        assert reader.get(b"a") == b"new_a"
        assert reader.get(b"b") == b"new_b"


# ---------------------------------------------------------------------------
# Lock Cleanup (TTL-based)
# ---------------------------------------------------------------------------

class TestLockCleanup:
    def test_stale_primary_lock_cleaned(self):
        """A stale primary lock (TTL expired) is cleaned up by a reader."""
        o = TimestampOracle(); s = MemoryStorage()

        # Simulate a crashed transaction: manually place prewrite data + lock
        crashed_ts = o.get_timestamp()
        old_ns = time.time_ns() - (LOCK_TTL_MS * 1_000_000 * 3)
        s.write(b"key", Column.DATA, crashed_ts, b"crashed_val")
        s.write(b"key", Column.LOCK, crashed_ts, (b"key", old_ns))

        reader = Transaction(o, s); reader.begin()
        assert reader.get(b"key") == b""  # not committed -> rolled back

    def test_stale_secondary_lock_primary_committed(self):
        """Stale secondary lock whose primary was committed: reader rolls forward."""
        o = TimestampOracle(); s = MemoryStorage()

        start_ts = o.get_timestamp()
        commit_ts = o.get_timestamp()

        # Primary was committed
        s.write(b"primary", Column.DATA, start_ts, b"pval")
        s.write(b"primary", Column.WRITE, commit_ts, start_ts)

        # Secondary has stale lock (prewrite done, commit dropped)
        old_ns = time.time_ns() - (LOCK_TTL_MS * 1_000_000 * 3)
        s.write(b"secondary", Column.DATA, start_ts, b"sval")
        s.write(b"secondary", Column.LOCK, start_ts, (b"primary", old_ns))

        reader = Transaction(o, s); reader.begin()
        assert reader.get(b"secondary") == b"sval"

    def test_stale_secondary_lock_primary_not_committed(self):
        """Stale secondary lock whose primary was never committed: reader rolls back."""
        o = TimestampOracle(); s = MemoryStorage()

        start_ts = o.get_timestamp()

        old_ns = time.time_ns() - (LOCK_TTL_MS * 1_000_000 * 3)

        # Primary: prewritten but not committed, lock stale
        s.write(b"aa_primary", Column.DATA, start_ts, b"pval")
        s.write(b"aa_primary", Column.LOCK, start_ts, (b"aa_primary", old_ns))

        # Secondary: prewritten, lock stale, references primary
        s.write(b"bb_secondary", Column.DATA, start_ts, b"sval")
        s.write(b"bb_secondary", Column.LOCK, start_ts, (b"aa_primary", old_ns))

        reader = Transaction(o, s); reader.begin()
        assert reader.get(b"bb_secondary") == b""
