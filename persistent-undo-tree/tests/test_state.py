
"""Tests for the persistent text buffer with branching undo."""

import pytest
import sys
sys.path.insert(0, '/app')

from text_buffer import TextBuffer
from piece_table import PieceTable
from undo_tree import UndoTree
from myers_diff import myers_diff


def _apply_diff(original, diff_ops):
    """Apply a diff to transform original into the target string."""
    result = []
    orig_idx = 0
    for op, char in diff_ops:
        if op == 'equal':
            assert orig_idx < len(original), f"equal past end of original at {orig_idx}"
            assert original[orig_idx] == char, (
                f"equal mismatch at {orig_idx}: expected {original[orig_idx]!r}, got {char!r}"
            )
            result.append(char)
            orig_idx += 1
        elif op == 'delete':
            assert orig_idx < len(original), f"delete past end of original at {orig_idx}"
            assert original[orig_idx] == char, (
                f"delete mismatch at {orig_idx}: expected {original[orig_idx]!r}, got {char!r}"
            )
            orig_idx += 1
        elif op == 'insert':
            result.append(char)
        else:
            raise ValueError(f"Unknown op: {op!r}")
    assert orig_idx == len(original), f"Did not consume all of original ({orig_idx}/{len(original)})"
    return "".join(result)


# ─── Piece Table Tests ───


class TestPieceTable:
    def test_empty_buffer(self):
        pt = PieceTable()
        assert pt.get_text() == ""
        assert pt.length() == 0

    def test_initial_text(self):
        pt = PieceTable("Hello World")
        assert pt.get_text() == "Hello World"
        assert pt.length() == 11

    def test_insert_beginning(self):
        pt = PieceTable("World")
        pt2 = pt.insert(0, "Hello ")
        assert pt2.get_text() == "Hello World"
        assert pt.get_text() == "World"

    def test_insert_end(self):
        pt = PieceTable("Hello")
        pt2 = pt.insert(5, " World")
        assert pt2.get_text() == "Hello World"

    def test_insert_middle(self):
        pt = PieceTable("Helo")
        pt2 = pt.insert(2, "l")
        assert pt2.get_text() == "Hello"

    def test_delete_beginning(self):
        pt = PieceTable("Hello World")
        pt2 = pt.delete(0, 6)
        assert pt2.get_text() == "World"
        assert pt.get_text() == "Hello World"

    def test_delete_end(self):
        pt = PieceTable("Hello World")
        pt2 = pt.delete(5, 6)
        assert pt2.get_text() == "Hello"

    def test_delete_middle(self):
        pt = PieceTable("Hello World")
        pt2 = pt.delete(4, 3)
        assert pt2.get_text() == "Hellorld"

    def test_persistence_chain(self):
        pt1 = PieceTable("ABC")
        pt2 = pt1.insert(3, "DEF")
        pt3 = pt2.delete(0, 1)
        assert pt1.get_text() == "ABC"
        assert pt2.get_text() == "ABCDEF"
        assert pt3.get_text() == "BCDEF"

    def test_sequential_inserts(self):
        pt = PieceTable("")
        pt = pt.insert(0, "C")
        pt = pt.insert(0, "A")
        pt = pt.insert(1, "B")
        assert pt.get_text() == "ABC"

    def test_complex_operations(self):
        pt = PieceTable("Hello")
        pt = pt.insert(5, " World")
        pt = pt.delete(5, 1)
        pt = pt.insert(5, " Beautiful ")
        pt = pt.delete(0, 6)
        assert pt.get_text() == "Beautiful World"

    def test_delete_spanning_pieces(self):
        pt = PieceTable("ABCDE")
        pt = pt.insert(2, "XX")  # "ABXXCDE"
        pt = pt.delete(1, 4)     # delete "BXXC" -> "ADE"
        assert pt.get_text() == "ADE"


# ─── Undo Tree Tests ───


