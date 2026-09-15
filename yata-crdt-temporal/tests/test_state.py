
"""
Tests for sequence CRDT with temporal snapshot support.
Verifies conflict resolution, sync properties, snapshots, delta encoding,
and advanced multi-client conflict resolution scenarios with known outcomes.
"""

import sys

import pytest

sys.path.insert(0, "/app")
from crdt import CRDTDoc


# =============================================================================
# Helper
# =============================================================================


def _full_sync(docs):
    """Pairwise sync all docs (sorted by client ID)."""
    keys = sorted(docs.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            docs[keys[i]].merge(docs[keys[j]])


# =============================================================================
# Basic operations
# =============================================================================


class TestBasicOperations:
    def test_insert_at_beginning(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        assert doc.get_content() == "hello"

    def test_insert_at_end(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        doc.insert(5, " world")
        assert doc.get_content() == "hello world"

    def test_insert_in_middle(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hllo")
        doc.insert(1, "e")
        assert doc.get_content() == "hello"

    def test_multiple_positional_inserts(self):
        doc = CRDTDoc(1)
        doc.insert(0, "a")
        doc.insert(1, "c")
        doc.insert(1, "b")
        assert doc.get_content() == "abc"

    def test_delete_single(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        doc.delete(0, 1)
        assert doc.get_content() == "ello"

    def test_delete_range(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello world")
        doc.delete(5, 6)
        assert doc.get_content() == "hello"

    def test_delete_middle(self):
        doc = CRDTDoc(1)
        doc.insert(0, "abcde")
        doc.delete(1, 3)
        assert doc.get_content() == "ae"

    def test_insert_after_delete(self):
        doc = CRDTDoc(1)
        doc.insert(0, "abc")
        doc.delete(1, 1)
        doc.insert(1, "x")
        assert doc.get_content() == "axc"


# =============================================================================
# State vector
# =============================================================================


class TestStateVector:
    def test_state_vector_single_client(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        sv = doc.get_state_vector()
        assert sv == {1: 5}

    def test_state_vector_empty(self):
        doc = CRDTDoc(1)
        sv = doc.get_state_vector()
        assert sv == {}

    def test_state_vector_after_sync(self):
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "abc")
        doc2.insert(0, "xy")
        doc1.merge(doc2)
        sv = doc1.get_state_vector()
        assert sv[1] == 3
        assert sv[2] == 2


# =============================================================================
# Concurrent inserts & conflict resolution
# =============================================================================


class TestConcurrentInserts:
    def test_concurrent_insert_same_position_two_clients(self):
        """Two clients independently insert at position 0 in empty docs."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "a")
        doc2.insert(0, "b")
        doc1.merge(doc2)
        # Both must converge; lower client_id is positioned left.
        assert doc1.get_content() == doc2.get_content()
        assert doc1.get_content() == "ab"

    def test_concurrent_insert_same_position_three_clients(self):
        """Three clients insert at position 0 — ordering by client_id."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc3 = CRDTDoc(3)
        doc1.insert(0, "a")
        doc2.insert(0, "b")
        doc3.insert(0, "c")

        doc1.merge(doc2)
        doc1.merge(doc3)
        doc2.merge(doc3)

        assert doc1.get_content() == doc2.get_content() == doc3.get_content()
        assert doc1.get_content() == "abc"

    def test_concurrent_insert_different_positions(self):
        """Two clients insert at different positions in a shared doc."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)

        doc1.insert(0, "abc")
        doc1.merge(doc2)

        # doc1 inserts between 'a' and 'b'; doc2 inserts between 'b' and 'c'
        doc1.insert(1, "x")
        doc2.insert(2, "y")
        doc1.merge(doc2)

        assert doc1.get_content() == doc2.get_content()
        assert doc1.get_content() == "axbyc"

    def test_concurrent_insert_same_context(self):
        """Two clients insert between the same two characters."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)

        doc1.insert(0, "ac")
        doc1.merge(doc2)

        doc1.insert(1, "x")
        doc2.insert(1, "y")
        doc1.merge(doc2)

        assert doc1.get_content() == doc2.get_content()
        # Lower client_id first in same context
        assert doc1.get_content() == "axyc"


# =============================================================================
# Sync properties
# =============================================================================


class TestSyncProperties:
    def test_sync_convergence(self):
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "hello")
        doc2.insert(0, "world")
        doc1.merge(doc2)
        assert doc1.get_content() == doc2.get_content()

    def test_sync_commutative(self):
        """Applying updates in any order yields the same content."""
        doc_a = CRDTDoc(1)
        doc_b = CRDTDoc(2)
        doc_c = CRDTDoc(3)

        doc_a.insert(0, "a")
        doc_b.insert(0, "b")
        doc_c.insert(0, "c")

        u_a = doc_a.encode_update({})
        u_b = doc_b.encode_update({})
        u_c = doc_c.encode_update({})

        # Order 1: a, b, c
        t1 = CRDTDoc(10)
        t1.apply_update(u_a)
        t1.apply_update(u_b)
        t1.apply_update(u_c)

        # Order 2: c, a, b
        t2 = CRDTDoc(11)
        t2.apply_update(u_c)
        t2.apply_update(u_a)
        t2.apply_update(u_b)

        # Order 3: b, c, a
        t3 = CRDTDoc(12)
        t3.apply_update(u_b)
        t3.apply_update(u_c)
        t3.apply_update(u_a)

        assert t1.get_content() == t2.get_content() == t3.get_content()

    def test_sync_idempotent(self):
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "hello")

        update = doc1.encode_update({})
        doc2.apply_update(update)
        after_first = doc2.get_content()
        doc2.apply_update(update)
        after_second = doc2.get_content()

        assert after_first == after_second == "hello"

    def test_sync_with_deletions(self):
        """Deletions propagate through sync."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)

        doc1.insert(0, "hello")
        doc1.merge(doc2)

        doc1.delete(0, 1)  # delete 'h'
        doc1.merge(doc2)

        assert doc1.get_content() == doc2.get_content() == "ello"


# =============================================================================
# Snapshots
# =============================================================================


class TestSnapshots:
    def test_snapshot_basic(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        snap = doc.snapshot()

        doc.insert(5, " world")
        assert doc.get_content() == "hello world"

        restored = doc.restore_snapshot(snap)
        assert restored == "hello"

    def test_snapshot_with_deletions(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello world")
        doc.delete(5, 6)
        snap = doc.snapshot()

        assert doc.get_content() == "hello"
        doc.insert(5, "!")

        restored = doc.restore_snapshot(snap)
        assert restored == "hello"

    def test_snapshot_preserves_pre_deletion_state(self):
        """Snapshot taken before deletion restores undeleted content."""
        doc = CRDTDoc(1)
        doc.insert(0, "abcde")
        snap_before = doc.snapshot()

        doc.delete(2, 2)  # delete 'cd'
        assert doc.get_content() == "abe"

        restored = doc.restore_snapshot(snap_before)
        assert restored == "abcde"

    def test_snapshot_multi_client(self):
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)

        doc1.insert(0, "abc")
        doc1.merge(doc2)
        doc2.insert(1, "x")
        doc2.merge(doc1)

        assert doc1.get_content() == doc2.get_content() == "axbc"

        snap = doc1.snapshot()
        doc1.insert(4, "y")
        restored = doc1.restore_snapshot(snap)
        assert restored == "axbc"


# =============================================================================
# Delta encoding
# =============================================================================


class TestDeltaEncoding:
    def test_delta_basic(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        snap1 = doc.snapshot()

        doc.insert(5, " world")
        snap2 = doc.snapshot()

        delta = doc.encode_delta(snap1, snap2)
        assert len(delta["structs"]) == 6  # ' world' = 6 chars
        assert len(delta["deletions"]) == 0

    def test_delta_with_deletions(self):
        doc = CRDTDoc(1)
        doc.insert(0, "hello")
        snap1 = doc.snapshot()

        doc.delete(0, 2)  # delete 'he'
        snap2 = doc.snapshot()

        delta = doc.encode_delta(snap1, snap2)
        assert len(delta["structs"]) == 0
        assert len(delta["deletions"]) == 2

    def test_delta_apply_reconstructs_state(self):
        """Applying a delta to a snapshot-state doc reconstructs the target."""
        doc = CRDTDoc(1)
        doc.insert(0, "abcde")
        snap1 = doc.snapshot()

        doc.insert(2, "XY")
        doc.delete(0, 1)  # delete 'a'
        snap2 = doc.snapshot()

        delta = doc.encode_delta(snap1, snap2)

        # Create a fresh doc at snap1 state
        fresh = CRDTDoc(1)
        fresh.insert(0, "abcde")
        assert fresh.get_content() == "abcde"

        fresh.apply_delta(delta)
        assert fresh.get_content() == doc.get_content()


# =============================================================================
# Complex / integration scenarios
# =============================================================================


class TestComplexScenarios:
    def test_interleaved_operations(self):
        """Concurrent edits at different positions in a shared document."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)

        doc1.insert(0, "The quick brown fox")
        doc1.merge(doc2)

        # doc1: replace "quick " with "slow "
        doc1.delete(4, 6)
        doc1.insert(4, "slow ")

        # doc2: replace "fox" with "cat"
        doc2.delete(16, 3)
        doc2.insert(16, "cat")

        doc1.merge(doc2)

        assert doc1.get_content() == doc2.get_content()
        assert "slow" in doc1.get_content()
        assert "cat" in doc1.get_content()

    def test_sequential_sync_convergence(self):
        """Multiple rounds of edit-sync cycles converge."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)

        doc1.insert(0, "a")
        doc1.merge(doc2)

        doc2.insert(1, "b")
        doc2.merge(doc1)

        doc1.insert(2, "c")
        doc1.merge(doc2)

        assert doc1.get_content() == doc2.get_content() == "abc"

    def test_full_temporal_reconstruction(self):
        """Reconstruct multiple historical versions from snapshots."""
        doc = CRDTDoc(1)

        doc.insert(0, "v1")
        snap_v1 = doc.snapshot()

        doc.delete(0, 2)
        doc.insert(0, "version2")
        snap_v2 = doc.snapshot()

        doc.delete(0, 8)
        doc.insert(0, "v3-final")
        snap_v3 = doc.snapshot()

        assert doc.restore_snapshot(snap_v1) == "v1"
        assert doc.restore_snapshot(snap_v2) == "version2"
        assert doc.restore_snapshot(snap_v3) == "v3-final"


# =============================================================================
# Advanced conflict resolution scenarios
# =============================================================================


class TestAdvancedConflictResolution:
    """Verify exact YATA conflict resolution across complex multi-client scenarios."""

    def test_multi_char_concurrent_two_clients(self):
        """Multi-character concurrent inserts at pos 0 — lower client's
        entire run appears left of the higher client's run."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "hello")
        doc2.insert(0, "world")
        doc1.merge(doc2)
        assert doc1.get_content() == "helloworld"
        assert doc2.get_content() == "helloworld"

    def test_four_clients_multi_char(self):
        """Four clients with multi-char inserts at pos 0 — ordered by client ID."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc3 = CRDTDoc(3)
        doc4 = CRDTDoc(4)
        doc1.insert(0, "AA")
        doc2.insert(0, "BB")
        doc3.insert(0, "CC")
        doc4.insert(0, "DD")
        docs = {1: doc1, 2: doc2, 3: doc3, 4: doc4}
        _full_sync(docs)
        for d in docs.values():
            assert d.get_content() == "AABBCCDD"

    def test_concurrent_insert_with_deletes(self):
        """Client 1 inserts and deletes, client 2 inserts independently —
        merged result places lower client's visible content first."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "abcde")
        doc1.delete(1, 2)  # delete 'bc' → visible "ade"
        doc2.insert(0, "xyz")
        doc1.merge(doc2)
        assert doc1.get_content() == "adexyz"
        assert doc2.get_content() == "adexyz"

    def test_phased_shared_then_diverge(self):
        """Clients share initial state, then concurrently insert at
        the same position — lower client ID wins the left slot."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "abcd")
        doc1.merge(doc2)
        doc1.insert(2, "X")
        doc2.insert(2, "Y")
        doc1.merge(doc2)
        assert doc1.get_content() == "abXYcd"
        assert doc2.get_content() == "abXYcd"

    def test_phased_delete_and_insert_same_region(self):
        """One client deletes a region while another inserts adjacent to it —
        the insertion survives the deletion."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc1.insert(0, "The quick fox")
        doc1.merge(doc2)
        doc1.delete(4, 6)  # remove "quick "
        doc2.insert(4, "very ")  # insert right before "quick"
        doc1.merge(doc2)
        assert doc1.get_content() == "The very fox"
        assert doc2.get_content() == "The very fox"

    def test_phased_three_way_conflict(self):
        """Three clients concurrently append at the same position after
        sharing an initial document — ordered by client ID."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        doc3 = CRDTDoc(3)
        doc1.insert(0, "base")
        docs = {1: doc1, 2: doc2, 3: doc3}
        _full_sync(docs)
        doc1.insert(4, "A")
        doc2.insert(4, "B")
        doc3.insert(4, "C")
        _full_sync(docs)
        for d in docs.values():
            assert d.get_content() == "baseABC"

    def test_multi_round_concurrent_appends(self):
        """Multiple rounds of concurrent appends and syncs — each round's
        concurrent inserts respect client ID ordering."""
        doc1 = CRDTDoc(1)
        doc2 = CRDTDoc(2)
        # Round 1
        doc1.insert(0, "Hello")
        doc1.merge(doc2)
        # Round 2: both append after "Hello"
        doc1.insert(5, " World")
        doc2.insert(5, "!")
        doc1.merge(doc2)
        # Lower client's run (" World") goes left, "!" goes right
        assert doc1.get_content() == "Hello World!"
        assert doc2.get_content() == "Hello World!"

    def test_reverse_client_id_ordering(self):
        """Higher client IDs insert first chronologically —
        verify correct placement (lower ID still goes left)."""
        doc_high = CRDTDoc(100)
        doc_low = CRDTDoc(1)
        doc_high.insert(0, "HIGH")
        doc_low.insert(0, "LOW")
        doc_high.merge(doc_low)
        assert doc_high.get_content() == "LOWHIGH"
        assert doc_low.get_content() == "LOWHIGH"
