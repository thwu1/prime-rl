
"""Fixed edit history with tree-structured undo/redo and branch merging."""

from __future__ import annotations
import difflib
from typing import List, Optional, Dict
from buffer import PieceTable


class _UndoTreeNode:
    __slots__ = ("id", "piece_table", "parent", "children")

    def __init__(
        self,
        node_id: int,
        piece_table: PieceTable,
        parent: Optional["_UndoTreeNode"] = None,
    ):
        self.id = node_id
        self.piece_table = piece_table
        self.parent = parent
        self.children: List["_UndoTreeNode"] = []


class UndoTree:
    """Tree-structured undo/redo history over PieceTable states.

    Editing after an undo creates a new branch rather than discarding the
    existing redo path.
    """

    def __init__(self, initial_text: str):
        pt = PieceTable(initial_text)
        self._root = _UndoTreeNode(0, pt)
        self._current = self._root
        self._next_id = 1
        self._nodes: Dict[int, _UndoTreeNode] = {0: self._root}

    # -- properties ----------------------------------------------------------

    @property
    def current_node_id(self) -> int:
        return self._current.id

    # -- queries -------------------------------------------------------------

    def current_text(self) -> str:
        return self._current.piece_table.get_text()

    def get_node_text(self, node_id: int) -> str:
        return self._nodes[node_id].piece_table.get_text()

    def get_children_count(self) -> int:
        return len(self._current.children)

    def get_tree_structure(self) -> dict:
        def _build(node: _UndoTreeNode) -> dict:
            return {
                "id": node.id,
                "children": [_build(c) for c in node.children],
            }

        return _build(self._root)

    # -- mutations -----------------------------------------------------------

    def _add_child(self, new_pt: PieceTable) -> None:
        node = _UndoTreeNode(self._next_id, new_pt, self._current)
        self._current.children.append(node)
        self._nodes[self._next_id] = node
        self._next_id += 1
        self._current = node

    def apply_insert(self, offset: int, text: str) -> None:
        new_pt = self._current.piece_table.insert(offset, text)
        self._add_child(new_pt)

    def apply_delete(self, offset: int, length: int) -> None:
        new_pt = self._current.piece_table.delete(offset, length)
        self._add_child(new_pt)

    def undo(self) -> bool:
        if self._current.parent is None:
            return False
        self._current = self._current.parent
        return True

    def redo(self, branch: int = 0) -> bool:
        if branch < 0 or branch >= len(self._current.children):
            return False
        self._current = self._current.children[branch]
        return True

    # -- merge ---------------------------------------------------------------

    def merge_branches(self, node_id_a: int, node_id_b: int) -> int:
        """3-way merge of two branch tips via their lowest common ancestor.

        Finds the LCA, computes line-level diffs from LCA to each tip,
        and creates a merged node under the LCA. Returns the new node's ID.
        """
        node_a = self._nodes[node_id_a]
        node_b = self._nodes[node_id_b]

        # Find LCA by collecting ancestors of A, then walking up from B
        ancestors_a: set = set()
        cur = node_a
        while cur is not None:
            ancestors_a.add(cur.id)
            cur = cur.parent

        lca = node_b
        while lca.id not in ancestors_a:
            lca = lca.parent

        base_text = lca.piece_table.get_text()
        text_a = node_a.piece_table.get_text()
        text_b = node_b.piece_table.get_text()

        merged_text = _merge_texts(base_text, text_a, text_b)
        merged_pt = PieceTable(merged_text)

        node = _UndoTreeNode(self._next_id, merged_pt, lca)
        lca.children.append(node)
        self._nodes[self._next_id] = node
        result_id = self._next_id
        self._next_id += 1
        return result_id


# ---------------------------------------------------------------------------
# 3-way merge helper
# ---------------------------------------------------------------------------


def _merge_texts(base_text: str, text_a: str, text_b: str) -> str:
    """Line-level 3-way merge with conflict markers.

    Uses difflib.SequenceMatcher to find change regions in each branch
    relative to the base, then merges non-overlapping changes and marks
    conflicts for overlapping regions with different content.
    """
    if text_a == base_text:
        return text_b
    if text_b == base_text:
        return text_a
    if text_a == text_b:
        return text_a

    base = base_text.splitlines(True) if base_text else []
    a = text_a.splitlines(True) if text_a else []
    b = text_b.splitlines(True) if text_b else []

    ops_a = list(
        difflib.SequenceMatcher(None, base, a, autojunk=False).get_opcodes()
    )
    ops_b = list(
        difflib.SequenceMatcher(None, base, b, autojunk=False).get_opcodes()
    )

    def get_edits(opcodes, mod):
        edits = []
        for tag, i1, i2, j1, j2 in opcodes:
            if tag != "equal":
                edits.append((i1, i2, mod[j1:j2]))
        return edits

    edits_a = get_edits(ops_a, a)
    edits_b = get_edits(ops_b, b)

    # Match overlapping edits between branches
    used_b: set = set()
    merged_edits = []

    for _ia, (a1, a2, ra) in enumerate(edits_a):
        overlap_idx = None
        for ib, (b1, b2, _rb) in enumerate(edits_b):
            if ib in used_b:
                continue
            if a1 < b2 and b1 < a2:  # ranges overlap
                overlap_idx = ib
                break

        if overlap_idx is None:
            merged_edits.append((a1, a2, list(ra)))
        else:
            used_b.add(overlap_idx)
            b1, b2, rb = edits_b[overlap_idx]
            start = min(a1, b1)
            end = max(a2, b2)
            if list(ra) == list(rb):
                merged_edits.append((start, end, list(ra)))
            else:
                conflict = (
                    ["<<<<<<< branch_a\n"]
                    + list(ra)
                    + ["=======\n"]
                    + list(rb)
                    + [">>>>>>> branch_b\n"]
                )
                merged_edits.append((start, end, conflict))

    # Add B-only edits that had no overlap with A
    for ib, (b1, b2, rb) in enumerate(edits_b):
        if ib not in used_b:
            merged_edits.append((b1, b2, list(rb)))

    merged_edits.sort(key=lambda x: x[0])

    # Apply merged edits to base
    result: List[str] = []
    pos = 0
    for start, end, repl in merged_edits:
        result.extend(base[pos:start])
        result.extend(repl)
        pos = end
    result.extend(base[pos:])

    return "".join(result)
