
"""Persistent text buffer engine with branching undo/redo and Myers diff."""

from __future__ import annotations
from typing import List, Tuple, Optional, Dict

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORIGINAL_BUFFER = 0
_ADD_BUFFER = 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _BufferPool:
    """Shared append-only buffer pool for persistent piece tables.

    The original buffer is immutable; the add buffer only grows via append.
    Multiple PieceTable instances safely share a single pool.
    """

    def __init__(self, original_text: str):
        self._buffers: List[str] = [original_text, ""]

    def append_to_add(self, text: str) -> Tuple[int, int]:
        start = len(self._buffers[_ADD_BUFFER])
        self._buffers[_ADD_BUFFER] += text
        return start, len(text)

    def get_text(self, buffer_id: int, start: int, length: int) -> str:
        return self._buffers[buffer_id][start : start + length]


class _Piece:
    """Descriptor pointing into a contiguous region of a buffer."""

    __slots__ = ("buffer_id", "start", "length")

    def __init__(self, buffer_id: int, start: int, length: int):
        self.buffer_id = buffer_id
        self.start = start
        self.length = length


# ---------------------------------------------------------------------------
# PieceTable
# ---------------------------------------------------------------------------


class PieceTable:
    """Persistent piece-table text buffer.

    Every ``insert`` / ``delete`` returns a *new* PieceTable that shares the
    underlying buffer pool with all earlier versions.
    """

    # The constructor is overloaded:
    #   PieceTable("some text")           – public, creates pool + initial piece
    #   PieceTable(pool_obj, pieces_list) – internal, wraps existing pool
    def __init__(self, initial_text_or_pool, pieces=None):
        if isinstance(initial_text_or_pool, str):
            self._pool = _BufferPool(initial_text_or_pool)
            if initial_text_or_pool:
                self._pieces: List[_Piece] = [
                    _Piece(_ORIGINAL_BUFFER, 0, len(initial_text_or_pool))
                ]
            else:
                self._pieces = []
        else:
            self._pool = initial_text_or_pool
            self._pieces = pieces if pieces is not None else []

    # -- properties ----------------------------------------------------------

    @property
    def length(self) -> int:
        return sum(p.length for p in self._pieces)

    # -- queries -------------------------------------------------------------

    def get_text(self) -> str:
        parts: List[str] = []
        for p in self._pieces:
            parts.append(self._pool.get_text(p.buffer_id, p.start, p.length))
        return "".join(parts)

    # -- modifications (return new PieceTable) -------------------------------

    def insert(self, offset: int, text: str) -> "PieceTable":
        if not text:
            return PieceTable(
                self._pool, [_Piece(p.buffer_id, p.start, p.length) for p in self._pieces]
            )

        add_start, add_length = self._pool.append_to_add(text)
        new_piece = _Piece(_ADD_BUFFER, add_start, add_length)

        new_pieces: List[_Piece] = []
        inserted = False
        remaining = offset

        # Insert at the very start
        if remaining == 0:
            new_pieces.append(new_piece)
            inserted = True

        for p in self._pieces:
            if inserted:
                new_pieces.append(_Piece(p.buffer_id, p.start, p.length))
                continue

            if remaining >= p.length:
                new_pieces.append(_Piece(p.buffer_id, p.start, p.length))
                remaining -= p.length
                if remaining == 0:
                    new_pieces.append(new_piece)
                    inserted = True
            else:
                # Split this piece at *remaining*
                if remaining > 0:
                    new_pieces.append(_Piece(p.buffer_id, p.start, remaining))
                new_pieces.append(new_piece)
                tail = p.length - remaining
                if tail > 0:
                    new_pieces.append(
                        _Piece(p.buffer_id, p.start + remaining, tail)
                    )
                inserted = True

        if not inserted:
            new_pieces.append(new_piece)

        return PieceTable(self._pool, new_pieces)

    def delete(self, offset: int, length: int) -> "PieceTable":
        if length == 0:
            return PieceTable(
                self._pool, [_Piece(p.buffer_id, p.start, p.length) for p in self._pieces]
            )

        new_pieces: List[_Piece] = []
        rem_off = offset
        rem_del = length

        for p in self._pieces:
            if rem_del == 0:
                # Past the deletion window – copy verbatim
                new_pieces.append(_Piece(p.buffer_id, p.start, p.length))
            elif rem_off >= p.length:
                # Before the deletion window – copy verbatim
                new_pieces.append(_Piece(p.buffer_id, p.start, p.length))
                rem_off -= p.length
            elif rem_off > 0:
                # Deletion starts inside this piece
                new_pieces.append(_Piece(p.buffer_id, p.start, rem_off))
                del_here = min(rem_del, p.length - rem_off)
                rem_del -= del_here
                after = p.length - rem_off - del_here
                if after > 0:
                    new_pieces.append(
                        _Piece(p.buffer_id, p.start + rem_off + del_here, after)
                    )
                rem_off = 0
            else:
                # rem_off == 0, actively consuming the delete window
                del_here = min(rem_del, p.length)
                rem_del -= del_here
                if del_here < p.length:
                    new_pieces.append(
                        _Piece(
                            p.buffer_id, p.start + del_here, p.length - del_here
                        )
                    )

        return PieceTable(self._pool, new_pieces)


