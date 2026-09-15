"""Abstract interface for a B+ tree-backed sorted set.


Elements are (member, score) pairs where member is a unique string and score is
a float.  Elements are ordered by (score, member) -- ascending by score first,
then lexicographically by member for equal scores.  This matches Redis sorted
set semantics.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple


class SortedSetInterface(ABC):

    # ── mutators ──────────────────────────────────────────────────────────

    @abstractmethod
    def zadd(
        self,
        items: List[Tuple[float, str]],
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
        ch: bool = False,
    ) -> int:
        """Add or update members with scores.

        Parameters
        ----------
        items : list of (score, member) pairs.
        nx    : Only add new elements; never update existing ones.
        xx    : Only update existing elements; never add new ones.
        gt    : Only update if new score > current score.  Does NOT prevent adds.
        lt    : Only update if new score < current score.  Does NOT prevent adds.
        ch    : Return count of *changed* elements (added + updated) instead of
                only newly added elements.

        Returns
        -------
        int : number added (default), or added+changed when *ch* is True.
        """

    @abstractmethod
    def zincrby(self, member: str, increment: float) -> float:
        """Increment *member*'s score by *increment*.

        If the member does not exist, it is added with *increment* as its score.
        Returns the new score.
        """

    @abstractmethod
    def zrem(self, *members: str) -> int:
        """Remove the listed members.  Returns number actually removed."""

    # ── queries ────────────────────────────────────────────────────────────

    @abstractmethod
    def zscore(self, member: str) -> Optional[float]:
        """Return *member*'s score, or ``None`` if absent."""

    @abstractmethod
    def zcard(self) -> int:
        """Return the number of elements."""

    @abstractmethod
    def zrank(self, member: str) -> Optional[int]:
        """0-based rank ordered low-to-high.  ``None`` if absent."""

    @abstractmethod
    def zrevrank(self, member: str) -> Optional[int]:
        """0-based rank ordered high-to-low.  ``None`` if absent."""

    # ── range by rank ──────────────────────────────────────────────────────

    @abstractmethod
    def zrange(
        self,
        start: int,
        stop: int,
        reverse: bool = False,
        withscores: bool = True,
    ) -> list:
        """Elements in rank range [start, stop] (inclusive, supports negatives).

        Returns list of ``(member, score)`` when *withscores* is True,
        else list of member strings.
        """

    # ── range by score ─────────────────────────────────────────────────────

    @abstractmethod
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
        """Elements with score in the given range.

        Use ``float('-inf')`` / ``float('inf')`` for open-ended ranges.
        *offset* and *count* provide LIMIT-style pagination (count=-1 means all).
        """

    @abstractmethod
    def zcount(
        self,
        min_score: float,
        max_score: float,
        min_exclusive: bool = False,
        max_exclusive: bool = False,
    ) -> int:
        """Count elements whose score falls in the range."""

    # ── pop ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def zpopmin(self, count: int = 1) -> List[Tuple[str, float]]:
        """Remove and return up to *count* elements with the lowest scores."""

    @abstractmethod
    def zpopmax(self, count: int = 1) -> List[Tuple[str, float]]:
        """Remove and return up to *count* elements with the highest scores."""

    # ── introspection (for structural tests) ────────────────────────────────

    @abstractmethod
    def _get_tree_info(self) -> dict:
        """Return a dict with at least these keys:

        - ``height``            : int, tree height (1 for a single leaf root)
        - ``node_count``        : int, total nodes in the tree
        - ``max_keys_per_node`` : int, configured maximum keys per node
        - ``total_elements``    : int, number of data elements stored
        """

    @abstractmethod
    def _verify_integrity(self) -> bool:
        """Verify internal B+ tree invariants.

        Must check at minimum:
        1. All leaves are at the same depth.
        2. Subtree counts in internal nodes match actual descendant leaf counts.
        3. Keys are in strictly increasing order within each node and globally
           (via the leaf linked list).
        4. Non-root nodes have >= floor(max_keys/2) keys.
        5. No node exceeds max_keys keys.

        Returns True if all invariants hold.
        """
