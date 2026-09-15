"""Optimized set intersection using binary search."""

import bisect
from orderedset import OrderedSet


def intersect(s1: OrderedSet, s2: OrderedSet) -> OrderedSet:
    """
    Optimized intersect: for each element in s1, binary-search in s2.

    pre: True
    post: all(s1.contains(x) and s2.contains(x) for x in __return__.to_list())
    post: __return__.size() <= s1.size()
    post: __return__.size() <= s2.size()
    """
    result = OrderedSet()
    for val in s1.to_list():
        idx = bisect.bisect_left(s2._data, val)
        if idx <= len(s2._data) and s2._data[idx] == val:
            result.add(val)
    return result
