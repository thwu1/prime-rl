"""
Persistent Piece Table Text Buffer with Branching Undo and Myers Diff.

Implementation uses a persistent implicit-key treap as the balanced BST
backing the piece table.  Split and merge are the two primitive operations;
all tree nodes are structurally immutable (path-copied on modification),
so old roots remain valid indefinitely.

"""

import random
from collections import namedtuple

Piece = namedtuple("Piece", ["buf_id", "start", "length"])


# ── Persistent implicit-key treap ─────────────────────────────────────────────

class _Node:
    """Immutable treap node.  Never mutated after __init__."""
    __slots__ = ("piece", "priority", "left", "right", "subtree_len")

    def __init__(self, piece, priority=None, left=None, right=None):
        self.piece = piece
        self.priority = priority if priority is not None else random.random()
        self.left = left
        self.right = right
        self.subtree_len = (
            piece.length
            + (left.subtree_len if left else 0)
            + (right.subtree_len if right else 0)
        )


def _slen(node):
    return node.subtree_len if node else 0


def _merge(a, b):
    """Persistent merge of two treaps.  Creates new path nodes."""
    if a is None:
        return b
    if b is None:
        return a
    if a.priority >= b.priority:
        return _Node(a.piece, a.priority, a.left, _merge(a.right, b))
    return _Node(b.piece, b.priority, _merge(a, b.left), b.right)


def _split(node, k):
    """Persistent split at character offset *k*.

    Returns ``(left, right)`` where *left* contains the first *k* characters.
    If *k* falls inside a piece the piece itself is split in two.
    """
    if node is None:
        return None, None

    ll = _slen(node.left)

    if k <= ll:
        sl, sr = _split(node.left, k)
        return sl, _Node(node.piece, node.priority, sr, node.right)

    k -= ll

    if k >= node.piece.length:
        k -= node.piece.length
        rl, rr = _split(node.right, k)
        return _Node(node.piece, node.priority, node.left, rl), rr

    # Split falls inside this piece.
    # The left-half piece gets a priority strictly below node.priority so it
    # can be safely attached as a descendant without violating the max-heap
    # invariant.  The right-half piece inherits node.priority.
    p = node.piece
    lp = Piece(p.buf_id, p.start, k)
    rp = Piece(p.buf_id, p.start + k, p.length - k)

    lp_node = _Node(lp, priority=node.priority * random.random())
    left_tree = _merge(node.left, lp_node)
    right_tree = _Node(rp, node.priority, None, node.right)
    return left_tree, right_tree


# ── Tree inspection helpers ───────────────────────────────────────────────────

def _height(node):
    if node is None:
        return 0
    return 1 + max(_height(node.left), _height(node.right))


def _count(node):
    if node is None:
        return 0
    return 1 + _count(node.left) + _count(node.right)


def _check(node):
    """Return ``(ok, computed_subtree_len)``."""
    if node is None:
        return True, 0
    ok_l, len_l = _check(node.left)
    ok_r, len_r = _check(node.right)
    expected = len_l + node.piece.length + len_r
    ok = ok_l and ok_r and (node.subtree_len == expected)
    if node.left and node.left.priority > node.priority:
        ok = False
    if node.right and node.right.priority > node.priority:
        ok = False
    return ok, expected


def _collect(node, orig, add, parts):
    """In-order traversal collecting text fragments."""
    if node is None:
        return
    _collect(node.left, orig, add, parts)
    p = node.piece
    buf = orig if p.buf_id == 0 else add
    parts.append(buf[p.start : p.start + p.length])
    _collect(node.right, orig, add, parts)


# ── Undo tree ─────────────────────────────────────────────────────────────────

class _UndoNode:
    __slots__ = ("root", "parent", "children")

    def __init__(self, root, parent=None):
        self.root = root
        self.parent = parent
        self.children = []


# ── Myers diff ────────────────────────────────────────────────────────────────

def _myers_diff(a, b):
    """Line-level Myers diff.  Returns ``[(op, line), ...]``."""
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return []

    max_d = n + m
    v = {1: 0}
    trace = []
    found = -1

    for d in range(max_d + 1):
        trace.append(dict(v))
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v.get(k - 1, 0) < v.get(k + 1, 0)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, 0) + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[k] = x
            if x >= n and y >= m:
                found = d
                break
        if found >= 0:
            break

    if found < 0:
        found = 0

    x, y = n, m
    ops = []

    for di in range(found, 0, -1):
        pv = trace[di]
        k = x - y
        if k == -di or (k != di and pv.get(k - 1, 0) < pv.get(k + 1, 0)):
            pk = k + 1
        else:
            pk = k - 1
        px = pv.get(pk, 0)
        py = px - pk

        while x > px and y > py:
            x -= 1
            y -= 1
            ops.append((" ", a[x]))
        if x == px:
            y -= 1
            ops.append(("+", b[y]))
        else:
            x -= 1
            ops.append(("-", a[x]))

    while x > 0 and y > 0:
        x -= 1
        y -= 1
        ops.append((" ", a[x]))

    ops.reverse()
    return ops