class TestUndoTree:
    def test_basic_undo(self):
        pt0 = PieceTable("Hello")
        tree = UndoTree(pt0)
        pt1 = pt0.insert(5, " World")
        tree.record(pt1, "add World")
        result = tree.undo()
        assert result is not None
        assert result.get_text() == "Hello"

    def test_basic_redo(self):
        pt0 = PieceTable("Hello")
        tree = UndoTree(pt0)
        pt1 = pt0.insert(5, " World")
        tree.record(pt1)
        tree.undo()
        result = tree.redo()
        assert result is not None
        assert result.get_text() == "Hello World"

    def test_undo_at_root(self):
        tree = UndoTree(PieceTable("Hello"))
        assert tree.undo() is None

    def test_redo_at_leaf(self):
        tree = UndoTree(PieceTable("Hello"))
        assert tree.redo() is None

    def test_redo_invalid_branch(self):
        pt0 = PieceTable("Hello")
        tree = UndoTree(pt0)
        tree.record(pt0.insert(5, " World"))
        tree.undo()
        assert tree.redo(1) is None  # only branch 0 exists

    def test_branching(self):
        pt0 = PieceTable("Hello")
        tree = UndoTree(pt0)
        tree.record(pt0.insert(5, " World"))
        tree.undo()
        tree.record(pt0.insert(5, " Python"))
        root = tree.get_node(0)
        assert len(root.children_ids) == 2

    def test_branching_redo_selection(self):
        pt0 = PieceTable("Hello")
        tree = UndoTree(pt0)
        tree.record(pt0.insert(5, " World"))
        tree.undo()
        tree.record(pt0.insert(5, " Python"))
        tree.undo()

        r0 = tree.redo(0)
        assert r0 is not None
        assert r0.get_text() == "Hello World"
        tree.undo()

        r1 = tree.redo(1)
        assert r1 is not None
        assert r1.get_text() == "Hello Python"

    def test_navigate_to(self):
        pt0 = PieceTable("A")
        tree = UndoTree(pt0)
        pt1 = pt0.insert(1, "B")
        s1 = tree.record(pt1)
        pt2 = pt1.insert(2, "C")
        s2 = tree.record(pt2)
        s3 = tree.record(pt2.insert(3, "D"))

        result = tree.navigate_to(s1)
        assert result is not None
        assert result.get_text() == "AB"
        assert tree.current_id == s1

    def test_navigate_invalid(self):
        tree = UndoTree(PieceTable("X"))
        assert tree.navigate_to(999) is None

    def test_path_linear(self):
        pt0 = PieceTable("A")
        tree = UndoTree(pt0)
        s1 = tree.record(pt0.insert(1, "B"))
        s2 = tree.record(PieceTable("ABC"))
        path = tree.get_path(0, s2)
        assert path == [0, s1, s2]

    def test_path_with_lca(self):
        pt0 = PieceTable("A")
        tree = UndoTree(pt0)

        pt1 = pt0.insert(1, "B")
        s1 = tree.record(pt1)
        s2 = tree.record(pt1.insert(2, "C"))

        tree.navigate_to(0)
        pt3 = pt0.insert(1, "X")
        s3 = tree.record(pt3)
        s4 = tree.record(pt3.insert(2, "Y"))

        path = tree.get_path(s2, s4)
        assert path is not None
        assert path[0] == s2
        assert path[-1] == s4
        assert 0 in path
        assert path == [s2, s1, 0, s3, s4]

    def test_path_invalid(self):
        tree = UndoTree(PieceTable("A"))
        assert tree.get_path(0, 999) is None

    def test_path_same_node(self):
        tree = UndoTree(PieceTable("A"))
        assert tree.get_path(0, 0) == [0]

    def test_path_parent_child(self):
        pt0 = PieceTable("A")
        tree = UndoTree(pt0)
        s1 = tree.record(pt0.insert(1, "B"))
        path = tree.get_path(0, s1)
        assert path == [0, s1]
        path2 = tree.get_path(s1, 0)
        assert path2 == [s1, 0]


# ─── Myers Diff Tests ───


