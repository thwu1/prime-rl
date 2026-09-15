
import pytest
import sqlite3
import sys

sys.path.insert(0, "/app")
from editor_engine import PieceTable, UndoTree, myers_diff, SessionStore


# ====================================================================
# PieceTable: Basic Operations
# ====================================================================


class TestPieceTableBasic:
    def test_create_with_text(self):
        pt = PieceTable("Hello World")
        assert pt.get_text() == "Hello World"
        assert pt.length == 11

    def test_create_empty(self):
        pt = PieceTable("")
        assert pt.get_text() == ""
        assert pt.length == 0

    def test_insert_at_beginning(self):
        pt = PieceTable("World")
        pt2 = pt.insert(0, "Hello ")
        assert pt2.get_text() == "Hello World"
        assert pt2.length == 11

    def test_insert_at_end(self):
        pt = PieceTable("Hello")
        pt2 = pt.insert(5, " World")
        assert pt2.get_text() == "Hello World"

    def test_insert_in_middle(self):
        pt = PieceTable("HelloWorld")
        pt2 = pt.insert(5, " ")
        assert pt2.get_text() == "Hello World"

    def test_delete_from_beginning(self):
        pt = PieceTable("Hello World")
        pt2 = pt.delete(0, 6)
        assert pt2.get_text() == "World"

    def test_delete_from_end(self):
        pt = PieceTable("Hello World")
        pt2 = pt.delete(5, 6)
        assert pt2.get_text() == "Hello"

    def test_delete_from_middle(self):
        pt = PieceTable("Hello Beautiful World")
        pt2 = pt.delete(5, 10)
        assert pt2.get_text() == "Hello World"


# ====================================================================
# PieceTable: Persistence
# ====================================================================


class TestPieceTablePersistence:
    def test_insert_preserves_original(self):
        pt1 = PieceTable("Hello World")
        pt2 = pt1.insert(5, " Beautiful")
        assert pt1.get_text() == "Hello World"
        assert pt2.get_text() == "Hello Beautiful World"

    def test_delete_preserves_original(self):
        pt1 = PieceTable("Hello Beautiful World")
        pt2 = pt1.delete(5, 10)
        assert pt1.get_text() == "Hello Beautiful World"
        assert pt2.get_text() == "Hello World"

    def test_chain_preserves_all_versions(self):
        pt1 = PieceTable("A")
        pt2 = pt1.insert(1, "B")
        pt3 = pt2.insert(2, "C")
        pt4 = pt3.insert(3, "D")
        pt5 = pt4.insert(4, "E")
        assert pt1.get_text() == "A"
        assert pt2.get_text() == "AB"
        assert pt3.get_text() == "ABC"
        assert pt4.get_text() == "ABCD"
        assert pt5.get_text() == "ABCDE"

    def test_divergent_edits_from_same_base(self):
        pt1 = PieceTable("Base")
        pt2a = pt1.insert(4, "X")
        pt2b = pt1.insert(4, "Y")
        pt2c = pt1.insert(0, "Z")
        assert pt1.get_text() == "Base"
        assert pt2a.get_text() == "BaseX"
        assert pt2b.get_text() == "BaseY"
        assert pt2c.get_text() == "ZBase"


# ====================================================================
# PieceTable: Complex / Edge Cases
# ====================================================================


class TestPieceTableComplex:
    def test_multiple_inserts_build_pieces(self):
        pt = PieceTable("AC")
        pt = pt.insert(1, "B")
        assert pt.get_text() == "ABC"
        pt = pt.insert(3, "D")
        assert pt.get_text() == "ABCD"
        pt = pt.insert(0, "Z")
        assert pt.get_text() == "ZABCD"

    def test_delete_spanning_multiple_pieces(self):
        pt = PieceTable("Hello")
        pt = pt.insert(5, " Beautiful")
        pt = pt.insert(15, " World")
        assert pt.get_text() == "Hello Beautiful World"
        # Delete " Beautiful" which spans from piece boundary into add buffer
        pt2 = pt.delete(5, 10)
        assert pt2.get_text() == "Hello World"

    def test_delete_entire_content(self):
        pt = PieceTable("Hello")
        pt2 = pt.delete(0, 5)
        assert pt2.get_text() == ""
        assert pt2.length == 0

    def test_insert_into_empty_after_delete(self):
        pt = PieceTable("X")
        pt = pt.delete(0, 1)
        assert pt.get_text() == ""
        pt = pt.insert(0, "New")
        assert pt.get_text() == "New"

    def test_insert_delete_roundtrip_preserves_all(self):
        pt1 = PieceTable("Hello World")
        pt2 = pt1.insert(5, " Beautiful")
        pt3 = pt2.delete(5, 10)
        assert pt1.get_text() == "Hello World"
        assert pt2.get_text() == "Hello Beautiful World"
        assert pt3.get_text() == "Hello World"

    def test_large_text(self):
        line = "X" * 500 + "\n"
        text = line * 200
        pt = PieceTable(text)
        assert pt.length == len(text)
        mid = pt.length // 2
        pt2 = pt.insert(mid, "INSERTED")
        assert pt2.length == pt.length + 8
        assert "INSERTED" in pt2.get_text()
        assert pt.length == len(text)  # original unchanged