# ── PieceTable ────────────────────────────────────────────────────────────────

class PieceTable:
    """Persistent piece table text buffer with branching undo/redo and Myers diff."""

    def __init__(self, initial_text: str = ""):
        self._orig = initial_text
        self._add = ""
        if initial_text:
            self._root = _Node(Piece(0, 0, len(initial_text)))
        else:
            self._root = None
        self._uroot = _UndoNode(self._root)
        self._ucur = self._uroot
        self._snaps = {}
        self._snap_id = 0

    # ── private helpers ───────────────────────────────────────────────────────

    def _push_undo(self):
        nd = _UndoNode(self._root, parent=self._ucur)
        self._ucur.children.append(nd)
        self._ucur = nd

    def _text_of(self, root):
        parts = []
        _collect(root, self._orig, self._add, parts)
        return "".join(parts)

    @staticmethod
    def _split_into_lines(text):
        if not text:
            return [""]
        result = []
        start = 0
        for i, ch in enumerate(text):
            if ch == "\n":
                result.append(text[start : i + 1])
                start = i + 1
        if start < len(text):
            result.append(text[start:])
        return result if result else [""]

    # ── public API ────────────────────────────────────────────────────────────

    def insert(self, offset: int, text: str) -> None:
        if not text:
            return
        total = self.length()
        if offset < 0 or offset > total:
            raise IndexError(f"offset {offset} out of range [0, {total}]")
        add_start = len(self._add)
        self._add += text
        new = _Node(Piece(1, add_start, len(text)))
        l, r = _split(self._root, offset)
        self._root = _merge(_merge(l, new), r)
        self._push_undo()

    def delete(self, offset: int, length: int) -> None:
        if length == 0:
            return
        total = self.length()
        if offset < 0 or offset + length > total:
            raise IndexError(
                f"range [{offset}, {offset + length}) out of bounds [0, {total})"
            )
        l, rest = _split(self._root, offset)
        _, r = _split(rest, length)
        self._root = _merge(l, r)
        self._push_undo()

    def get_text(self) -> str:
        return self._text_of(self._root)

    def char_at(self, offset: int) -> str:
        total = self.length()
        if offset < 0 or offset >= total:
            raise IndexError(f"offset {offset} out of range [0, {total})")
        nd = self._root
        while nd is not None:
            ll = _slen(nd.left)
            if offset < ll:
                nd = nd.left
            elif offset < ll + nd.piece.length:
                loc = offset - ll
                p = nd.piece
                buf = self._orig if p.buf_id == 0 else self._add
                return buf[p.start + loc]
            else:
                offset -= ll + nd.piece.length
                nd = nd.right
        raise IndexError("should not reach here")

    def length(self) -> int:
        return _slen(self._root)

    def line_count(self) -> int:
        text = self.get_text()
        if not text:
            return 1
        c = text.count("\n")
        if not text.endswith("\n"):
            c += 1
        return c

    def get_line(self, line_num: int) -> str:
        text = self.get_text()
        lines = self._split_into_lines(text)
        if line_num < 0 or line_num >= len(lines):
            raise IndexError(f"line {line_num} out of range")
        return lines[line_num]

    def snapshot(self) -> int:
        sid = self._snap_id
        self._snap_id += 1
        self._snaps[sid] = self._root
        return sid

    def restore(self, snapshot_id: int) -> None:
        if snapshot_id not in self._snaps:
            raise KeyError(f"snapshot {snapshot_id} not found")
        self._root = self._snaps[snapshot_id]
        self._push_undo()

    def undo(self) -> bool:
        if self._ucur.parent is None:
            return False
        self._ucur = self._ucur.parent
        self._root = self._ucur.root
        return True

    def redo(self, branch: int = 0) -> bool:
        if branch < 0 or branch >= len(self._ucur.children):
            return False
        self._ucur = self._ucur.children[branch]
        self._root = self._ucur.root
        return True

    def redo_branch_count(self) -> int:
        return len(self._ucur.children)

    def undo_depth(self) -> int:
        d = 0
        nd = self._ucur
        while nd.parent is not None:
            d += 1
            nd = nd.parent
        return d

    def diff_snapshots(self, snap_a: int, snap_b: int) -> list:
        if snap_a not in self._snaps:
            raise KeyError(f"snapshot {snap_a} not found")
        if snap_b not in self._snaps:
            raise KeyError(f"snapshot {snap_b} not found")
        la = self._text_of(self._snaps[snap_a]).splitlines()
        lb = self._text_of(self._snaps[snap_b]).splitlines()
        return _myers_diff(la, lb)

    # ── introspection for tests ───────────────────────────────────────────────

    def _tree_height(self) -> int:
        return _height(self._root)

    def _piece_count(self) -> int:
        return _count(self._root)

    def _is_balanced(self) -> bool:
        ok, _ = _check(self._root)
        return ok

    def _get_buffers(self) -> tuple:
        return (self._orig, self._add)
