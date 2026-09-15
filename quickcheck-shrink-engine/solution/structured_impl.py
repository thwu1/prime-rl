"""Correct implementation of shrink_interval_set."""

from pbt.shrink import shrink_nonneg


def shrink_interval_set(intervals):
    """Shrink a sorted, non-overlapping set of integer intervals.

    All outputs maintain: 0 <= lo < hi, sorted by lo, non-overlapping.
    """
    if not intervals:
        return

    n = len(intervals)

    # Phase 0: yield empty list
    yield []

    # Phase 1: remove individual intervals (only if more than one)
    if n > 1:
        for i in range(n):
            yield intervals[:i] + intervals[i + 1:]

    # Phase 2: endpoint shrinking
    for i in range(n):
        lo, hi = intervals[i]

        # (a) Shrink hi toward lo + 1
        gap = hi - (lo + 1)
        for g in shrink_nonneg(gap):
            new_hi = lo + 1 + g
            yield intervals[:i] + [(lo, new_hi)] + intervals[i + 1:]

        # (b) Shrink lo toward lower bound
        lower_bound = intervals[i - 1][1] if i > 0 else 0
        gap = lo - lower_bound
        for g in shrink_nonneg(gap):
            new_lo = lower_bound + g
            yield intervals[:i] + [(new_lo, hi)] + intervals[i + 1:]
