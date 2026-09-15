"""
Interface for the Sorted Set data structure.

Your implementation in sorted_set.py must provide a class `SortedSet`
that implements all methods defined here.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple


class SortedSetInterface(ABC):
    """
    A sorted set stores unique string members, each with a float score.
    Entries are ordered by (score ASC, member ASC) -- ascending score
    with lexicographic tiebreaking on member name.
    """

    @abstractmethod
    def zadd(self, member: str, score: float) -> bool:
        """Add or update member with score.
        Returns True if the member was newly added.
        Returns False if the member already existed (score is updated)."""

    @abstractmethod
    def zrem(self, member: str) -> bool:
        """Remove member. Returns True if removed, False if not found."""

    @abstractmethod
    def zscore(self, member: str) -> Optional[float]:
        """Return score of member, or None if not found."""

    @abstractmethod
    def zrank(self, member: str) -> Optional[int]:
        """Return 0-based rank of member in ascending order.
        Returns None if member not found."""

    @abstractmethod
    def zrevrank(self, member: str) -> Optional[int]:
        """Return 0-based rank of member in descending order.
        Rank 0 = highest score. Returns None if member not found."""

    @abstractmethod
    def zcard(self) -> int:
        """Return the number of elements in the sorted set."""

    @abstractmethod
    def zcount(self, min_score: float, max_score: float) -> int:
        """Return the number of elements with score in [min_score, max_score]."""

    @abstractmethod
    def zrange_by_rank(self, start: int, stop: int) -> List[Tuple[str, float]]:
        """Return elements at ranks [start, stop] inclusive (0-based, ascending).
        Out-of-range indices are clamped. Returns [] if range is empty."""

    @abstractmethod
    def zrange_by_score(self, min_score: float, max_score: float,
                        offset: int = 0, count: int = -1) -> List[Tuple[str, float]]:
        """Return elements with score in [min_score, max_score], ascending order.
        Skip `offset` elements, return at most `count` (-1 means unlimited)."""

    @abstractmethod
    def zrevrange_by_rank(self, start: int, stop: int) -> List[Tuple[str, float]]:
        """Return elements at ranks [start, stop] inclusive (0-based, descending).
        Rank 0 = highest score. Out-of-range indices clamped."""

    @abstractmethod
    def node_count(self) -> int:
        """Return the total number of nodes in the internal tree structure."""

    @abstractmethod
    def height(self) -> int:
        """Return the height of the internal tree (1 = single root node)."""
