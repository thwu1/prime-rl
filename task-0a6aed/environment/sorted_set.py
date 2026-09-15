
"""Rank-augmented B+ tree sorted set – implementation required.

See interface.py for the complete API specification. Replace every
NotImplementedError stub below with a working implementation backed
by a rank-augmented B+ tree.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from interface import SortedSetInterface


class BPTreeSortedSet(SortedSetInterface):
    """Redis-compatible sorted set backed by a rank-augmented B+ tree.

    Elements are ordered by (score, member) — ascending score first, then
    lexicographic member for ties.
    """

    def __init__(self, max_keys: int = 24):
        raise NotImplementedError

    def zadd(
        self,
        items: List[Tuple[float, str]],
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
        ch: bool = False,
    ) -> int:
        raise NotImplementedError

    def zincrby(self, member: str, increment: float) -> float:
        raise NotImplementedError

    def zrem(self, *members: str) -> int:
        raise NotImplementedError

    def zscore(self, member: str) -> Optional[float]:
        raise NotImplementedError

    def zcard(self) -> int:
        raise NotImplementedError

    def zrank(self, member: str) -> Optional[int]:
        raise NotImplementedError

    def zrevrank(self, member: str) -> Optional[int]:
        raise NotImplementedError

    def zrange(
        self,
        start: int,
        stop: int,
        reverse: bool = False,
        withscores: bool = True,
    ) -> list:
        raise NotImplementedError

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
        raise NotImplementedError

    def zcount(
        self,
        min_score: float,
        max_score: float,
        min_exclusive: bool = False,
        max_exclusive: bool = False,
    ) -> int:
        raise NotImplementedError

    def zpopmin(self, count: int = 1) -> List[Tuple[str, float]]:
        raise NotImplementedError

    def zpopmax(self, count: int = 1) -> List[Tuple[str, float]]:
        raise NotImplementedError

    def _get_tree_info(self) -> dict:
        raise NotImplementedError

    def _verify_integrity(self) -> bool:
        raise NotImplementedError