class TestMyersDiff:
    def test_identical(self):
        result = myers_diff("abc", "abc")
        assert all(op == 'equal' for op, _ in result)
        assert "".join(c for _, c in result if True) == "abc"

    def test_empty_to_nonempty(self):
        result = myers_diff("", "abc")
        assert result == [('insert', 'a'), ('insert', 'b'), ('insert', 'c')]

    def test_nonempty_to_empty(self):
        result = myers_diff("abc", "")
        assert result == [('delete', 'a'), ('delete', 'b'), ('delete', 'c')]

    def test_both_empty(self):
        result = myers_diff("", "")
        assert result == []

    def test_single_insert(self):
        result = myers_diff("ac", "abc")
        assert _apply_diff("ac", result) == "abc"

    def test_single_delete(self):
        result = myers_diff("abc", "ac")
        assert _apply_diff("abc", result) == "ac"

    def test_substitution(self):
        result = myers_diff("abc", "axc")
        assert _apply_diff("abc", result) == "axc"

    def test_classic_example(self):
        result = myers_diff("ABCABBA", "CBABAC")
        assert _apply_diff("ABCABBA", result) == "CBABAC"

    def test_classic_minimality(self):
        result = myers_diff("ABCABBA", "CBABAC")
        edits = sum(1 for op, _ in result if op != 'equal')
        assert edits == 5

    def test_prefix_addition(self):
        result = myers_diff("World", "Hello World")
        assert _apply_diff("World", result) == "Hello World"

    def test_suffix_addition(self):
        result = myers_diff("Hello", "Hello World")
        assert _apply_diff("Hello", result) == "Hello World"

    def test_repeated_chars(self):
        result = myers_diff("aaaa", "aabaa")
        assert _apply_diff("aaaa", result) == "aabaa"

    def test_complete_replacement(self):
        result = myers_diff("abc", "xyz")
        assert _apply_diff("abc", result) == "xyz"

    def test_roundtrip_corpus(self):
        pairs = [
            ("kitten", "sitting"),
            ("Saturday", "Sunday"),
            ("", "nonempty"),
            ("nonempty", ""),
            ("same", "same"),
            ("a", "b"),
            ("ab", "ba"),
            ("abcdef", "azced"),
            ("the quick brown fox", "the slow red fox"),
            ("line1\nline2\nline3", "line1\nmodified\nline3\nnew"),
        ]
        for a, b in pairs:
            result = myers_diff(a, b)
            assert _apply_diff(a, result) == b, f"Failed for {a!r} -> {b!r}"


# ─── Text Buffer Integration Tests ───


