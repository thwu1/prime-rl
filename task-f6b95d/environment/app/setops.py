"""Set operations on OrderedSet with PEP 316 contracts."""

import bisect
from typing import List
from orderedset import OrderedSet


def union(s1: OrderedSet, s2: OrderedSet) -> OrderedSet:
    """
    Return a new OrderedSet containing all elements from s1 and s2.

    pre: True
    post: __return__.size() >= s1.size()
    post: __return__.size() >= s2.size()
    post: __return__.size() <= s1.size() + s2.size()
    post: all(s1.contains(x) or s2.contains(x) for x in __return__.to_list())
    """
    result = OrderedSet()
    for val in s1.to_list():
        result.add(val)
    for val in s2.to_list():
        result.add(val)
    return result


def intersect(s1: OrderedSet, s2: OrderedSet) -> OrderedSet:
    """
    Return a new OrderedSet containing elements common to both sets.

    pre: True
    post: all(s1.contains(x) and s2.contains(x) for x in __return__.to_list())
    post: __return__.size() <= s1.size()
    post: __return__.size() <= s2.size()
    post: __return__.size() == min(s1.size(), s2.size())
    """
    result = OrderedSet()
    for val in s1.to_list():
        if s2.contains(val):
            result.add(val)
    return result


def difference(s1: OrderedSet, s2: OrderedSet) -> OrderedSet:
    """
    Return elements in s1 but not in s2.

    pre: True
    post: __return__.size() <= s1.size()
    post: all(s1.contains(x) and not s2.contains(x) for x in __return__.to_list())
    """
    result = OrderedSet()
    for val in s1.to_list():
        if not s2.contains(val):
            result.add(val)
    return result


def symmetric_difference(s1: OrderedSet, s2: OrderedSet) -> OrderedSet:
    """
    Return elements that are in exactly one of the two sets.

    pre: True
    post: __return__.size() <= s1.size() + s2.size()
    post: all(not (s1.contains(x) and s2.contains(x)) for x in __return__.to_list())
    post: all(s1.contains(x) or s2.contains(x) for x in __return__.to_list())
    """
    result = OrderedSet()
    list1, list2 = s1.to_list(), s2.to_list()
    i, j = 0, 0
    while i < len(list1) and j < len(list2):
        if list1[i] < list2[j]:
            result.add(list1[i])
            i += 1
        elif list1[i] > list2[j]:
            result.add(list2[j])
            j += 1
        else:
            i += 1
    while i < len(list1):
        result.add(list1[i])
        i += 1
    while j < len(list2):
        result.add(list2[j])
        j += 1
    return result


def range_count(s: OrderedSet, lo: int, hi: int) -> int:
    """
    Count elements x in s where lo <= x <= hi.

    pre: lo <= hi
    post: 0 <= __return__ <= s.size()
    post: __return__ == len([x for x in s.to_list() if lo <= x <= hi])
    """
    left = bisect.bisect_left(s._data, lo)
    right = bisect.bisect_right(s._data, hi)
    return right - left + 1


def kth_element(s: OrderedSet, k: int) -> int:
    """
    Return the k-th smallest element (0-indexed).

    pre: s.size() > 0
    pre: 0 <= k < s.size()
    post: s.contains(__return__)
    """
    return s.kth(k)
