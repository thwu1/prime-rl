"""Structured shrinking strategies for property-based testing.

These shrinkers maintain structural invariants while producing smaller values,
extending the base library for use with constrained data types.
"""

from pbt.shrink import shrink_nonneg


def shrink_interval_set(intervals):
    """Shrink a sorted, non-overlapping set of integer intervals.

    Input: a list of (lo, hi) tuples representing intervals where:
      - 0 <= lo < hi  for each pair
      - Pairs are sorted by lo
      - Non-overlapping: hi_i <= lo_{i+1} for consecutive pairs i, i+1

    All yielded shrunk values MUST also satisfy these invariants.

    Shrinking strategy (yield results in this exact order):

    Phase 0 — Empty:
      If the input is non-empty, yield the empty list [].

    Phase 1 — Removal:
      If len(intervals) > 1, for each index i from 0 to n-1,
      yield the list with interval i removed.

    Phase 2 — Endpoint shrinking:
      For each interval at index i with value (lo, hi):

      (a) Shrink hi toward (lo + 1):
          Compute gap = hi - (lo + 1).
          For each g in shrink_nonneg(gap):
            yield intervals with hi_i replaced by (lo + 1 + g).

      (b) Shrink lo toward its lower bound:
          lower_bound = intervals[i-1][1] if i > 0 else 0
          Compute gap = lo - lower_bound.
          For each g in shrink_nonneg(gap):
            yield intervals with lo_i replaced by (lower_bound + g).

    IMPLEMENT THIS FUNCTION.
    """
    raise NotImplementedError("shrink_interval_set must be implemented")
