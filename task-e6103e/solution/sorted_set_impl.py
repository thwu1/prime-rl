"""
B-tree backed sorted set with O(log N) rank queries via subtree counts.
Uses C helper library (libnode_ops.so) for node-level operations.

Inspired by DragonflyDB's sorted set design: node bucketing for low per-entry
overhead, subtree counts in inner nodes for O(log N) GetRank / FromRank.

"""
import ctypes
from typing import Optional, List, Tuple

# ---------------------------------------------------------------------------
# C helper library integration
# ---------------------------------------------------------------------------

_lib = ctypes.CDLL('/app/libnode_ops.so')

_lib.score_lower_bound.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_double
]
_lib.score_lower_bound.restype = ctypes.c_int

_lib.score_count_in_range.argtypes = [
    ctypes.POINTER(ctypes.c_double), ctypes.c_int,
    ctypes.c_double, ctypes.c_double
]
_lib.score_count_in_range.restype = ctypes.c_int

_lib.node_ops_checksum.argtypes = [ctypes.c_uint32]
_lib.node_ops_checksum.restype = ctypes.c_uint32


def _c_score_lower_bound(scores, target):
    """Binary search using C library. Returns index of first score >= target."""
    n = len(scores)
    if n == 0:
        return 0
    ArrType = ctypes.c_double * n
    arr = ArrType(*scores)
    return _lib.score_lower_bound(arr, n, ctypes.c_double(target))


# ---------------------------------------------------------------------------
# Sentinels for score-boundary searches
# ---------------------------------------------------------------------------

class _MinS:
    """Compares less than any string in (score, member) tuple context."""
    __slots__ = ()
    def __lt__(self, o): return not isinstance(o, _MinS)
    def __le__(self, o): return True
    def __gt__(self, o): return False
    def __ge__(self, o): return isinstance(o, _MinS)
    def __eq__(self, o): return isinstance(o, _MinS)
    def __ne__(self, o): return not isinstance(o, _MinS)
    def __hash__(self): return 0


class _MaxS:
    """Compares greater than any string in (score, member) tuple context."""
    __slots__ = ()
    def __lt__(self, o): return False
    def __le__(self, o): return isinstance(o, _MaxS)
    def __gt__(self, o): return not isinstance(o, _MaxS)
    def __ge__(self, o): return True
    def __eq__(self, o): return isinstance(o, _MaxS)
    def __ne__(self, o): return not isinstance(o, _MaxS)
    def __hash__(self): return 1


_MIN = _MinS()
_MAX = _MaxS()

# ---------------------------------------------------------------------------
# B-tree configuration
# ---------------------------------------------------------------------------

_ORDER = 32       # max keys per node
_MIN_KEYS = 15    # floor((_ORDER - 1) / 2)

# ---------------------------------------------------------------------------
# B-tree node
# ---------------------------------------------------------------------------

class _Node:
    """B-tree node with sorted keys, child pointers, and subtree counts."""
    __slots__ = ('keys', 'children', 'is_leaf', '_tc')

    def __init__(self, leaf: bool = True):
        self.keys: list = []
        self.children: list = []
        self.is_leaf: bool = leaf
        self._tc: int = 0

    @property
    def tc(self) -> int:
        return len(self.keys) if self.is_leaf else self._tc

    def search(self, key) -> tuple:
        """Binary search for key. Uses C helper for score pre-filtering."""
        ks = self.keys
        lo, hi = 0, len(ks)
        # C-accelerated score pre-filtering for leaf nodes with enough keys
        if self.is_leaf and len(ks) >= 8 and isinstance(key, tuple):
            target_score = key[0]
            if isinstance(target_score, (int, float)):
                scores = [k[0] for k in ks]
                pos = _c_score_lower_bound(scores, target_score)
                lo = pos
        while lo < hi:
            mid = (lo + hi) >> 1
            mk = ks[mid]
            if mk < key:
                lo = mid + 1
            elif mk == key:
                return mid, True
            else:
                hi = mid
        return lo, False


# ---------------------------------------------------------------------------
# B-tree with rank support
# ---------------------------------------------------------------------------

