"""
Tests for YATA Sequence CRDT Engine.

Verifies conflict resolution, convergence, state-vector sync, and temporal queries.

"""

import sys
import os
import copy
import itertools

sys.path.insert(0, "/app")

from crdt_engine import Document


# ──────────────────────────── helpers ────────────────────────────

def sync_pair(d1, d2):
    """Full bidirectional sync between two documents."""
    sv1 = d1.get_state_vector()
    sv2 = d2.get_state_vector()
    u1 = d1.encode_update(sv2)
    u2 = d2.encode_update(sv1)
    d1.apply_update(u2)
    d2.apply_update(u1)


def make_base(text, client=0):
    """Create a document with initial text and return (doc, update)."""
    doc = Document(client)
    doc.insert(0, text)
    return doc, doc.encode_update()


def apply_to_fresh(client_id, *updates):
    doc = Document(client_id)
    for u in updates:
        doc.apply_update(u)
    return doc


# ─────────────────── 1. basic operations ───────────────────────

class TestBasicOperations:
    def test_insert_empty(self):
        doc = Document(1)
        doc.insert(0, "hello")
        assert doc.get_text() == "hello"

    def test_insert_at_end(self):
        doc = Document(1)
        doc.insert(0, "hello")
        doc.insert(5, " world")
        assert doc.get_text() == "hello world"

    def test_insert_at_start(self):
        doc = Document(1)
        doc.insert(0, "world")
        doc.insert(0, "hello ")
        assert doc.get_text() == "hello world"

    def test_insert_middle(self):
        doc = Document(1)
        doc.insert(0, "hllo")
        doc.insert(1, "e")
        assert doc.get_text() == "hello"

    def test_delete_single(self):
        doc = Document(1)
        doc.insert(0, "hello")
        doc.delete(1, 1)
        assert doc.get_text() == "hllo"

    def test_delete_range(self):
        doc = Document(1)
        doc.insert(0, "hello world")
        doc.delete(5, 6)
        assert doc.get_text() == "hello"

    def test_delete_from_start(self):
        doc = Document(1)
        doc.insert(0, "hello")
        doc.delete(0, 3)
        assert doc.get_text() == "lo"

    def test_insert_after_delete(self):
        doc = Document(1)
        doc.insert(0, "hllo")
        doc.delete(0, 1)
        doc.insert(0, "He")
        assert doc.get_text() == "Hello"


# ─────────────────── 2. state vector ───────────────────────────

class TestStateVector:
    def test_empty(self):
        doc = Document(1)
        assert doc.get_state_vector() == {}

    def test_after_insert(self):
        doc = Document(1)
        doc.insert(0, "hi")
        sv = doc.get_state_vector()
        assert sv == {1: 2}

    def test_multiple_inserts(self):
        doc = Document(1)
        doc.insert(0, "ab")
        doc.insert(2, "cd")
        sv = doc.get_state_vector()
        assert sv[1] == 4

    def test_after_remote_apply(self):
        doc1 = Document(1)
        doc1.insert(0, "hey")
        u = doc1.encode_update()

        doc2 = Document(2)
        doc2.apply_update(u)
        doc2.insert(3, "!")
        sv = doc2.get_state_vector()
        assert sv[1] == 3
        assert sv[2] == 1


# ──────── 3. YATA conflict resolution — concurrent inserts ─────

class TestConflictResolution:
    def test_two_clients_same_position(self):
        """Lower client_id item goes first."""
        d1 = Document(1)
        d2 = Document(2)
        d1.insert(0, "A")
        d2.insert(0, "B")
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text() == "AB"

    def test_three_clients_same_position(self):
        d1, d2, d3 = Document(1), Document(2), Document(3)
        d1.insert(0, "A")
        d2.insert(0, "B")
        d3.insert(0, "C")
        u1, u2, u3 = d1.encode_update(), d2.encode_update(), d3.encode_update()
        for d in (d1, d2, d3):
            d.apply_update(u1)
            d.apply_update(u2)
            d.apply_update(u3)
        assert d1.get_text() == d2.get_text() == d3.get_text() == "ABC"

    def test_concurrent_insert_in_shared_doc(self):
        """Two clients insert at the same position in a shared document."""
        base, u0 = make_base("AC", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)
        d1.insert(1, "X")   # AXC
        d2.insert(1, "Y")   # AYC
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text() == "AXYC"

    def test_multi_char_concurrent(self):
        """Multi-character compound inserts at the same position."""
        d1, d2 = Document(1), Document(2)
        d1.insert(0, "AB")
        d2.insert(0, "XY")
        u1, u2 = d1.encode_update(), d2.encode_update()
        da = apply_to_fresh(10, u1, u2)
        db = apply_to_fresh(11, u2, u1)
        assert da.get_text() == db.get_text() == "ABXY"

    def test_insert_before_shared_content(self):
        """Both clients insert before existing content M."""
        base, u0 = make_base("M", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)
        d1.insert(0, "A")
        d2.insert(0, "B")
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text() == "ABM"