# ====================================================================
# UndoTree: Basic Operations
# ====================================================================


class TestUndoTreeBasic:
    def test_create(self):
        tree = UndoTree("Hello")
        assert tree.current_text() == "Hello"
        assert tree.current_node_id == 0

    def test_single_edit(self):
        tree = UndoTree("Hello")
        tree.apply_insert(5, " World")
        assert tree.current_text() == "Hello World"
        assert tree.current_node_id == 1

    def test_undo(self):
        tree = UndoTree("Hello")
        tree.apply_insert(5, " World")
        result = tree.undo()
        assert result is True
        assert tree.current_text() == "Hello"
        assert tree.current_node_id == 0

    def test_undo_at_root_returns_false(self):
        tree = UndoTree("Hello")
        result = tree.undo()
        assert result is False
        assert tree.current_text() == "Hello"

    def test_redo(self):
        tree = UndoTree("Hello")
        tree.apply_insert(5, " World")
        tree.undo()
        result = tree.redo(0)
        assert result is True
        assert tree.current_text() == "Hello World"

    def test_redo_no_children_returns_false(self):
        tree = UndoTree("Hello")
        result = tree.redo(0)
        assert result is False

    def test_redo_invalid_branch_returns_false(self):
        tree = UndoTree("Hello")
        tree.apply_insert(5, " World")
        tree.undo()
        result = tree.redo(5)  # only branch 0 exists
        assert result is False


# ====================================================================
# UndoTree: Branching
# ====================================================================


class TestUndoTreeBranching:
    def test_edit_after_undo_creates_branch(self):
        tree = UndoTree("ABCDEF")
        tree.apply_insert(3, "XYZ")  # node 1: ABCXYZDEF
        tree.undo()  # back to ABCDEF
        tree.apply_insert(0, "123")  # node 2: 123ABCDEF (new branch)
        assert tree.current_text() == "123ABCDEF"
        tree.undo()  # back to root
        assert tree.get_children_count() == 2

    def test_navigate_multiple_branches(self):
        tree = UndoTree("ROOT")
        tree.apply_insert(4, "-A")  # node 1
        tree.undo()
        tree.apply_insert(4, "-B")  # node 2
        tree.undo()
        tree.apply_insert(4, "-C")  # node 3
        tree.undo()

        assert tree.get_children_count() == 3

        tree.redo(0)
        assert tree.current_text() == "ROOT-A"
        tree.undo()

        tree.redo(1)
        assert tree.current_text() == "ROOT-B"
        tree.undo()

        tree.redo(2)
        assert tree.current_text() == "ROOT-C"

    def test_deep_branching(self):
        tree = UndoTree("X")
        tree.apply_insert(1, "A")  # node 1: XA
        tree.apply_insert(2, "B")  # node 2: XAB
        tree.apply_insert(3, "C")  # node 3: XABC

        tree.undo()  # XAB
        tree.undo()  # XA (node 1)

        tree.apply_insert(2, "D")  # node 4: XAD
        tree.apply_insert(3, "E")  # node 5: XADE

        # Go back to node 1 (XA)
        tree.undo()  # XAD (node 4)
        tree.undo()  # XA (node 1)

        assert tree.get_children_count() == 2

        # Branch 0: XAB -> XABC
        tree.redo(0)
        assert tree.current_text() == "XAB"
        tree.redo(0)
        assert tree.current_text() == "XABC"

        # Go back to node 1 and take branch 1
        tree.undo()
        tree.undo()
        tree.redo(1)
        assert tree.current_text() == "XAD"
        tree.redo(0)
        assert tree.current_text() == "XADE"

    def test_get_node_text_across_branches(self):
        tree = UndoTree("START")
        tree.apply_insert(5, "1")  # node 1: START1
        tree.apply_insert(6, "2")  # node 2: START12
        tree.undo()  # START1
        tree.apply_insert(6, "3")  # node 3: START13 (branch)

        assert tree.get_node_text(0) == "START"
        assert tree.get_node_text(1) == "START1"
        assert tree.get_node_text(2) == "START12"
        assert tree.get_node_text(3) == "START13"

    def test_tree_structure_format(self):
        tree = UndoTree("R")
        tree.apply_insert(1, "A")  # node 1
        tree.undo()
        tree.apply_insert(1, "B")  # node 2

        structure = tree.get_tree_structure()
        assert structure["id"] == 0
        assert len(structure["children"]) == 2
        assert structure["children"][0]["id"] == 1
        assert structure["children"][1]["id"] == 2
        assert structure["children"][0]["children"] == []
        assert structure["children"][1]["children"] == []


