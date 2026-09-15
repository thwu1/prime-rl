
"""
Rank-augmented B+ tree sorted set implementation.

Key ideas (inspired by DragonflyDB's sorted set redesign):
- Bucketed B+ tree nodes hold multiple keys, reducing per-entry overhead.
- Internal nodes maintain a *subtree count* for each child, enabling O(log N)
  rank queries (GetRank / FromRank) without scanning.
- Leaf nodes are linked for efficient forward iteration (range scans).
- Compound sort key (score, member) gives Redis-compatible ordering.
"""

from __future__ import annotations

import bisect
from typing import List, Optional, Tuple

from interface import SortedSetInterface


# ═══════════════════════════════════════════════════════════════════════════
# B+ tree internals
# ═══════════════════════════════════════════════════════════════════════════


class _Node:
    """Single node in the B+ tree (leaf or internal)."""

    __slots__ = ("leaf", "keys", "children", "counts", "next_leaf")

    def __init__(self, leaf: bool = True):
        self.leaf = leaf
        self.keys: list = []
        # -- internal only --
        self.children: list = []
        self.counts: list = []  # counts[i] = total elements in children[i]'s subtree
        # -- leaf only --
        self.next_leaf: Optional[_Node] = None


class _BPTree:
    """Rank-augmented B+ tree.

    *max_keys* sets the maximum number of keys stored in a single node (leaf
    or internal).  Nodes (except the root) must contain at least
    ``max_keys // 2`` keys.

    Keys are arbitrary objects that support ``<`` / ``==`` comparison
    (tuples work out of the box).
    """

    def __init__(self, max_keys: int = 24):
        assert max_keys >= 8
        self.max_keys = max_keys
        self.min_keys = max_keys // 2
        self.root = _Node(leaf=True)
        self._size = 0
        self._height = 1
        self._node_count = 1

    # ── helpers ─────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return self._size

    def _leftmost_leaf(self) -> _Node:
        n = self.root
        while not n.leaf:
            n = n.children[0]
        return n

    # ── insert ──────────────────────────────────────────────────────────

    def insert(self, key) -> bool:
        """Insert *key*.  Return True if new, False if duplicate."""
        path: list[tuple[_Node, int]] = []
        node = self.root
        while not node.leaf:
            idx = bisect.bisect_right(node.keys, key)
            path.append((node, idx))
            node = node.children[idx]

        pos = bisect.bisect_left(node.keys, key)
        if pos < len(node.keys) and node.keys[pos] == key:
            return False  # duplicate

        node.keys.insert(pos, key)
        self._size += 1

        # bump subtree counts on the path from root to leaf
        for anc, ci in path:
            anc.counts[ci] += 1

        if len(node.keys) > self.max_keys:
            self._split(node, path)

        return True

    def _split(self, node: _Node, path: list[tuple[_Node, int]]) -> None:
        mid = len(node.keys) // 2
        right = _Node(leaf=node.leaf)
        self._node_count += 1

        if node.leaf:
            # ── leaf split (copy-up) ──
            right.keys = node.keys[mid:]
            node.keys = node.keys[:mid]
            right.next_leaf = node.next_leaf
            node.next_leaf = right
            sep = right.keys[0]
        else:
            # ── internal split (push-up) ──
            sep = node.keys[mid]
            right.keys = node.keys[mid + 1 :]
            right.children = node.children[mid + 1 :]
            right.counts = node.counts[mid + 1 :]
            node.keys = node.keys[:mid]
            node.children = node.children[: mid + 1]
            node.counts = node.counts[: mid + 1]

        # propagate separator up
        if not path:
            new_root = _Node(leaf=False)
            self._node_count += 1
            new_root.keys = [sep]
            new_root.children = [node, right]
            new_root.counts = [
                len(node.keys) if node.leaf else sum(node.counts),
                len(right.keys) if right.leaf else sum(right.counts),
            ]
            self.root = new_root
            self._height += 1
        else:
            parent, ci = path[-1]
            parent.keys.insert(ci, sep)
            parent.children.insert(ci + 1, right)
            lc = len(node.keys) if node.leaf else sum(node.counts)
            rc = len(right.keys) if right.leaf else sum(right.counts)
            parent.counts[ci] = lc
            parent.counts.insert(ci + 1, rc)

            if len(parent.keys) > self.max_keys:
                self._split(parent, path[:-1])

    # ── delete ──────────────────────────────────────────────────────────

    def delete(self, key) -> bool:
        """Delete *key*.  Return True if found, False otherwise."""
        path: list[tuple[_Node, int]] = []
        node = self.root
        while not node.leaf:
            idx = bisect.bisect_right(node.keys, key)
            path.append((node, idx))
            node = node.children[idx]

        pos = bisect.bisect_left(node.keys, key)
        if pos >= len(node.keys) or node.keys[pos] != key:
            return False

        node.keys.pop(pos)
        self._size -= 1

        for anc, ci in path:
            anc.counts[ci] -= 1

        if path and len(node.keys) < self.min_keys:
            self._fix_underflow(node, path)

        # shrink tree if root collapsed to a single child
        while not self.root.leaf and len(self.root.children) == 1:
            self.root = self.root.children[0]
            self._height -= 1
            self._node_count -= 1

        return True

    def _fix_underflow(self, node: _Node, path: list[tuple[_Node, int]]) -> None:
        parent, ci = path[-1]

        # ── try borrow from left sibling ──
        if ci > 0:
            left = parent.children[ci - 1]
            if len(left.keys) > self.min_keys:
                if node.leaf:
                    node.keys.insert(0, left.keys.pop())
                    parent.keys[ci - 1] = node.keys[0]
                    parent.counts[ci - 1] -= 1
                    parent.counts[ci] += 1
                else:
                    node.keys.insert(0, parent.keys[ci - 1])
                    parent.keys[ci - 1] = left.keys.pop()
                    ch = left.children.pop()
                    cnt = left.counts.pop()
                    node.children.insert(0, ch)
                    node.counts.insert(0, cnt)
                    parent.counts[ci - 1] -= cnt
                    parent.counts[ci] += cnt
                return

        # ── try borrow from right sibling ──
        if ci < len(parent.children) - 1:
            right = parent.children[ci + 1]
            if len(right.keys) > self.min_keys:
                if node.leaf:
                    node.keys.append(right.keys.pop(0))
                    parent.keys[ci] = right.keys[0]
                    parent.counts[ci] += 1
                    parent.counts[ci + 1] -= 1
                else:
                    node.keys.append(parent.keys[ci])
                    parent.keys[ci] = right.keys.pop(0)
                    ch = right.children.pop(0)
                    cnt = right.counts.pop(0)
                    node.children.append(ch)
                    node.counts.append(cnt)
                    parent.counts[ci] += cnt
                    parent.counts[ci + 1] -= cnt
                return

        # ── merge ──
        if ci > 0:
            # merge *node* into its left sibling
            left = parent.children[ci - 1]
            if not node.leaf:
                left.keys.append(parent.keys.pop(ci - 1))
                left.keys.extend(node.keys)
                left.children.extend(node.children)
                left.counts.extend(node.counts)
            else:
                parent.keys.pop(ci - 1)  # remove separator
                left.keys.extend(node.keys)
                left.next_leaf = node.next_leaf
            parent.children.pop(ci)
            mc = parent.counts.pop(ci)
            parent.counts[ci - 1] += mc
            self._node_count -= 1
        else:
            # merge right sibling into *node*
            right = parent.children[ci + 1]
            if not node.leaf:
                node.keys.append(parent.keys.pop(ci))
                node.keys.extend(right.keys)
                node.children.extend(right.children)
                node.counts.extend(right.counts)
            else:
                parent.keys.pop(ci)  # remove separator
                node.keys.extend(right.keys)
                node.next_leaf = right.next_leaf
            parent.children.pop(ci + 1)
            mc = parent.counts.pop(ci + 1)
            parent.counts[ci] += mc
            self._node_count -= 1

        # cascade if parent now underflows (unless parent is root)
        if len(path) > 1 and len(parent.keys) < self.min_keys:
            self._fix_underflow(parent, path[:-1])

    # ── rank operations ─────────────────────────────────────────────────

    def get_rank(self, key) -> Optional[int]:
        """Return 0-based rank of *key*, or ``None`` if absent."""
        node = self.root
        rank = 0

        while not node.leaf:
            idx = bisect.bisect_right(node.keys, key)
            for i in range(idx):
                rank += node.counts[i]
            node = node.children[idx]

        pos = bisect.bisect_left(node.keys, key)
        if pos >= len(node.keys) or node.keys[pos] != key:
            return None
        return rank + pos

    def from_rank(self, rank: int):
        """Return key at *rank* (0-based), or ``None`` if out of range."""
        if rank < 0 or rank >= self._size:
            return None
        node = self.root
        rem = rank
        while not node.leaf:
            for i, c in enumerate(node.counts):
                if rem < c:
                    node = node.children[i]
                    break
                rem -= c
            else:
                return None  # should never happen in a valid tree
        if rem < len(node.keys):
            return node.keys[rem]
        return None

    # ── range helpers ───────────────────────────────────────────────────

    def range_by_rank(self, start: int, end: int) -> list:
        """Return keys at ranks [start, end] inclusive."""
        if self._size == 0 or start > end or start >= self._size:
            return []
        start = max(0, start)
        end = min(end, self._size - 1)

        first_key = self.from_rank(start)
        if first_key is None:
            return []

        # descend to the leaf containing first_key
        node = self.root
        while not node.leaf:
            idx = bisect.bisect_right(node.keys, first_key)
            node = node.children[idx]
        pos = bisect.bisect_left(node.keys, first_key)

        result = []
        need = end - start + 1
        while need > 0 and node is not None:
            while pos < len(node.keys) and need > 0:
                result.append(node.keys[pos])
                pos += 1
                need -= 1
            node = node.next_leaf
            pos = 0
        return result

    def find_ge(self, key) -> Optional[Tuple[_Node, int]]:
        """Return (leaf, pos) of first stored key >= *key*, or None."""
        if self._size == 0:
            return None
        node = self.root
        while not node.leaf:
            idx = bisect.bisect_right(node.keys, key)
            node = node.children[idx]
        pos = bisect.bisect_left(node.keys, key)
        while pos >= len(node.keys):
            node = node.next_leaf  # type: ignore[assignment]
            if node is None:
                return None
            pos = 0
        return (node, pos)


