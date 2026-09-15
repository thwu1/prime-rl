"""
Rank-augmented sorted set using a randomized treap with subtree-size
augmentation.  O(log N) for rank, insert, delete; O(log N + k) for
range queries.

Inspired by DragonflyDB's B+ tree sorted set design (subtree counts
for O(log N) rank queries), adapted to a Python treap.
"""

import random as _rng

# ── Treap primitives ─────────────────────────────────────────────────

class _Node:
    __slots__ = ("key", "pri", "left", "right", "sz")

    def __init__(self, key):
        self.key = key
        self.pri = _rng.random()
        self.left = None
        self.right = None
        self.sz = 1


def _sz(n):
    return n.sz if n else 0


def _upd(n):
    if n:
        n.sz = 1 + _sz(n.left) + _sz(n.right)


def _split(n, key):
    """Split into (< key, >= key)."""
    if not n:
        return None, None
    if n.key < key:
        n.right, right = _split(n.right, key)
        _upd(n)
        return n, right
    else:
        left, n.left = _split(n.left, key)
        _upd(n)
        return left, n


def _merge(a, b):
    """Merge two treaps (all keys in *a* < all keys in *b*)."""
    if not a:
        return b
    if not b:
        return a
    if a.pri > b.pri:
        a.right = _merge(a.right, b)
        _upd(a)
        return a
    else:
        b.left = _merge(a, b.left)
        _upd(b)
        return b


def _insert(root, key):
    node = _Node(key)
    left, right = _split(root, key)
    return _merge(_merge(left, node), right)


def _erase(root, key):
    if not root:
        return None
    if root.key == key:
        return _merge(root.left, root.right)
    if key < root.key:
        root.left = _erase(root.left, key)
    else:
        root.right = _erase(root.right, key)
    _upd(root)
    return root


def _rank_of(root, key):
    """Return 0-based rank of *key*, or None."""
    r = 0
    node = root
    while node:
        if key < node.key:
            node = node.left
        elif key == node.key:
            return r + _sz(node.left)
        else:
            r += _sz(node.left) + 1
            node = node.right
    return None


def _kth(root, k):
    """Select the k-th smallest key (0-based)."""
    node = root
    while node:
        ls = _sz(node.left)
        if k < ls:
            node = node.left
        elif k == ls:
            return node.key
        else:
            k -= ls + 1
            node = node.right
    return None


def _collect_range(node, start, stop, out):
    """Collect keys at ranks [start, stop] via in-order traversal (O(log N + k))."""
    if not node or start > stop:
        return
    ls = _sz(node.left)
    if start < ls:
        _collect_range(node.left, start, min(stop, ls - 1), out)
    if start <= ls <= stop:
        out.append(node.key)
    if stop > ls:
        _collect_range(node.right, max(0, start - ls - 1), stop - ls - 1, out)


def _count_score_lt(root, score):
    """Count keys whose score (tuple element 0) is strictly < *score*."""
    c = 0
    node = root
    while node:
        if node.key[0] < score:
            c += _sz(node.left) + 1
            node = node.right
        else:
            node = node.left
    return c


def _count_score_leq(root, score):
    """Count keys whose score (tuple element 0) is <= *score*."""
    c = 0
    node = root
    while node:
        if node.key[0] <= score:
            c += _sz(node.left) + 1
            node = node.right
        else:
            node = node.left
    return c


# ── Public SortedSet class ───────────────────────────────────────────

class SortedSet:
    """Sorted set ordered by (score asc, member asc) with O(log N) rank."""

    def __init__(self):
        self._root = None          # treap of (score, member) tuples
        self._members = {}         # member -> score

    # -- mutators --

    def add(self, member, score):
        if member in self._members:
            old = self._members[member]
            if old == score:
                return False
            self._root = _erase(self._root, (old, member))
            self._members[member] = score
            self._root = _insert(self._root, (score, member))
            return False
        self._members[member] = score
        self._root = _insert(self._root, (score, member))
        return True

    def remove(self, member):
        if member not in self._members:
            return False
        score = self._members.pop(member)
        self._root = _erase(self._root, (score, member))
        return True

    def incr(self, member, increment):
        old = self._members.get(member, 0.0)
        new = old + increment
        if member in self._members:
            if old != new:
                self._root = _erase(self._root, (old, member))
                self._root = _insert(self._root, (new, member))
        else:
            self._root = _insert(self._root, (new, member))
        self._members[member] = new
        return new

    # -- queries --

    def score(self, member):
        return self._members.get(member)

    def card(self):
        return len(self._members)

    def rank(self, member):
        if member not in self._members:
            return None
        s = self._members[member]
        return _rank_of(self._root, (s, member))

    def rev_rank(self, member):
        r = self.rank(member)
        if r is None:
            return None
        return len(self._members) - 1 - r

    def range_by_rank(self, start, stop, reverse=False):
        n = self.card()
        if n == 0:
            return []
        if reverse:
            a = max(0, n - 1 - stop)
            b = min(n - 1, n - 1 - start)
        else:
            a = max(0, start)
            b = min(n - 1, stop)
        if a > b:
            return []
        buf = []
        _collect_range(self._root, a, b, buf)
        items = [(m, s) for s, m in buf]
        if reverse:
            items.reverse()
        return items

    def range_by_score(self, min_score, max_score):
        if min_score > max_score or not self._root:
            return []
        lo = _count_score_lt(self._root, min_score)
        hi = _count_score_leq(self._root, max_score) - 1
        if lo > hi:
            return []
        buf = []
        _collect_range(self._root, lo, hi, buf)
        return [(m, s) for s, m in buf]

    def count(self, min_score, max_score):
        if min_score > max_score or not self._root:
            return 0
        return _count_score_leq(self._root, max_score) - _count_score_lt(self._root, min_score)