class TestTextBuffer:
    def test_basic_insert(self):
        buf = TextBuffer("Hello")
        buf.insert(5, " World")
        assert buf.get_text() == "Hello World"

    def test_undo_redo(self):
        buf = TextBuffer("Hello")
        buf.insert(5, " World")
        assert buf.get_text() == "Hello World"
        buf.undo()
        assert buf.get_text() == "Hello"
        buf.redo()
        assert buf.get_text() == "Hello World"

    def test_branching_undo(self):
        buf = TextBuffer("Hello")
        buf.insert(5, " World")
        buf.undo()
        assert buf.get_text() == "Hello"
        buf.insert(5, " Python")
        assert buf.get_text() == "Hello Python"
        buf.undo()
        assert buf.num_redo_branches() == 2
        buf.redo(0)
        assert buf.get_text() == "Hello World"
        buf.undo()
        buf.redo(1)
        assert buf.get_text() == "Hello Python"

    def test_navigate_to(self):
        buf = TextBuffer("A")
        s1 = buf.insert(1, "B")
        s2 = buf.insert(2, "C")
        s3 = buf.insert(3, "D")
        buf.navigate_to(s1)
        assert buf.get_text() == "AB"
        buf.navigate_to(s3)
        assert buf.get_text() == "ABCD"

    def test_get_state_text(self):
        buf = TextBuffer("A")
        s1 = buf.insert(1, "B")
        s2 = buf.insert(2, "C")
        assert buf.get_state_text(0) == "A"
        assert buf.get_state_text(s1) == "AB"
        assert buf.get_state_text(s2) == "ABC"
        assert buf.get_state_text(999) is None

    def test_diff_adjacent_states(self):
        buf = TextBuffer("Hello")
        s0 = buf.current_state_id
        s1 = buf.insert(5, " World")
        diff = buf.diff(s0, s1)
        assert diff is not None
        text_a = buf.get_state_text(s0)
        assert _apply_diff(text_a, diff) == buf.get_state_text(s1)

    def test_diff_across_branches(self):
        buf = TextBuffer("Hello")
        s0 = buf.current_state_id
        s1 = buf.insert(5, " World")
        buf.undo()
        s2 = buf.insert(5, " Python")
        diff = buf.diff(s1, s2)
        assert diff is not None
        assert _apply_diff(buf.get_state_text(s1), diff) == buf.get_state_text(s2)

    def test_diff_invalid_state(self):
        buf = TextBuffer("Hello")
        assert buf.diff(0, 999) is None

    def test_complex_branching(self):
        buf = TextBuffer("")
        buf.insert(0, "function")
        buf.insert(8, "()")
        s_base = buf.insert(10, " {}")

        s_branch1 = buf.insert(12, "\n  return 42;\n")
        buf.navigate_to(s_base)
        s_branch2 = buf.insert(12, "\n  console.log('hello');\n")

        assert buf.get_state_text(s_branch1) == "function() {\n  return 42;\n}"
        assert buf.get_state_text(s_branch2) == "function() {\n  console.log('hello');\n}"

        diff = buf.diff(s_branch1, s_branch2)
        assert diff is not None
        assert _apply_diff(buf.get_state_text(s_branch1), diff) == buf.get_state_text(s_branch2)

    def test_deep_undo_chain(self):
        buf = TextBuffer("")
        states = [buf.current_state_id]
        for i in range(10):
            sid = buf.insert(buf.length(), chr(65 + i))
            states.append(sid)
        assert buf.get_text() == "ABCDEFGHIJ"
        for _ in range(10):
            assert buf.undo()
        assert buf.get_text() == ""
        assert not buf.undo()
        for _ in range(10):
            assert buf.redo()
        assert buf.get_text() == "ABCDEFGHIJ"

    def test_multi_branch_tree(self):
        """Create a wide tree with 3 branches from root."""
        buf = TextBuffer("root")
        s0 = buf.current_state_id
        s1 = buf.insert(4, "-alpha")
        buf.navigate_to(s0)
        s2 = buf.insert(4, "-beta")
        buf.navigate_to(s0)
        s3 = buf.insert(4, "-gamma")

        assert buf.get_state_text(s1) == "root-alpha"
        assert buf.get_state_text(s2) == "root-beta"
        assert buf.get_state_text(s3) == "root-gamma"

        for sa, sb in [(s1, s2), (s2, s3), (s1, s3)]:
            diff = buf.diff(sa, sb)
            assert _apply_diff(buf.get_state_text(sa), diff) == buf.get_state_text(sb)

    def test_delete_and_reinsert(self):
        buf = TextBuffer("Hello World")
        s0 = buf.current_state_id
        s1 = buf.delete(5, 6)  # "Hello"
        s2 = buf.insert(5, " Python")  # "Hello Python"

        buf.undo()  # back to "Hello"
        buf.undo()  # back to "Hello World"
        assert buf.get_text() == "Hello World"

        diff = buf.diff(s0, s2)
        assert _apply_diff(buf.get_state_text(s0), diff) == buf.get_state_text(s2)

    def test_navigate_preserves_branches(self):
        """Navigating should not destroy any branches."""
        buf = TextBuffer("A")
        s1 = buf.insert(1, "B")
        buf.navigate_to(0)
        s2 = buf.insert(1, "X")
        buf.navigate_to(0)
        s3 = buf.insert(1, "Y")

        # Navigate around, all states should remain accessible
        buf.navigate_to(s1)
        assert buf.get_text() == "AB"
        buf.navigate_to(s2)
        assert buf.get_text() == "AX"
        buf.navigate_to(s3)
        assert buf.get_text() == "AY"
        buf.navigate_to(0)
        assert buf.get_text() == "A"

    def test_diff_between_deep_states(self):
        """Diff between states deep in different branches."""
        buf = TextBuffer("start")
        s0 = buf.current_state_id

        # Branch 1: start -> startAA -> startAABB
        s1 = buf.insert(5, "AA")
        s2 = buf.insert(7, "BB")

        buf.navigate_to(s0)

        # Branch 2: start -> startXX -> startXXYY -> startXXYYZZ
        s3 = buf.insert(5, "XX")
        s4 = buf.insert(7, "YY")
        s5 = buf.insert(9, "ZZ")

        # Diff between s2 (startAABB) and s5 (startXXYYZZ)
        diff = buf.diff(s2, s5)
        assert _apply_diff(buf.get_state_text(s2), diff) == buf.get_state_text(s5)
