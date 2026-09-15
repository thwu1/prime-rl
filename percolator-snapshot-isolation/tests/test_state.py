"""Tests for Percolator distributed transaction implementation.

Verifies snapshot isolation via Hermitage anomaly tests and crash recovery
via commit hook scenarios.
"""

import sys
sys.path.insert(0, '/app')

import pytest
from percolator import TimestampOracle, MemoryStorage, CommitHooks, Client
from percolator.errors import ResponseDroppedError


def make_clients(n, hooks=None):
    """Create n clients sharing a single TSO and storage."""
    tso = TimestampOracle()
    storage = MemoryStorage()
    if hooks:
        storage.set_hooks(hooks)
    return [Client(tso, storage) for _ in range(n)]


class TestBasicOperations:
    """Fundamental single-client transaction tests."""

    def test_simple_read_write(self):
        [c] = make_clients(1)
        c.begin()
        c.set(b"key1", b"value1")
        assert c.commit() is True
        c.begin()
        assert c.get(b"key1") == b"value1"

    def test_multiple_keys_transaction(self):
        [c] = make_clients(1)
        c.begin()
        c.set(b"a", b"1")
        c.set(b"b", b"2")
        c.set(b"c", b"3")
        assert c.commit() is True
        c.begin()
        assert c.get(b"a") == b"1"
        assert c.get(b"b") == b"2"
        assert c.get(b"c") == b"3"

    def test_read_nonexistent_key(self):
        [c] = make_clients(1)
        c.begin()
        assert c.get(b"missing") == b""

    def test_overwrite_key(self):
        [c] = make_clients(1)
        c.begin()
        c.set(b"k", b"v1")
        assert c.commit() is True
        c.begin()
        c.set(b"k", b"v2")
        assert c.commit() is True
        c.begin()
        assert c.get(b"k") == b"v2"


class TestSnapshotIsolation:
    """Hermitage test suite for snapshot isolation properties.

    Each test is derived from the Hermitage project's SQL Server snapshot
    isolation tests, adapted for the Percolator key-value model.
    """

    def test_predicate_many_preceders_read_predicates(self):
        """PMP-Read: reads within a snapshot do not see concurrent writes."""
        c0, c1, c2 = make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        assert c1.get(b"3") == b""

        c2.begin()
        c2.set(b"3", b"30")
        assert c2.commit() is True

        # c1's snapshot predates c2's commit; key 3 remains invisible
        assert c1.get(b"3") == b""

    def test_predicate_many_preceders_write_predicates(self):
        """PMP-Write: write conflict detected when another txn committed."""
        c0, c1, c2 = make_clients(3)

        c0.begin()
        c0.set(b"1", b"10")
        c0.set(b"2", b"20")
        assert c0.commit() is True

        c1.begin()
        c2.begin()

        c1.set(b"1", b"20")
        c1.set(b"2", b"30")
        # get reads from storage, not from the local write buffer
        assert c1.get(b"2") == b"20"

        c2.set(b"2", b"40")
        assert c1.commit() is True
        # c2 conflicts: c1 already committed a write to key 2
        assert c2.commit() is False

    def test_lost_update(self):
        """P4: lost update is prevented by write-write conflict detection."""
        c0, c1, c2 = make_clients(3)

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
        """G-Single read-only: reads see a consistent snapshot."""
        c0, c1, c2 = make_clients(3)

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

        # c1 still sees the old snapshot
        assert c1.get(b"2") == b"20"

    def test_read_skew_predicate_dependencies(self):
        """G-Single predicates: new keys from concurrent txns are invisible."""
        c0, c1, c2 = make_clients(3)

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

        # c1 does not see key 3 created after its snapshot
        assert c1.get(b"3") == b""

    def test_read_skew_write_predicate(self):
        """G-Single write predicate: write after conflicting commit fails."""
        c0, c1, c2 = make_clients(3)

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
        # c2 already committed a write to key 2 after c1's snapshot
        assert c1.commit() is False

    def test_write_skew(self):
        """G2-item: write skew is allowed under snapshot isolation."""
        c0, c1, c2 = make_clients(3)

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

        # Both succeed: they write to different keys (write skew)
        assert c1.commit() is True
        assert c2.commit() is True

    def test_anti_dependency_cycles(self):
        """G2: concurrent writes to disjoint keys succeed; future reads see both."""
        c0, c1, c2, c3 = make_clients(4)

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


class TestCrashRecovery:
    """Tests for partial commit failure and lock cleanup.

    Uses CommitHooks to simulate network failures at the commit phase.
    Verifies that readers can recover data from partially committed
    transactions via lock cleanup.
    """

    def test_commit_primary_drop_secondary_requests(self):
        """Primary commits but secondary commit requests are dropped.
        Readers should recover secondary values via lock cleanup."""
        hooks = CommitHooks()
        c0, c1 = make_clients(2, hooks)

        c0.begin()
        c0.set(b"3", b"30")
        c0.set(b"4", b"40")
        c0.set(b"5", b"50")
        hooks.drop_req = True
        assert c0.commit() is True

        c1.begin()
        assert c1.get(b"3") == b"30"
        assert c1.get(b"4") == b"40"
        assert c1.get(b"5") == b"50"

    def test_commit_primary_success(self):
        """Duplicate of drop_secondary_requests: primary commits, secondaries dropped."""
        hooks = CommitHooks()
        c0, c1 = make_clients(2, hooks)

        c0.begin()
        c0.set(b"3", b"30")
        c0.set(b"4", b"40")
        c0.set(b"5", b"50")
        hooks.drop_req = True
        assert c0.commit() is True

        c1.begin()
        assert c1.get(b"3") == b"30"
        assert c1.get(b"4") == b"40"
        assert c1.get(b"5") == b"50"

    def test_commit_primary_success_without_response(self):
        """Primary commits on server but response is lost.
        Client raises but readers should still see all values."""
        hooks = CommitHooks()
        c0, c1 = make_clients(2, hooks)

        c0.begin()
        c0.set(b"3", b"30")
        c0.set(b"4", b"40")
        c0.set(b"5", b"50")
        hooks.drop_resp = True
        with pytest.raises(ResponseDroppedError):
            c0.commit()

        hooks.drop_resp = False
        c1.begin()
        assert c1.get(b"3") == b"30"
        assert c1.get(b"4") == b"40"
        assert c1.get(b"5") == b"50"

    def test_commit_primary_fail(self):
        """All commit requests are dropped. No data should be visible."""
        hooks = CommitHooks()
        c0, c1 = make_clients(2, hooks)

        c0.begin()
        c0.set(b"3", b"30")
        c0.set(b"4", b"40")
        c0.set(b"5", b"50")
        hooks.drop_req = True
        hooks.fail_primary = True
        assert c0.commit() is False

        c1.begin()
        assert c1.get(b"3") == b""
        assert c1.get(b"4") == b""
        assert c1.get(b"5") == b""