# ──────────── 4. cascading conflict (two-set algorithm) ─────────

class TestCascadingConflict:
    def test_sequential_vs_concurrent(self):
        """
        Client 1 types A then B (B depends on A via origin).
        Client 2 types X concurrently at the same position.
        The two-set algorithm must keep B adjacent to A.
        """
        base, u0 = make_base("M", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)

        d1.insert(0, "A")
        d1.insert(1, "B")
        d2.insert(0, "X")

        sv0 = base.get_state_vector()
        u1 = d1.encode_update(sv0)
        u2 = d2.encode_update(sv0)

        da = apply_to_fresh(10, u0, u1, u2)
        db = apply_to_fresh(11, u0, u2, u1)
        assert da.get_text() == db.get_text() == "ABXM"

    def test_both_sequential(self):
        """
        Both clients type two chars sequentially (each char depends on previous).
        Must converge regardless of application order.
        """
        base, u0 = make_base("M", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)

        d1.insert(0, "A")
        d1.insert(1, "B")
        d2.insert(0, "X")
        d2.insert(1, "Y")

        sv0 = base.get_state_vector()
        u1 = d1.encode_update(sv0)
        u2 = d2.encode_update(sv0)

        da = apply_to_fresh(10, u0, u1, u2)
        db = apply_to_fresh(11, u0, u2, u1)
        assert da.get_text() == db.get_text() == "ABXYM"

    def test_three_sequential_chains(self):
        """Three clients each type two chars; all converge in every order."""
        base, u0 = make_base("Z", client=0)
        clients = []
        updates = []
        for cid in (1, 2, 3):
            d = apply_to_fresh(cid, u0)
            d.insert(0, chr(64 + cid))         # A / B / C
            d.insert(1, chr(64 + cid).lower())  # a / b / c
            clients.append(d)
            updates.append(d.encode_update(base.get_state_vector()))

        results = set()
        for perm in itertools.permutations(range(3)):
            doc = apply_to_fresh(99, u0)
            for i in perm:
                doc.apply_update(updates[i])
            results.add(doc.get_text())
        assert len(results) == 1, f"Non-convergent results: {results}"
        assert results.pop() == "AaBbCcZ"


# ──────────────── 5. commutativity & idempotency ────────────────

class TestCommIdemp:
    def test_commutativity_different_positions(self):
        base, u0 = make_base("base", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)
        d1.insert(4, "END")
        d2.insert(0, "START")
        sv0 = base.get_state_vector()
        u1, u2 = d1.encode_update(sv0), d2.encode_update(sv0)
        da = apply_to_fresh(10, u0, u1, u2)
        db = apply_to_fresh(11, u0, u2, u1)
        assert da.get_text() == db.get_text() == "STARTbaseEND"

    def test_commutativity_same_position(self):
        base, u0 = make_base("AB", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)
        d1.insert(1, "X")
        d2.insert(1, "Y")
        sv0 = base.get_state_vector()
        u1, u2 = d1.encode_update(sv0), d2.encode_update(sv0)
        da = apply_to_fresh(10, u0, u1, u2)
        db = apply_to_fresh(11, u0, u2, u1)
        assert da.get_text() == db.get_text() == "AXYB"

    def test_idempotency(self):
        doc = Document(1)
        doc.insert(0, "hello")
        update = doc.encode_update()

        target = Document(2)
        target.apply_update(update)
        t1 = target.get_text()
        target.apply_update(update)
        assert target.get_text() == t1 == "hello"


# ──────────────── 6. diff-based sync ────────────────────────────

class TestDiffSync:
    def test_diff_sync_basic(self):
        d1 = Document(1)
        d1.insert(0, "hello")
        d2 = apply_to_fresh(2, d1.encode_update())
        d1.insert(5, " world")
        d2.insert(0, "say: ")
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text() == "say: hello world"

    def test_diff_sync_with_delete(self):
        d1 = Document(1)
        d1.insert(0, "ABCDE")
        d2 = apply_to_fresh(2, d1.encode_update())
        d1.delete(2, 1)   # ABDE
        d2.insert(2, "X")  # ABXCDE
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text()
        text = d1.get_text()
        # C was deleted by d1, X was inserted by d2
        assert "X" in text
        assert "C" not in text


# ──────────────── 7. snapshots ──────────────────────────────────