# ====================================================================
# UndoTree: Delete Operations
# ====================================================================


class TestUndoTreeWithDelete:
    def test_delete_and_undo(self):
        tree = UndoTree("Hello World")
        tree.apply_delete(5, 6)
        assert tree.current_text() == "Hello"
        tree.undo()
        assert tree.current_text() == "Hello World"

    def test_mixed_insert_delete_branching(self):
        tree = UndoTree("ABCDEF")
        tree.apply_delete(2, 2)  # node 1: ABEF
        tree.apply_insert(2, "XY")  # node 2: ABXYEF
        tree.undo()  # ABEF
        tree.undo()  # ABCDEF
        tree.apply_delete(0, 3)  # node 3: DEF (new branch)
        assert tree.current_text() == "DEF"
        tree.undo()
        tree.redo(0)
        assert tree.current_text() == "ABEF"


# ====================================================================
# Myers Diff
# ====================================================================


class TestMyersDiff:
    def test_identical_texts(self):
        result = myers_diff("A\nB\nC\n", "A\nB\nC\n")
        assert all(line.startswith(" ") for line in result)
        assert len(result) == 3

    def test_both_empty(self):
        result = myers_diff("", "")
        assert result == []

    def test_empty_to_text(self):
        result = myers_diff("", "A\nB\n")
        assert result == ["+A", "+B"]

    def test_text_to_empty(self):
        result = myers_diff("A\nB\n", "")
        assert result == ["-A", "-B"]

    def test_single_insertion(self):
        result = myers_diff("A\nC\n", "A\nB\nC\n")
        assert result == [" A", "+B", " C"]

    def test_single_deletion(self):
        result = myers_diff("A\nB\nC\n", "A\nC\n")
        assert result == [" A", "-B", " C"]

    def test_single_replacement(self):
        result = myers_diff("A\nB\nC\n", "A\nX\nC\n")
        assert result == [" A", "-B", "+X", " C"]

    def test_append_lines(self):
        result = myers_diff("A\nB\n", "A\nB\nC\n")
        assert result == [" A", " B", "+C"]

    def test_complex_diff_validity(self):
        """Applying the diff to text_a must reconstruct text_b."""
        text_a = "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\n"
        text_b = "alpha\nBETA\ngamma\neta\nepsilon\ntheta\nzeta\n"
        result = myers_diff(text_a, text_b)

        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()
        reconstructed = []
        a_idx = 0

        for entry in result:
            op = entry[0]
            content = entry[1:]
            if op == " ":
                assert a_idx < len(lines_a)
                assert content == lines_a[a_idx]
                reconstructed.append(content)
                a_idx += 1
            elif op == "-":
                assert a_idx < len(lines_a)
                assert content == lines_a[a_idx]
                a_idx += 1
            elif op == "+":
                reconstructed.append(content)

        assert a_idx == len(lines_a)
        assert reconstructed == lines_b

    def test_diff_minimality_replacement(self):
        """Edit distance for replacing one line should be exactly 2."""
        text_a = "A\nB\nC\nD\n"
        text_b = "A\nX\nC\nD\n"
        result = myers_diff(text_a, text_b)
        edits = sum(1 for line in result if line[0] in "+-")
        assert edits == 2

    def test_diff_minimality_insertion(self):
        """Edit distance for inserting one line should be exactly 1."""
        text_a = "A\nC\n"
        text_b = "A\nB\nC\n"
        result = myers_diff(text_a, text_b)
        edits = sum(1 for line in result if line[0] in "+-")
        assert edits == 1

    def test_diff_minimality_multiple(self):
        """Edit distance for a known case with 3 edits."""
        text_a = "A\nB\nC\nD\nE\nF\n"
        text_b = "A\nB\nX\nC\nY\nE\nF\n"
        result = myers_diff(text_a, text_b)

        # Verify validity by reconstruction
        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()
        reconstructed = []
        a_idx = 0
        for entry in result:
            op = entry[0]
            content = entry[1:]
            if op == " ":
                reconstructed.append(content)
                a_idx += 1
            elif op == "-":
                a_idx += 1
            elif op == "+":
                reconstructed.append(content)
        assert reconstructed == lines_b
        assert a_idx == len(lines_a)

        # Edit distance should be 3 (insert X, delete D, insert Y)
        edits = sum(1 for line in result if line[0] in "+-")
        assert edits == 3