# ═══════════════════════════════════════════════════════════════════════════
# Sorted set (wraps B+ tree + hash map)
# ═══════════════════════════════════════════════════════════════════════════


class BPTreeSortedSet(SortedSetInterface):
    """Redis-like sorted set backed by a rank-augmented B+ tree.

    Elements are ordered by ``(score, member)`` – ascending score first, then
    lexicographic member for ties.
    """

    def __init__(self, max_keys: int = 24):
        self._tree = _BPTree(max_keys=max_keys)
        self._members: dict[str, float] = {}  # member → score (O(1) lookup)

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _fmt(items: list, withscores: bool) -> list:
        if withscores:
            return [(m, s) for s, m in items]
        return [m for _s, m in items]

    # ── mutators ────────────────────────────────────────────────────────

    def zadd(
        self,
        items: List[Tuple[float, str]],
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
        ch: bool = False,
    ) -> int:
        added = 0
        changed = 0

        for score, member in items:
            if member in self._members:
                if nx:
                    continue
                old = self._members[member]
                if gt and score <= old:
                    continue
                if lt and score >= old:
                    continue
                if old != score:
                    self._tree.delete((old, member))
                    self._tree.insert((score, member))
                    self._members[member] = score
                    changed += 1
            else:
                if xx:
                    continue
                self._tree.insert((score, member))
                self._members[member] = score
                added += 1

        return (added + changed) if ch else added

    def zincrby(self, member: str, increment: float) -> float:
        if member in self._members:
            old = self._members[member]
            new = old + increment
            self._tree.delete((old, member))
            self._tree.insert((new, member))
            self._members[member] = new
            return new
        self._tree.insert((increment, member))
        self._members[member] = increment
        return increment

    def zrem(self, *members: str) -> int:
        removed = 0
        for m in members:
            if m in self._members:
                s = self._members.pop(m)
                self._tree.delete((s, m))
                removed += 1
        return removed

    # ── queries ─────────────────────────────────────────────────────────

    def zscore(self, member: str) -> Optional[float]:
        return self._members.get(member)

    def zcard(self) -> int:
        return len(self._members)

    def zrank(self, member: str) -> Optional[int]:
        if member not in self._members:
            return None
        return self._tree.get_rank((self._members[member], member))

    def zrevrank(self, member: str) -> Optional[int]:
        r = self.zrank(member)
        if r is None:
            return None
        return len(self._members) - 1 - r

    # ── range by rank ───────────────────────────────────────────────────

    def zrange(
        self,
        start: int,
        stop: int,
        reverse: bool = False,
        withscores: bool = True,
    ) -> list:
        n = len(self._members)
        if n == 0:
            return []
        if start < 0:
            start += n
        if stop < 0:
            stop += n
        start = max(0, start)
        stop = min(n - 1, stop)
        if start > stop:
            return []

        if reverse:
            rs = n - 1 - stop
            re = n - 1 - start
            items = self._tree.range_by_rank(rs, re)
            items = list(reversed(items))
        else:
            items = self._tree.range_by_rank(start, stop)

        return self._fmt(items, withscores)

    # ── range by score ──────────────────────────────────────────────────

    def zrangebyscore(
        self,
        min_score: float,
        max_score: float,
        min_exclusive: bool = False,
        max_exclusive: bool = False,
        offset: int = 0,
        count: int = -1,
        withscores: bool = True,
    ) -> list:
        if self._tree.size == 0:
            return []

        pos_info = self._tree.find_ge((min_score, ""))
        if pos_info is None:
            return []

        leaf, pos = pos_info
        results: list = []
        skipped = 0
        collected = 0

        while leaf is not None:
            while pos < len(leaf.keys):
                sc, mb = leaf.keys[pos]
                # lower bound
                if sc < min_score or (min_exclusive and sc == min_score):
                    pos += 1
                    continue
                # upper bound
                if sc > max_score or (max_exclusive and sc == max_score):
                    return self._fmt(results, withscores)
                # offset
                if skipped < offset:
                    skipped += 1
                    pos += 1
                    continue
                results.append((sc, mb))
                collected += 1
                if count >= 0 and collected >= count:
                    return self._fmt(results, withscores)
                pos += 1
            leaf = leaf.next_leaf
            pos = 0

        return self._fmt(results, withscores)

    def zcount(
        self,
        min_score: float,
        max_score: float,
        min_exclusive: bool = False,
        max_exclusive: bool = False,
    ) -> int:
        return len(
            self.zrangebyscore(
                min_score,
                max_score,
                min_exclusive,
                max_exclusive,
                withscores=False,
            )
        )

    # ── pop ─────────────────────────────────────────────────────────────

    def zpopmin(self, count: int = 1) -> List[Tuple[str, float]]:
        result: list[tuple[str, float]] = []
        for _ in range(min(count, len(self._members))):
            key = self._tree.from_rank(0)
            if key is None:
                break
            sc, mb = key
            self._tree.delete(key)
            del self._members[mb]
            result.append((mb, sc))
        return result

    def zpopmax(self, count: int = 1) -> List[Tuple[str, float]]:
        result: list[tuple[str, float]] = []
        for _ in range(min(count, len(self._members))):
            key = self._tree.from_rank(self._tree.size - 1)
            if key is None:
                break
            sc, mb = key
            self._tree.delete(key)
            del self._members[mb]
            result.append((mb, sc))
        return result

    # ── introspection ───────────────────────────────────────────────────

    def _get_tree_info(self) -> dict:
        return {
            "height": self._tree._height,
            "node_count": self._tree._node_count,
            "max_keys_per_node": self._tree.max_keys,
            "total_elements": self._tree._size,
        }

    def _verify_integrity(self) -> bool:
        tree = self._tree

        # ── recursive node check ──
        def _check(node: _Node, is_root: bool) -> tuple[bool, int, set[int]]:
            """Return (ok, element_count, {depth_from_leaves})."""
            # key-count bounds
            if not is_root and len(node.keys) < tree.min_keys:
                return False, 0, set()
            if len(node.keys) > tree.max_keys:
                return False, 0, set()
            # intra-node sort
            for i in range(len(node.keys) - 1):
                if node.keys[i] >= node.keys[i + 1]:
                    return False, 0, set()

            if node.leaf:
                return True, len(node.keys), {0}

            # internal-node structural checks
            if len(node.children) != len(node.keys) + 1:
                return False, 0, set()
            if len(node.counts) != len(node.children):
                return False, 0, set()

            total = 0
            depths: set[int] = set()
            for i, child in enumerate(node.children):
                ok, cnt, ds = _check(child, False)
                if not ok:
                    return False, 0, set()
                if node.counts[i] != cnt:
                    return False, 0, set()
                total += cnt
                depths |= {d + 1 for d in ds}

            if len(depths) > 1:
                return False, 0, set()
            return True, total, depths

        ok, count, _ = _check(tree.root, True)
        if not ok or count != tree._size or count != len(self._members):
            return False

        # ── leaf-list global sort check ──
        leaf = tree._leftmost_leaf()
        prev = None
        lcount = 0
        while leaf is not None:
            for k in leaf.keys:
                if prev is not None and k <= prev:
                    return False
                prev = k
                lcount += 1
            leaf = leaf.next_leaf

        return lcount == count