class TestSnapshots:
    def test_snapshot_basic(self):
        doc = Document(1)
        doc.insert(0, "hello")
        snap1 = doc.snapshot()
        doc.insert(5, " world")
        snap2 = doc.snapshot()
        assert doc.text_at_snapshot(snap1) == "hello"
        assert doc.text_at_snapshot(snap2) == "hello world"

    def test_snapshot_with_delete(self):
        doc = Document(1)
        doc.insert(0, "hello world")
        snap_before = doc.snapshot()
        doc.delete(0, 6)  # delete "hello "
        snap_after = doc.snapshot()
        assert doc.text_at_snapshot(snap_before) == "hello world"
        assert doc.text_at_snapshot(snap_after) == "world"

    def test_snapshot_multiple_edits(self):
        doc = Document(1)
        doc.insert(0, "AB")
        s1 = doc.snapshot()
        doc.insert(1, "X")   # AXB
        s2 = doc.snapshot()
        doc.delete(0, 1)      # XB
        s3 = doc.snapshot()
        doc.insert(0, "Z")   # ZXB
        s4 = doc.snapshot()
        assert doc.text_at_snapshot(s1) == "AB"
        assert doc.text_at_snapshot(s2) == "AXB"
        assert doc.text_at_snapshot(s3) == "XB"
        assert doc.text_at_snapshot(s4) == "ZXB"


# ────────── 8. convergence with concurrent deletes ──────────────

class TestConcurrentDeletes:
    def test_concurrent_delete_same_char(self):
        """Two clients delete the same character. Must converge."""
        base, u0 = make_base("ABC", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)
        d1.delete(1, 1)  # AC
        d2.delete(1, 1)  # AC
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text() == "AC"

    def test_concurrent_insert_and_delete(self):
        """One client inserts, other deletes at nearby position."""
        base, u0 = make_base("ABCD", client=0)
        d1 = apply_to_fresh(1, u0)
        d2 = apply_to_fresh(2, u0)
        d1.insert(2, "XX")   # ABXXCD
        d2.delete(1, 2)      # AD
        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text()
        text = d1.get_text()
        assert "XX" in text
        assert "A" in text and "D" in text


# ────────── 9. complex multi-client scenario ────────────────────

class TestComplexScenario:
    def test_multi_client_convergence(self):
        """
        Four clients make diverse edits to a shared doc.
        All six pairwise-syncs must converge to the same state.
        """
        base, u0 = make_base("The fox", client=0)
        sv0 = base.get_state_vector()

        d1 = apply_to_fresh(1, u0)
        d1.insert(4, "quick ")          # The quick fox

        d2 = apply_to_fresh(2, u0)
        d2.insert(7, " jumps")          # The fox jumps

        d3 = apply_to_fresh(3, u0)
        d3.delete(0, 4)                 # fox
        d3.insert(0, "A ")              # A fox

        u1, u2, u3 = (
            d1.encode_update(sv0),
            d2.encode_update(sv0),
            d3.encode_update(sv0),
        )

        results = set()
        for perm in itertools.permutations([u1, u2, u3]):
            doc = apply_to_fresh(99, u0)
            for u in perm:
                doc.apply_update(u)
            results.add(doc.get_text())

        assert len(results) == 1, f"Non-convergent: {results}"


# ────────── 10. compound item splitting ─────────────────────────

class TestCompoundSplitting:
    def test_insert_inside_compound(self):
        """Inserting in the middle of a multi-char item must split correctly."""
        doc = Document(1)
        doc.insert(0, "ABCDE")
        doc.insert(2, "XY")
        assert doc.get_text() == "ABXYCDE"

    def test_delete_inside_compound(self):
        doc = Document(1)
        doc.insert(0, "ABCDE")
        doc.delete(1, 3)
        assert doc.get_text() == "AE"

    def test_remote_insert_splits_local_compound(self):
        """Remote insert that targets the middle of a local compound item."""
        d1 = Document(1)
        d1.insert(0, "ABCDE")

        d2 = apply_to_fresh(2, d1.encode_update())
        d2.insert(2, "XY")  # ABXYCDE

        # d1 doesn't know about XY yet; inserts at pos 4 in "ABCDE" → "ABCDZZE"
        d1.insert(4, "ZZ")
        assert d1.get_text() == "ABCDZZE"

        sync_pair(d1, d2)
        assert d1.get_text() == d2.get_text()
        text = d1.get_text()
        assert "XY" in text and "ZZ" in text


# ────────── 11. encode_update with target_sv ────────────────────

class TestEncodeDiff:
    def test_encode_sends_only_new(self):
        """encode_update(target_sv) must not include items the target already has."""
        d = Document(1)
        d.insert(0, "AB")
        sv_after_ab = d.get_state_vector()  # {1: 2}
        d.insert(2, "CD")

        diff = d.encode_update(sv_after_ab)
        # diff should include CD but not AB
        for item in diff['items']:
            cid, clock = item['id']
            if cid == 1:
                assert clock >= 2, "Sent already-known item"

    def test_full_sync_from_zero(self):
        d = Document(1)
        d.insert(0, "hi")
        d.delete(0, 1)
        u = d.encode_update()
        d2 = Document(2)
        d2.apply_update(u)
        assert d2.get_text() == d.get_text()