# ====================================================================
# Integration
# ====================================================================


class TestIntegration:
    def test_diff_between_undo_tree_states(self):
        tree = UndoTree("Line1\nLine2\nLine3\n")
        tree.apply_insert(len("Line1\n"), "NewLine\n")
        # State 0: "Line1\nLine2\nLine3\n"
        # State 1: "Line1\nNewLine\nLine2\nLine3\n"

        text_0 = tree.get_node_text(0)
        text_1 = tree.get_node_text(1)

        diff = myers_diff(text_0, text_1)

        # Verify the diff is valid
        lines_a = text_0.splitlines()
        lines_b = text_1.splitlines()
        reconstructed = []
        a_idx = 0
        for entry in diff:
            op = entry[0]
            content = entry[1:]
            if op == " ":
                reconstructed.append(content)
                a_idx += 1
            elif op == "-":
                a_idx += 1
            elif op == "+":
                reconstructed.append(content)
        assert reconstructed == lines_b
        assert a_idx == len(lines_a)

    def test_complex_editing_workflow(self):
        """Simulate a realistic editing session with branching and diffing."""
        tree = UndoTree("fn main() {\n    println!(\"hello\");\n}\n")

        # Branch 1: Add a parameter
        tree.apply_insert(len("fn main("), "args: Vec<String>")
        branch1_text = tree.current_text()
        assert "args: Vec<String>" in branch1_text
        node1_id = tree.current_node_id

        # Undo and create branch 2: Add a comment instead
        tree.undo()
        tree.apply_insert(0, "// Entry point\n")
        branch2_text = tree.current_text()
        assert "// Entry point" in branch2_text
        node2_id = tree.current_node_id

        # Both branches accessible from root
        tree.undo()
        assert tree.get_children_count() == 2

        # Diff between branch 1 and branch 2
        text_b1 = tree.get_node_text(node1_id)
        text_b2 = tree.get_node_text(node2_id)
        diff = myers_diff(text_b1, text_b2)

        # Verify the diff transforms branch1 into branch2
        lines_a = text_b1.splitlines()
        lines_b = text_b2.splitlines()
        reconstructed = []
        a_idx = 0
        for entry in diff:
            op = entry[0]
            content = entry[1:]
            if op == " ":
                reconstructed.append(content)
                a_idx += 1
            elif op == "-":
                a_idx += 1
            elif op == "+":
                reconstructed.append(content)
        assert reconstructed == lines_b
        assert a_idx == len(lines_a)

    def test_persistence_under_branching_undo(self):
        """Piece tables in undo tree must be truly persistent."""
        tree = UndoTree("ORIGINAL")

        tree.apply_insert(8, "_V1")  # node 1: ORIGINAL_V1
        tree.apply_insert(11, "_V2")  # node 2: ORIGINAL_V1_V2

        tree.undo()  # ORIGINAL_V1
        tree.apply_delete(0, 8)  # node 3: _V1 (branch from node 1)

        tree.undo()  # ORIGINAL_V1
        tree.undo()  # ORIGINAL

        # All states must be independently valid
        assert tree.get_node_text(0) == "ORIGINAL"
        assert tree.get_node_text(1) == "ORIGINAL_V1"
        assert tree.get_node_text(2) == "ORIGINAL_V1_V2"
        assert tree.get_node_text(3) == "_V1"