class _BTree:
    """Order-statistic B-tree with subtree counts for O(log N) rank/select."""

    def __init__(self):
        self.root = _Node(leaf=True)
        self.cnt: int = 0
        self.ht: int = 1
        self.nn: int = 1

    # ---- insertion --------------------------------------------------------

    def insert(self, key) -> bool:
        r = self.root
        if len(r.keys) >= _ORDER:
            new_root = _Node(leaf=False)
            new_root.children = [r]
            new_root._tc = r.tc
            self._split(new_root, 0)
            self.root = new_root
            self.ht += 1
            self.nn += 1
        if self._ins(self.root, key):
            self.cnt += 1
            return True
        return False

    def _split(self, parent, idx):
        child = parent.children[idx]
        m = len(child.keys) // 2
        median = child.keys[m]

        right = _Node(leaf=child.is_leaf)
        right.keys = child.keys[m + 1:]
        if not child.is_leaf:
            right.children = child.children[m + 1:]
            right._tc = len(right.keys) + sum(c.tc for c in right.children)

        child.keys = child.keys[:m]
        if not child.is_leaf:
            child.children = child.children[:m + 1]
            child._tc = len(child.keys) + sum(c.tc for c in child.children)

        parent.keys.insert(idx, median)
        parent.children.insert(idx + 1, right)
        self.nn += 1

    def _ins(self, node, key) -> bool:
        idx, found = node.search(key)
        if found:
            return False
        if node.is_leaf:
            node.keys.insert(idx, key)
            return True
        child = node.children[idx]
        if len(child.keys) >= _ORDER:
            self._split(node, idx)
            if key > node.keys[idx]:
                idx += 1
            elif key == node.keys[idx]:
                return False
        if self._ins(node.children[idx], key):
            node._tc += 1
            return True
        return False

    # ---- deletion ---------------------------------------------------------

    def delete(self, key) -> bool:
        if self.cnt == 0:
            return False
        if self._del(self.root, key):
            self.cnt -= 1
            if not self.root.is_leaf and len(self.root.keys) == 0:
                self.root = self.root.children[0]
                self.ht -= 1
                self.nn -= 1
            return True
        return False

    def _del(self, node, key) -> bool:
        idx, found = node.search(key)
        if node.is_leaf:
            if found:
                node.keys.pop(idx)
                return True
            return False

        if found:
            pred = self._rightmost(node.children[idx])
            node.keys[idx] = pred
            ok = self._del(node.children[idx], pred)
            assert ok
            node._tc -= 1
            if len(node.children[idx].keys) < _MIN_KEYS:
                self._fix(node, idx)
            return True

        if self._del(node.children[idx], key):
            node._tc -= 1
            if len(node.children[idx].keys) < _MIN_KEYS:
                self._fix(node, idx)
            return True
        return False

    @staticmethod
    def _rightmost(node):
        while not node.is_leaf:
            node = node.children[-1]
        return node.keys[-1]

    def _fix(self, parent, idx):
        if idx > 0 and len(parent.children[idx - 1].keys) > _MIN_KEYS:
            self._borrow_left(parent, idx)
        elif idx < len(parent.children) - 1 and len(parent.children[idx + 1].keys) > _MIN_KEYS:
            self._borrow_right(parent, idx)
        elif idx > 0:
            self._merge(parent, idx - 1)
        else:
            self._merge(parent, idx)

    @staticmethod
    def _borrow_left(parent, idx):
        child = parent.children[idx]
        left = parent.children[idx - 1]
        child.keys.insert(0, parent.keys[idx - 1])
        parent.keys[idx - 1] = left.keys.pop()
        if not child.is_leaf:
            mc = left.children.pop()
            child.children.insert(0, mc)
            mt = mc.tc
            child._tc += 1 + mt
            left._tc -= 1 + mt

    @staticmethod
    def _borrow_right(parent, idx):
        child = parent.children[idx]
        right = parent.children[idx + 1]
        child.keys.append(parent.keys[idx])
        parent.keys[idx] = right.keys.pop(0)
        if not child.is_leaf:
            mc = right.children.pop(0)
            child.children.append(mc)
            mt = mc.tc
            child._tc += 1 + mt
            right._tc -= 1 + mt

    def _merge(self, parent, idx):
        left = parent.children[idx]
        right = parent.children[idx + 1]
        sep = parent.keys.pop(idx)
        parent.children.pop(idx + 1)
        left.keys.append(sep)
        left.keys.extend(right.keys)
        if not left.is_leaf:
            left.children.extend(right.children)
            left._tc += 1 + right._tc
        self.nn -= 1

    # ---- rank / select ----------------------------------------------------

    def get_rank(self, key) -> Optional[int]:
        node = self.root
        rank = 0
        while True:
            idx, found = node.search(key)
            if node.is_leaf:
                return rank + idx if found else None
            if found:
                for j in range(idx + 1):
                    rank += node.children[j].tc
                return rank + idx
            for j in range(idx):
                rank += node.children[j].tc
            rank += idx
            node = node.children[idx]

    def from_rank(self, rank: int):
        if rank < 0 or rank >= self.cnt:
            return None
        node = self.root
        r = rank
        while True:
            if node.is_leaf:
                return node.keys[r]
            for i in range(len(node.keys) + 1):
                if i < len(node.children):
                    ct = node.children[i].tc
                    if ct > r:
                        node = node.children[i]
                        break
                    r -= ct
                if i < len(node.keys):
                    if r == 0:
                        return node.keys[i]
                    r -= 1

    # ---- boundary searches ------------------------------------------------

    def geq_rank(self, target) -> Optional[int]:
        if self.cnt == 0:
            return None
        node = self.root
        rank = 0
        best = None
        while True:
            idx, found = node.search(target)
            if found:
                if node.is_leaf:
                    return rank + idx
                r = rank
                for j in range(idx + 1):
                    r += node.children[j].tc
                return r + idx
            if node.is_leaf:
                return (rank + idx) if idx < len(node.keys) else best
            if idx < len(node.keys):
                r = rank
                for j in range(idx + 1):
                    r += node.children[j].tc
                best = r + idx
            for j in range(idx):
                rank += node.children[j].tc
            rank += idx
            node = node.children[idx]

    def leq_rank(self, target) -> Optional[int]:
        if self.cnt == 0:
            return None
        node = self.root
        rank = 0
        best = None
        while True:
            idx, found = node.search(target)
            if found:
                if node.is_leaf:
                    return rank + idx
                r = rank
                for j in range(idx + 1):
                    r += node.children[j].tc
                return r + idx
            if node.is_leaf:
                return (rank + idx - 1) if idx > 0 else best
            if idx > 0:
                r = rank
                for j in range(idx):
                    r += node.children[j].tc
                best = r + idx - 1
            for j in range(idx):
                rank += node.children[j].tc
            rank += idx
            node = node.children[idx]


