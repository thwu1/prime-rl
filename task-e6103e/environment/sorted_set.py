"""
Sorted set implementation for leaderboard service.
"""
import bisect
from typing import Optional, List, Tuple


class SortedSet:
    """
    Sorted set storing unique string members with float scores.
    Ordered by (score ASC, member ASC).
    """

    def __init__(self):
        self._items = []  # sorted list of (score, member) tuples
        self._members = {}  # member -> score for O(1) score lookup

    def zadd(self, member: str, score: float) -> bool:
        if member in self._members:
            old_score = self._members[member]
            if old_score != score:
                idx = bisect.bisect_left(self._items, (old_score, member))
                while idx < len(self._items) and self._items[idx] != (old_score, member):
                    idx += 1
                if idx < len(self._items):
                    self._items.pop(idx)
                bisect.insort(self._items, (score, member))
                self._members[member] = score
            return False
        bisect.insort(self._items, (score, member))
        self._members[member] = score
        return True

    def zrem(self, member: str) -> bool:
        if member not in self._members:
            return False
        score = self._members.pop(member)
        idx = bisect.bisect_left(self._items, (score, member))
        while idx < len(self._items) and self._items[idx] != (score, member):
            idx += 1
        if idx < len(self._items):
            self._items.pop(idx)
        return True

    def zscore(self, member: str) -> Optional[float]:
        return self._members.get(member)

    def zrank(self, member: str) -> Optional[int]:
        if member not in self._members:
            return None
        score = self._members[member]
        for i, (s, m) in enumerate(self._items):
            if s == score and m == member:
                return i
        return None

    def zrevrank(self, member: str) -> Optional[int]:
        r = self.zrank(member)
        if r is None:
            return None
        return len(self._items) - 1 - r

    def zcard(self) -> int:
        return len(self._items)

    def zcount(self, min_score: float, max_score: float) -> int:
        if min_score > max_score:
            return 0
        count = 0
        for s, _m in self._items:
            if min_score <= s <= max_score:
                count += 1
        return count

    def zrange_by_rank(self, start: int, stop: int) -> List[Tuple[str, float]]:
        n = len(self._items)
        if start >= n or start > stop:
            return []
        stop = min(stop, n - 1)
        return [(m, s) for s, m in self._items[start:stop + 1]]

    def zrange_by_score(self, min_score: float, max_score: float,
                        offset: int = 0, count: int = -1) -> List[Tuple[str, float]]:
        if min_score > max_score:
            return []
        result = []
        for s, m in self._items:
            if min_score <= s <= max_score:
                result.append((m, s))
        if offset > 0:
            result = result[offset:]
        if count >= 0:
            result = result[:count]
        return result

    def zrevrange_by_rank(self, start: int, stop: int) -> List[Tuple[str, float]]:
        n = len(self._items)
        if start >= n or start > stop:
            return []
        stop = min(stop, n - 1)
        fwd_start = n - 1 - stop
        fwd_stop = n - 1 - start
        result = self.zrange_by_rank(fwd_start, fwd_stop)
        result.reverse()
        return result

    def node_count(self) -> int:
        return 1

    def height(self) -> int:
        return 1