# ====================================================================
# Merge Branches
# ====================================================================


class TestMergeBranches:
    def test_merge_non_conflicting(self):
        """Non-overlapping edits from two branches should be combined."""
        tree = UndoTree("aaa\nbbb\nccc\n")
        # Branch A: replace line 2 (bbb -> XXX)
        tree.apply_delete(4, 4)    # node 1: "aaa\nccc\n"
        tree.apply_insert(4, "XXX\n")  # node 2: "aaa\nXXX\nccc\n"
        node_a = tree.current_node_id

        tree.undo()  # node 1
        tree.undo()  # root

        # Branch B: replace line 3 (ccc -> YYY)
        tree.apply_delete(8, 4)    # node 3: "aaa\nbbb\n"
        tree.apply_insert(8, "YYY\n")  # node 4: "aaa\nbbb\nYYY\n"
        node_b = tree.current_node_id

        merge_id = tree.merge_branches(node_a, node_b)
        merged = tree.get_node_text(merge_id)
        assert merged == "aaa\nXXX\nYYY\n"

    def test_merge_conflicting(self):
        """Same region modified differently -> conflict markers."""
        tree = UndoTree("aaa\nbbb\nccc\n")
        # Branch A: replace bbb with XXX
        tree.apply_delete(4, 4)
        tree.apply_insert(4, "XXX\n")
        node_a = tree.current_node_id

        tree.undo()
        tree.undo()

        # Branch B: replace bbb with ZZZ
        tree.apply_delete(4, 4)
        tree.apply_insert(4, "ZZZ\n")
        node_b = tree.current_node_id

        merge_id = tree.merge_branches(node_a, node_b)
        merged = tree.get_node_text(merge_id)
        assert "<<<<<<< branch_a" in merged
        assert "XXX" in merged
        assert "=======" in merged
        assert "ZZZ" in merged
        assert ">>>>>>> branch_b" in merged
        # Unchanged lines should be preserved
        assert merged.startswith("aaa\n")
        assert merged.endswith("ccc\n")

    def test_merge_identical_changes(self):
        """Same change in both branches -> no conflict."""
        tree = UndoTree("aaa\nbbb\nccc\n")
        # Both branches replace bbb with XXX
        tree.apply_delete(4, 4)
        tree.apply_insert(4, "XXX\n")
        node_a = tree.current_node_id

        tree.undo()
        tree.undo()

        tree.apply_delete(4, 4)
        tree.apply_insert(4, "XXX\n")
        node_b = tree.current_node_id

        merge_id = tree.merge_branches(node_a, node_b)
        merged = tree.get_node_text(merge_id)
        assert merged == "aaa\nXXX\nccc\n"
        assert "<<<<<<" not in merged

    def test_merge_one_branch_unchanged(self):
        """One branch unchanged -> take the other branch's changes."""
        tree = UndoTree("aaa\nbbb\nccc\n")
        # Branch A: no changes (just the root)
        node_a = tree.current_node_id  # root

        # Branch B: modify
        tree.apply_delete(4, 4)
        tree.apply_insert(4, "ZZZ\n")
        node_b = tree.current_node_id

        merge_id = tree.merge_branches(node_a, node_b)
        merged = tree.get_node_text(merge_id)
        assert merged == "aaa\nZZZ\nccc\n"

    def test_merge_lca_not_root(self):
        """LCA should be correctly identified as a non-root node."""
        tree = UndoTree("base\n")
        tree.apply_insert(5, "shared\n")  # node 1: "base\nshared\n"

        # Branch A from node 1: prepend a line
        tree.apply_insert(0, "prefix_a\n")  # node 2: "prefix_a\nbase\nshared\n"
        node_a = tree.current_node_id

        tree.undo()  # back to node 1

        # Branch B from node 1: append a line
        tree.apply_insert(12, "suffix_b\n")  # node 3: "base\nshared\nsuffix_b\n"
        node_b = tree.current_node_id

        merge_id = tree.merge_branches(node_a, node_b)
        merged = tree.get_node_text(merge_id)
        # LCA is node 1 ("base\nshared\n")
        # A prepends prefix_a, B appends suffix_b — non-overlapping
        assert "prefix_a" in merged
        assert "suffix_b" in merged
        assert "base" in merged
        assert "shared" in merged

    def test_merge_creates_node_under_lca(self):
        """The merged node must be a child of the LCA."""
        tree = UndoTree("root\n")
        tree.apply_insert(5, "A\n")  # node 1
        node_a = tree.current_node_id
        tree.undo()
        tree.apply_insert(5, "B\n")  # node 2
        node_b = tree.current_node_id

        tree.undo()  # back to root
        assert tree.get_children_count() == 2

        merge_id = tree.merge_branches(node_a, node_b)
        # Merged node should be a child of the LCA (root)
        assert tree.get_children_count() == 3
        # Merged node text is accessible
        merged = tree.get_node_text(merge_id)
        assert "root" in merged