# ---------------------------------------------------------------------------
# UndoTree
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Myers Diff
# ---------------------------------------------------------------------------


def myers_diff(text_a: str, text_b: str) -> List[str]:
    """Compute a minimal line-based diff using the Myers O(ND) algorithm.

    Returns a list of strings, each prefixed with:
        ``' '`` – line kept (context)
        ``'-'`` – line removed from *text_a*
        ``'+'`` – line added from *text_b*
    """
    lines_a: List[str] = text_a.splitlines() if text_a else []
    lines_b: List[str] = text_b.splitlines() if text_b else []

    n, m = len(lines_a), len(lines_b)

    # Trivial cases
    if n == 0 and m == 0:
        return []
    if n == 0:
        return ["+" + ln for ln in lines_b]
    if m == 0:
        return ["-" + ln for ln in lines_a]

    max_d = n + m
    # v maps diagonal k -> furthest x reached on that diagonal
    v: Dict[int, int] = {1: 0}
    trace: List[Dict[int, int]] = []

    for d in range(max_d + 1):
        trace.append(dict(v))  # snapshot *before* processing step d

        for k in range(-d, d + 1, 2):
            # Choose: come from k+1 (insertion) or k-1 (deletion)
            if k == -d or (k != d and v.get(k - 1, -1) < v.get(k + 1, -1)):
                x = v.get(k + 1, 0)  # insertion from diagonal k+1
            else:
                x = v.get(k - 1, 0) + 1  # deletion from diagonal k-1

            y = x - k

            # Extend along diagonal (matches)
            while x < n and y < m and lines_a[x] == lines_b[y]:
                x += 1
                y += 1

            v[k] = x

            if x >= n and y >= m:
                trace.append(dict(v))  # final snapshot
                return _backtrack_diff(trace, lines_a, lines_b, d)

    return []  # unreachable for finite inputs


def _backtrack_diff(
    trace: List[Dict[int, int]],
    lines_a: List[str],
    lines_b: List[str],
    edit_distance: int,
) -> List[str]:
    """Walk backwards through the saved V snapshots to reconstruct the edit script."""
    x, y = len(lines_a), len(lines_b)
    edits: List[str] = []

    for d in range(edit_distance, 0, -1):
        k = x - y
        v_prev = trace[d]  # V state after step d-1

        if k == -d or (k != d and v_prev.get(k - 1, -1) < v_prev.get(k + 1, -1)):
            # Came from k+1 via insertion
            prev_k = k + 1
            prev_x = v_prev.get(prev_k, 0)
            prev_y = prev_x - prev_k
            mid_x = prev_x
            mid_y = prev_y + 1
        else:
            # Came from k-1 via deletion
            prev_k = k - 1
            prev_x = v_prev.get(prev_k, 0)
            prev_y = prev_x - prev_k
            mid_x = prev_x + 1
            mid_y = prev_y

        # Diagonal matches from (mid_x, mid_y) to (x, y)
        while x > mid_x:
            x -= 1
            y -= 1
            edits.append(" " + lines_a[x])

        # The actual edit
        if prev_k == k + 1:
            # Insertion
            edits.append("+" + lines_b[mid_y - 1])
        else:
            # Deletion
            edits.append("-" + lines_a[mid_x - 1])

        x, y = prev_x, prev_y

    # Remaining diagonal at d==0
    while x > 0:
        x -= 1
        y -= 1
        edits.append(" " + lines_a[x])

    edits.reverse()
    return edits
