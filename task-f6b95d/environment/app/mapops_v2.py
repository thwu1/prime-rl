"""Optimized mapping operations using iterative scan."""

import bisect
from sortedmap import SortedMapping


def range_lookup(m: SortedMapping, lo: int, hi: int) -> SortedMapping:
    """
    Optimized range lookup using iterative scan from lower bound.

    pre: lo <= hi
    post: all(lo <= k <= hi for k in __return__.keys())
    post: __return__.size() <= m.size()
    post: all(__return__.get(k) == m.get(k) for k in __return__.keys())
    """
    result = SortedMapping()
    idx = bisect.bisect_left(m._keys, lo)
    while idx < len(m._keys) and m._keys[idx] < hi:
        result.put(m._keys[idx], m._values[idx])
        idx += 1
    return result