# ====================================================================
# Session Store
# ====================================================================


class TestSessionStore:
    @pytest.fixture
    def db_path(self, tmp_path):
        db = str(tmp_path / "test_sessions.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE sessions "
            "(session_id TEXT PRIMARY KEY, initial_text TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE operations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL, "
            "seq INTEGER NOT NULL, "
            "op_type TEXT NOT NULL, "
            "offset INTEGER, "
            "length INTEGER, "
            "text TEXT, "
            "branch INTEGER DEFAULT 0)"
        )
        # Simple session: insert " World" at offset 5
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?)", ("s1", "Hello")
        )
        conn.execute(
            "INSERT INTO operations (session_id, seq, op_type, offset, text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("s1", 1, "insert", 5, " World"),
        )
        conn.commit()
        conn.close()
        return db

    def test_list_sessions(self, db_path):
        store = SessionStore(db_path)
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "s1"
        assert sessions[0]["initial_text"] == "Hello"

    def test_replay_session_basic(self, db_path):
        store = SessionStore(db_path)
        tree = store.replay_session("s1")
        assert tree.current_text() == "Hello World"

    def test_record_operation(self, db_path):
        store = SessionStore(db_path)
        store.record_operation("s1", 2, "insert", offset=11, text="!")
        # Verify by replaying: should now be "Hello World!"
        tree = store.replay_session("s1")
        assert tree.current_text() == "Hello World!"

    def test_replay_with_branching(self, db_path):
        """Replay a session that includes undo, creating branches."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?)", ("s2", "AB")
        )
        conn.execute(
            "INSERT INTO operations (session_id, seq, op_type, offset, text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("s2", 1, "insert", 2, "C"),
        )
        conn.execute(
            "INSERT INTO operations (session_id, seq, op_type) "
            "VALUES (?, ?, ?)",
            ("s2", 2, "undo"),
        )
        conn.execute(
            "INSERT INTO operations (session_id, seq, op_type, offset, text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("s2", 3, "insert", 2, "D"),
        )
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        tree = store.replay_session("s2")

        # Current state after replay: ABD
        assert tree.current_text() == "ABD"

        # Should have branching structure
        tree.undo()  # back to root AB
        assert tree.current_text() == "AB"
        assert tree.get_children_count() == 2

        # Navigate branches
        tree.redo(0)
        assert tree.current_text() == "ABC"
        tree.undo()
        tree.redo(1)
        assert tree.current_text() == "ABD"

    def test_replay_with_delete(self, db_path):
        """Replay a session that includes delete operations."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?)", ("s3", "Hello World")
        )
        conn.execute(
            "INSERT INTO operations (session_id, seq, op_type, offset, length) "
            "VALUES (?, ?, ?, ?, ?)",
            ("s3", 1, "delete", 5, 6),
        )
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        tree = store.replay_session("s3")
        assert tree.current_text() == "Hello"

    def test_replay_unknown_session_raises(self, db_path):
        store = SessionStore(db_path)
        with pytest.raises(KeyError):
            store.replay_session("nonexistent")

    def test_record_and_replay_roundtrip(self, db_path):
        """Record a sequence of operations, then replay to verify."""
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?)", ("s4", "START")
        )
        conn.commit()
        conn.close()

        store = SessionStore(db_path)
        store.record_operation("s4", 1, "insert", offset=5, text="_MID")
        store.record_operation("s4", 2, "insert", offset=9, text="_END")

        tree = store.replay_session("s4")
        assert tree.current_text() == "START_MID_END"