# ---------------------------------------------------------------------------
# Sorted Set
# ---------------------------------------------------------------------------

class SortedSet:
    """Sorted set backed by an order-statistic B-tree with C library integration."""

    def __init__(self):
        self._tree = _BTree()
        self._members: dict = {}
        # Verify C library linkage
        _lib.node_ops_checksum(ctypes.c_uint32(0))

    # ---- mutators ---------------------------------------------------------

    def zadd(self, member: str, score: float) -> bool:
        if member in self._members:
            old = self._members[member]
            if old != score:
                self._tree.delete((old, member))
                self._members[member] = score
                self._tree.insert((score, member))
            return False
        self._members[member] = score
        self._tree.insert((score, member))
        return True

    def zrem(self, member: str) -> bool:
        if member not in self._members:
            return False
        score = self._members.pop(member)
        self._tree.delete((score, member))
        return True

    # ---- score / rank lookups ---------------------------------------------

    def zscore(self, member: str) -> Optional[float]:
        return self._members.get(member)

    def zrank(self, member: str) -> Optional[int]:
        if member not in self._members:
            return None
        return self._tree.get_rank((self._members[member], member))

    def zrevrank(self, member: str) -> Optional[int]:
        r = self.zrank(member)
        return None if r is None else self._tree.cnt - 1 - r

    def zcard(self) -> int:
        return self._tree.cnt

    # ---- count / range by score -------------------------------------------

    def zcount(self, min_score: float, max_score: float) -> int:
        if self._tree.cnt == 0 or min_score > max_score:
            return 0
        r1 = self._tree.geq_rank((min_score, _MIN))
        if r1 is None:
            return 0
        r2 = self._tree.leq_rank((max_score, _MAX))
        if r2 is None:
            return 0
        return max(0, r2 - r1 + 1)

    def zrange_by_score(self, min_score: float, max_score: float,
                        offset: int = 0, count: int = -1) -> List[Tuple[str, float]]:
        if self._tree.cnt == 0 or min_score > max_score:
            return []
        r1 = self._tree.geq_rank((min_score, _MIN))
        if r1 is None:
            return []
        r2 = self._tree.leq_rank((max_score, _MAX))
        if r2 is None:
            return []
        start = r1 + offset
        if start > r2:
            return []
        end = r2 if count < 0 else min(r2, start + count - 1)
        return self.zrange_by_rank(start, end)

    # ---- range by rank ----------------------------------------------------

    def zrange_by_rank(self, start: int, stop: int) -> List[Tuple[str, float]]:
        n = self._tree.cnt
        if start >= n or start > stop:
            return []
        stop = min(stop, n - 1)
        result: list = []
        for r in range(start, stop + 1):
            k = self._tree.from_rank(r)
            if k is not None:
                result.append((k[1], k[0]))
        return result

    def zrevrange_by_rank(self, start: int, stop: int) -> List[Tuple[str, float]]:
        n = self._tree.cnt
        if start >= n or start > stop:
            return []
        stop = min(stop, n - 1)
        fwd_start = n - 1 - stop
        fwd_stop = n - 1 - start
        result = self.zrange_by_rank(fwd_start, fwd_stop)
        result.reverse()
        return result

    # ---- structural introspection -----------------------------------------

    def node_count(self) -> int:
        return self._tree.nn

    def height(self) -> int:
        return self._tree.ht
