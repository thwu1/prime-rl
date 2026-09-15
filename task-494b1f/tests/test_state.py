"""
Tests for Persistent Text Buffer System.

"""

import pytest
import time
import math
import sys
import os
import subprocess
import shutil
import tempfile
import sqlite3

sys.path.insert(0, "/app")

from piece_table import PieceTable


# ─── Basic text operations ───────────────────────────────────────────────────

class TestBasicOperations:
    def test_empty_init(self):
        pt = PieceTable()
        assert pt.get_text() == ""
        assert pt.length() == 0

    def test_init_with_text(self):
        pt = PieceTable("Hello World")
        assert pt.get_text() == "Hello World"
        assert pt.length() == 11

    def test_insert_at_end(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        assert pt.get_text() == "Hello World"

    def test_insert_at_beginning(self):
        pt = PieceTable("World")
        pt.insert(0, "Hello ")
        assert pt.get_text() == "Hello World"

    def test_insert_in_middle(self):
        pt = PieceTable("Helo")
        pt.insert(2, "l")
        assert pt.get_text() == "Hello"

    def test_insert_into_empty(self):
        pt = PieceTable()
        pt.insert(0, "Hello")
        assert pt.get_text() == "Hello"

    def test_multiple_inserts(self):
        pt = PieceTable()
        pt.insert(0, "World")
        pt.insert(0, "Hello ")
        pt.insert(11, "!")
        assert pt.get_text() == "Hello World!"

    def test_delete_from_end(self):
        pt = PieceTable("Hello World")
        pt.delete(5, 6)
        assert pt.get_text() == "Hello"

    def test_delete_from_beginning(self):
        pt = PieceTable("Hello World")
        pt.delete(0, 6)
        assert pt.get_text() == "World"

    def test_delete_from_middle(self):
        pt = PieceTable("Hello World")
        pt.delete(4, 3)
        assert pt.get_text() == "Hellorld"

    def test_delete_all(self):
        pt = PieceTable("Hello")
        pt.delete(0, 5)
        assert pt.get_text() == ""
        assert pt.length() == 0

    def test_insert_delete_sequence(self):
        pt = PieceTable("abcdef")
        pt.insert(3, "XYZ")       # abcXYZdef
        pt.delete(1, 4)           # aZdef
        pt.insert(1, "!")         # a!Zdef
        assert pt.get_text() == "a!Zdef"

    def test_char_at(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        for i, ch in enumerate("Hello World"):
            assert pt.char_at(i) == ch

    def test_length_tracking(self):
        pt = PieceTable("Hello")
        assert pt.length() == 5
        pt.insert(5, " World")
        assert pt.length() == 11
        pt.delete(5, 6)
        assert pt.length() == 5

    def test_many_small_inserts(self):
        pt = PieceTable("")
        expected = ""
        for i in range(100):
            ch = chr(ord('a') + i % 26)
            pos = i % (pt.length() + 1)
            pt.insert(pos, ch)
            expected = expected[:pos] + ch + expected[pos:]
        assert pt.get_text() == expected


# ─── Line operations ─────────────────────────────────────────────────────────

class TestLineOperations:
    def test_single_line_no_newline(self):
        pt = PieceTable("Hello World")
        assert pt.line_count() == 1
        assert pt.get_line(0) == "Hello World"

    def test_single_line_with_newline(self):
        pt = PieceTable("Hello\n")
        assert pt.line_count() == 1
        assert pt.get_line(0) == "Hello\n"

    def test_two_lines(self):
        pt = PieceTable("Hello\nWorld")
        assert pt.line_count() == 2
        assert pt.get_line(0) == "Hello\n"
        assert pt.get_line(1) == "World"

    def test_two_lines_trailing_newline(self):
        pt = PieceTable("Hello\nWorld\n")
        assert pt.line_count() == 2
        assert pt.get_line(0) == "Hello\n"
        assert pt.get_line(1) == "World\n"

    def test_empty_text(self):
        pt = PieceTable("")
        assert pt.line_count() == 1
        assert pt.get_line(0) == ""

    def test_only_newlines(self):
        pt = PieceTable("\n\n\n")
        assert pt.line_count() == 3
        assert pt.get_line(0) == "\n"
        assert pt.get_line(1) == "\n"
        assert pt.get_line(2) == "\n"

    def test_lines_after_insert(self):
        pt = PieceTable("Hello World")
        pt.insert(5, "\n")
        assert pt.line_count() == 2
        assert pt.get_line(0) == "Hello\n"
        assert pt.get_line(1) == " World"


# ─── Piece table pattern verification ────────────────────────────────────────

class TestPieceTablePattern:
    def test_original_buffer_preserved(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        orig, add = pt._get_buffers()
        assert orig == "Hello"
        assert " World" in add

    def test_add_buffer_append_only(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        _, add1 = pt._get_buffers()
        pt.insert(11, "!")
        _, add2 = pt._get_buffers()
        assert add2.startswith(add1)
        assert len(add2) > len(add1)

    def test_delete_does_not_shrink_buffers(self):
        pt = PieceTable("Hello World")
        orig_before, add_before = pt._get_buffers()
        pt.delete(5, 6)
        orig_after, add_after = pt._get_buffers()
        assert orig_before == orig_after
        assert len(add_after) >= len(add_before)

    def test_original_buffer_never_changes(self):
        pt = PieceTable("ABCDEF")
        for i in range(20):
            pt.insert(i % (pt.length() + 1), f"x{i}")
        for _ in range(5):
            if pt.length() > 3:
                pt.delete(1, 2)
        orig, _ = pt._get_buffers()
        assert orig == "ABCDEF"


# ─── BST structure invariants ─────────────────────────────────────────────────

class TestTreeStructure:
    def test_initial_height(self):
        pt = PieceTable("Hello")
        assert pt._tree_height() >= 1

    def test_piece_count_after_insert(self):
        pt = PieceTable("Hello")
        assert pt._piece_count() == 1
        pt.insert(3, "XY")
        assert pt._piece_count() >= 2

    def test_invariants_after_many_ops(self):
        pt = PieceTable("Hello World")
        for i in range(50):
            pt.insert(i % (pt.length() + 1), f"x{i}")
        assert pt._is_balanced()

    def test_height_logarithmic(self):
        """Tree height must grow at most logarithmically with piece count."""
        pt = PieceTable("x" * 100)
        for i in range(200):
            pos = i % (pt.length() + 1)
            pt.insert(pos, "ab")
        n = pt._piece_count()
        h = pt._tree_height()
        max_h = 6 * math.log2(n + 1) + 10
        assert h <= max_h, f"Height {h} too large for {n} pieces (max {max_h:.0f})"

    def test_invariants_after_deletes(self):
        pt = PieceTable("a" * 200)
        for i in range(50):
            pt.insert(i * 3 % (pt.length() + 1), "bc")
        for i in range(30):
            if pt.length() > 5:
                pt.delete(i % (pt.length() - 2), 2)
        assert pt._is_balanced()


# ─── Undo / Redo (linear) ────────────────────────────────────────────────────

class TestUndoRedo:
    def test_undo_single(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        assert pt.get_text() == "Hello World"
        assert pt.undo()
        assert pt.get_text() == "Hello"

    def test_undo_at_root_returns_false(self):
        pt = PieceTable("Hello")
        assert not pt.undo()
        assert pt.get_text() == "Hello"

    def test_redo_single(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        pt.undo()
        assert pt.redo()
        assert pt.get_text() == "Hello World"

    def test_redo_without_undo_returns_false(self):
        pt = PieceTable("Hello")
        assert not pt.redo()

    def test_undo_redo_chain(self):
        pt = PieceTable("A")
        pt.insert(1, "B")
        pt.insert(2, "C")
        pt.insert(3, "D")

        assert pt.undo(); assert pt.get_text() == "ABC"
        assert pt.undo(); assert pt.get_text() == "AB"
        assert pt.undo(); assert pt.get_text() == "A"
        assert not pt.undo()

        assert pt.redo(); assert pt.get_text() == "AB"
        assert pt.redo(); assert pt.get_text() == "ABC"
        assert pt.redo(); assert pt.get_text() == "ABCD"
        assert not pt.redo()

    def test_undo_depth(self):
        pt = PieceTable("A")
        assert pt.undo_depth() == 0
        pt.insert(1, "B")
        assert pt.undo_depth() == 1
        pt.insert(2, "C")
        assert pt.undo_depth() == 2
        pt.undo()
        assert pt.undo_depth() == 1
        pt.undo()
        assert pt.undo_depth() == 0

    def test_undo_delete(self):
        pt = PieceTable("Hello World")
        pt.delete(5, 6)
        assert pt.get_text() == "Hello"
        pt.undo()
        assert pt.get_text() == "Hello World"


# ─── Branching undo/redo ──────────────────────────────────────────────────────

class TestBranchingUndo:
    def test_branch_creation(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        pt.undo()
        pt.insert(5, " Earth")
        pt.undo()
        assert pt.get_text() == "Hello"
        assert pt.redo_branch_count() == 2

    def test_navigate_two_branches(self):
        pt = PieceTable("Hello")
        pt.insert(5, " World")
        pt.undo()
        pt.insert(5, " Earth")
        pt.undo()

        pt.redo(0)
        assert pt.get_text() == "Hello World"
        pt.undo()

        pt.redo(1)
        assert pt.get_text() == "Hello Earth"

    def test_three_branches(self):
        pt = PieceTable("A")
        pt.insert(1, "1")
        pt.undo()
        pt.insert(1, "2")
        pt.undo()
        pt.insert(1, "3")
        pt.undo()

        assert pt.redo_branch_count() == 3

        pt.redo(0); assert pt.get_text() == "A1"; pt.undo()
        pt.redo(1); assert pt.get_text() == "A2"; pt.undo()
        pt.redo(2); assert pt.get_text() == "A3"

    def test_nested_branches(self):
        pt = PieceTable("root")
        pt.insert(4, "-A")       # root-A
        pt.insert(6, "-B")       # root-A-B

        pt.undo()                 # root-A
        pt.insert(6, "-C")       # root-A-C

        pt.undo()                 # root-A
        assert pt.redo_branch_count() == 2

        pt.redo(0); assert pt.get_text() == "root-A-B"; pt.undo()
        pt.redo(1); assert pt.get_text() == "root-A-C"

    def test_branch_preserves_deep_history(self):
        pt = PieceTable("X")
        pt.insert(1, "A")        # XA
        pt.insert(2, "B")        # XAB

        pt.undo(); pt.undo()     # X
        pt.insert(1, "C")        # XC
        pt.insert(2, "D")        # XCD

        pt.undo(); pt.undo()     # X
        pt.redo(0)               # XA
        assert pt.get_text() == "XA"
        pt.redo(0)               # XAB
        assert pt.get_text() == "XAB"

        pt.undo(); pt.undo()     # X
        pt.redo(1)               # XC
        assert pt.get_text() == "XC"
        pt.redo(0)               # XCD
        assert pt.get_text() == "XCD"

    def test_redo_invalid_branch_returns_false(self):
        pt = PieceTable("A")
        pt.insert(1, "B")
        pt.undo()
        assert not pt.redo(1)    # only branch 0 exists
        assert not pt.redo(99)


# ─── Persistence guarantees ───────────────────────────────────────────────────

class TestPersistence:
    def test_snapshot_survives_edits(self):
        pt = PieceTable("Original")
        snap0 = pt.snapshot()

        pt.insert(8, " Modified")
        snap1 = pt.snapshot()

        pt.delete(0, 8)
        snap2 = pt.snapshot()

        pt.restore(snap0); assert pt.get_text() == "Original"
        pt.restore(snap1); assert pt.get_text() == "Original Modified"
        pt.restore(snap2); assert pt.get_text() == " Modified"

    def test_snapshot_survives_many_edits(self):
        pt = PieceTable("Start")
        snap = pt.snapshot()
        for i in range(100):
            pt.insert(pt.length(), f"-{i}")
        pt.restore(snap)
        assert pt.get_text() == "Start"

    def test_undo_after_restore(self):
        pt = PieceTable("A")
        snap = pt.snapshot()
        pt.insert(1, "B")
        pt.restore(snap)
        assert pt.get_text() == "A"
        pt.undo()   # undo the restore
        assert pt.get_text() == "AB"

    def test_multiple_snapshots_independent(self):
        pt = PieceTable("base")
        s1 = pt.snapshot()
        pt.insert(4, "-ext1")
        s2 = pt.snapshot()
        pt.delete(0, 4)
        s3 = pt.snapshot()

        pt.restore(s2); assert pt.get_text() == "base-ext1"
        pt.restore(s3); assert pt.get_text() == "-ext1"
        pt.restore(s1); assert pt.get_text() == "base"


# ─── Myers diff ──────────────────────────────────────────────────────────────

class TestMyersDiff:
    def test_identical(self):
        pt = PieceTable("Hello\nWorld\n")
        s1 = pt.snapshot()
        s2 = pt.snapshot()
        diff = pt.diff_snapshots(s1, s2)
        assert all(op == ' ' for op, _ in diff)
        assert len(diff) == 2

    def test_specific_substitution(self):
        pt = PieceTable("A\nB\nC\n")
        s1 = pt.snapshot()
        pt.delete(2, 2)       # remove "B\n" -> "A\nC\n"
        pt.insert(2, "X\n")   # "A\nX\nC\n"
        s2 = pt.snapshot()
        diff = pt.diff_snapshots(s1, s2)
        assert diff == [(' ', 'A'), ('-', 'B'), ('+', 'X'), (' ', 'C')]

    def test_pure_insertion(self):
        pt = PieceTable("")
        s1 = pt.snapshot()
        pt.insert(0, "Hello\nWorld\n")
        s2 = pt.snapshot()
        diff = pt.diff_snapshots(s1, s2)
        added = [(op, line) for op, line in diff if op == '+']
        assert len(added) == 2
        assert added[0] == ('+', 'Hello')
        assert added[1] == ('+', 'World')

    def test_pure_deletion(self):
        pt = PieceTable("Hello\nWorld\n")
        s1 = pt.snapshot()
        pt.delete(0, pt.length())
        s2 = pt.snapshot()
        diff = pt.diff_snapshots(s1, s2)
        removed = [(op, line) for op, line in diff if op == '-']
        assert len(removed) == 2

    def test_line_deletion_diff(self):
        pt = PieceTable("Line1\nLine2\nLine3\n")
        s1 = pt.snapshot()
        pt.delete(6, 6)   # remove "Line2\n"
        s2 = pt.snapshot()
        diff = pt.diff_snapshots(s1, s2)
        removed = [(op, line) for op, line in diff if op == '-']
        assert len(removed) == 1
        assert removed[0][1] == "Line2"

    def test_diff_common_lines_preserved(self):
        pt = PieceTable("A\nB\nC\nD\nE\n")
        s1 = pt.snapshot()
        pt.delete(4, 2)      # remove "C\n"
        pt.insert(4, "X\n")  # A\nB\nX\nD\nE\n
        s2 = pt.snapshot()
        diff = pt.diff_snapshots(s1, s2)
        context = [line for op, line in diff if op == ' ']
        assert 'A' in context
        assert 'B' in context
        assert 'D' in context
        assert 'E' in context


# ─── Performance ──────────────────────────────────────────────────────────────

class TestPerformance:
    def test_insert_performance(self):
        """5000 inserts must complete in < 30s (rules out O(n) per-op)."""
        pt = PieceTable("x" * 1000)
        start = time.time()
        for i in range(5000):
            pos = i % (pt.length() + 1)
            pt.insert(pos, "ab")
        elapsed = time.time() - start
        assert elapsed < 30, f"5000 inserts took {elapsed:.1f}s"
        assert pt.length() == 1000 + 5000 * 2

    def test_delete_performance(self):
        """1000 deletes must be efficient."""
        pt = PieceTable("x" * 5000)
        for i in range(500):
            pt.insert(i * 2 % (pt.length() + 1), "YZ")
        start = time.time()
        for _ in range(1000):
            if pt.length() > 2:
                pt.delete(0, 1)
        elapsed = time.time() - start
        assert elapsed < 30, f"1000 deletes took {elapsed:.1f}s"

    def test_char_at_performance(self):
        """Random access via char_at must be sub-linear."""
        pt = PieceTable("x" * 1000)
        for i in range(500):
            pt.insert(i * 3 % (pt.length() + 1), "abc")
        total = pt.length()
        start = time.time()
        for i in range(10000):
            pt.char_at(i % total)
        elapsed = time.time() - start
        assert elapsed < 10, f"10000 char_at took {elapsed:.1f}s"


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_insert_empty_string(self):
        pt = PieceTable("Hello")
        pt.insert(3, "")
        assert pt.get_text() == "Hello"

    def test_delete_zero_length(self):
        pt = PieceTable("Hello")
        pt.delete(3, 0)
        assert pt.get_text() == "Hello"

    def test_single_char_typing(self):
        pt = PieceTable()
        for ch in "Hello":
            pt.insert(pt.length(), ch)
        assert pt.get_text() == "Hello"

    def test_unicode(self):
        pt = PieceTable("caf\u00e9")
        pt.insert(4, " cr\u00e8me")
        assert pt.get_text() == "caf\u00e9 cr\u00e8me"
        assert pt.length() == 10

    def test_large_initial_text(self):
        text = "line\n" * 10000
        pt = PieceTable(text)
        assert pt.length() == len(text)
        assert pt.get_text() == text

    def test_delete_then_reinsert(self):
        pt = PieceTable("ABCDE")
        pt.delete(0, 5)
        assert pt.get_text() == ""
        pt.insert(0, "XYZ")
        assert pt.get_text() == "XYZ"


# ─── Journal Replay Pipeline ─────────────────────────────────────────────────

SNAP_EXPECTED = {
    1: "The quick brown fox\njumps over the lazy dog\n",
    2: "The quick brown fox\nquickly jumps over the lazy dog\n",
    3: "The quick red fox\nquickly jumps over the lazy dog\n",
    4: "The quick, brown fox\nquickly jumps over the lazy dog\n",
}


class TestJournalPipeline:
    @pytest.fixture(scope="class", autouse=True)
    def run_pipeline(self):
        """Run replay_journal.sh once before pipeline tests."""
        assert os.path.isfile("/app/replay_journal.sh"), \
            "/app/replay_journal.sh does not exist"
        result = subprocess.run(
            ["bash", "/app/replay_journal.sh"],
            capture_output=True, text=True, timeout=120,
            cwd="/app"
        )
        assert result.returncode == 0, \
            f"replay_journal.sh failed (rc={result.returncode}): {result.stderr}"

    def test_snapshot_1_content(self):
        with open("/app/output/snapshots/snapshot_1.txt") as f:
            assert f.read() == SNAP_EXPECTED[1]

    def test_snapshot_2_content(self):
        with open("/app/output/snapshots/snapshot_2.txt") as f:
            assert f.read() == SNAP_EXPECTED[2]

    def test_snapshot_3_content(self):
        with open("/app/output/snapshots/snapshot_3.txt") as f:
            assert f.read() == SNAP_EXPECTED[3]

    def test_snapshot_4_content(self):
        with open("/app/output/snapshots/snapshot_4.txt") as f:
            assert f.read() == SNAP_EXPECTED[4]

    def test_diff_1_2_exists(self):
        assert os.path.isfile("/app/output/diffs/diff_1_2.patch")

    def test_diff_2_3_exists(self):
        assert os.path.isfile("/app/output/diffs/diff_2_3.patch")

    def test_diff_3_4_exists(self):
        assert os.path.isfile("/app/output/diffs/diff_3_4.patch")

    def test_patch_1_to_2(self):
        self._verify_patch(1, 2)

    def test_patch_2_to_3(self):
        self._verify_patch(2, 3)

    def test_patch_3_to_4(self):
        self._verify_patch(3, 4)

    def _verify_patch(self, a, b):
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "source.txt")
            shutil.copy(f"/app/output/snapshots/snapshot_{a}.txt", src)
            result = subprocess.run(
                ["patch", src, f"/app/output/diffs/diff_{a}_{b}.patch"],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"patch failed: {result.stderr}"
            with open(src) as f:
                patched = f.read()
            assert patched == SNAP_EXPECTED[b]

    def test_versions_db_exists(self):
        assert os.path.isfile("/app/output/versions.db")

    def test_db_snapshots_table(self):
        conn = sqlite3.connect("/app/output/versions.db")
        cur = conn.cursor()
        cur.execute("SELECT id, char_count, line_count FROM snapshots ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 4
        assert rows[0] == (1, 44, 2)
        assert rows[1] == (2, 52, 2)
        assert rows[2] == (3, 50, 2)
        assert rows[3] == (4, 53, 2)

    def test_db_snapshots_content(self):
        conn = sqlite3.connect("/app/output/versions.db")
        cur = conn.cursor()
        for sid, expected in SNAP_EXPECTED.items():
            cur.execute("SELECT content FROM snapshots WHERE id = ?", (sid,))
            row = cur.fetchone()
            assert row is not None, f"snapshot {sid} missing from DB"
            assert row[0] == expected
        conn.close()

    def test_db_diffs_table(self):
        conn = sqlite3.connect("/app/output/versions.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT from_snapshot, to_snapshot, additions, deletions "
            "FROM diffs ORDER BY from_snapshot"
        )
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 3
        assert rows[0][:2] == (1, 2)
        assert rows[1][:2] == (2, 3)
        assert rows[2][:2] == (3, 4)
        for row in rows:
            assert row[2] >= 1, f"Expected >=1 addition, got {row[2]}"
            assert row[3] >= 1, f"Expected >=1 deletion, got {row[3]}"

    # ─── xxd validation tests ────────────────────────────────────────────────

    def test_header_hex_exists(self):
        """validate target must produce header_hex.txt with xxd output."""
        assert os.path.isfile("/app/output/header_hex.txt")

    def test_header_hex_contains_magic(self):
        """header_hex.txt must contain the hex representation of PTEDIT magic."""
        with open("/app/output/header_hex.txt") as f:
            content = f.read()
        # xxd output includes hex bytes; PTEDIT = 50 54 45 44 49 54
        hex_lower = content.lower().replace(" ", "").replace("\n", "")
        assert "5054454449" in hex_lower, \
            f"header_hex.txt missing PTEDIT magic bytes: {content!r}"

    def test_journal_valid_stamp(self):
        """validate target must create stamp file on successful validation."""
        assert os.path.isfile("/app/output/journal_valid.stamp")

    # ─── sqlite3 CLI report tests ────────────────────────────────────────────

    def test_report_exists(self):
        assert os.path.isfile("/app/output/report.txt")

    def test_report_version_header(self):
        with open("/app/output/report.txt") as f:
            content = f.read()
        assert "=== Version Report ===" in content

    def test_report_diff_summary_header(self):
        with open("/app/output/report.txt") as f:
            content = f.read()
        assert "--- Diff Summary ---" in content

    def test_report_contains_snapshot_counts(self):
        """Report must contain char_count values from all snapshots."""
        with open("/app/output/report.txt") as f:
            content = f.read()
        # Check that snapshot char counts appear (44, 52, 50, 53)
        assert "44" in content, "Report missing snapshot 1 char_count=44"
        assert "52" in content, "Report missing snapshot 2 char_count=52"
        assert "53" in content, "Report missing snapshot 4 char_count=53"

    def test_report_contains_column_headers(self):
        """Report must have sqlite3 column-formatted output with headers."""
        with open("/app/output/report.txt") as f:
            content = f.read().lower()
        assert "id" in content
        assert "line_count" in content
        assert "char_count" in content

    def test_report_contains_diff_totals(self):
        """Report must contain total additions/deletions summary."""
        with open("/app/output/report.txt") as f:
            content = f.read().lower()
        assert "total_additions" in content or "additions" in content
        assert "total_deletions" in content or "deletions" in content


# ─── Makefile target tests ────────────────────────────────────────────────────

class TestMakefileTargets:
    """Test Makefile existence, required targets, and clean/rebuild cycle."""

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile")

    def test_makefile_has_required_targets(self):
        with open("/app/Makefile") as f:
            content = f.read()
        for target in ["all", "validate", "replay", "diffs", "database",
                        "report", "clean"]:
            assert target in content, f"Makefile missing target: {target}"

    def test_make_clean_removes_output(self):
        """make clean must remove all generated output."""
        # Ensure output exists first
        subprocess.run(["make", "-C", "/app", "all"],
                       capture_output=True, text=True, timeout=120)
        assert os.path.isfile("/app/output/versions.db"), \
            "Precondition failed: versions.db should exist before clean"

        result = subprocess.run(["make", "-C", "/app", "clean"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, \
            f"make clean failed: {result.stderr}"
        assert not os.path.exists("/app/output/versions.db"), \
            "make clean did not remove versions.db"
        assert not os.path.exists("/app/output/journal_valid.stamp"), \
            "make clean did not remove journal_valid.stamp"

    def test_make_validate_only(self):
        """make validate must produce header files without triggering downstream."""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, text=True, timeout=30)
        result = subprocess.run(["make", "-C", "/app", "validate"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, \
            f"make validate failed: {result.stderr}"
        assert os.path.isfile("/app/output/header_hex.txt"), \
            "make validate did not create header_hex.txt"
        assert os.path.isfile("/app/output/journal_valid.stamp"), \
            "make validate did not create journal_valid.stamp"
        # Only validate ran — database should not exist
        assert not os.path.isfile("/app/output/versions.db"), \
            "make validate should not create versions.db"

    def test_make_full_rebuild(self):
        """make all from clean state must produce all artifacts."""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, text=True, timeout=30)
        result = subprocess.run(["make", "-C", "/app", "all"],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, \
            f"make all failed: {result.stderr}"
        assert os.path.isfile("/app/output/versions.db")
        assert os.path.isfile("/app/output/report.txt")
        assert os.path.isfile("/app/output/journal_valid.stamp")
        assert os.path.isfile("/app/output/header_hex.txt")
        assert os.path.isdir("/app/output/snapshots")
        assert os.path.isdir("/app/output/diffs")
