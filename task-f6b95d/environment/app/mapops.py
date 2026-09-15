"""Mapping operations on SortedMapping with PEP 316 contracts."""

import bisect
from typing import List, Optional
from orderedset import OrderedSet
from sortedmap import SortedMapping


def merge_mappings(m1: SortedMapping, m2: SortedMapping) -> SortedMapping:
    """
    Merge two sorted mappings. For keys present in both, sum the values.

    pre: True
    post: all(__return__.contains_key(k) for k in m1.keys())
    post: all(__return__.contains_key(k) for k in m2.keys())
    post: all(__return__.get(k) == m1.get(k) + m2.get(k) for k in m1.keys() if m2.contains_key(k))
    post: all(__return__.get(k) == m1.get(k) for k in m1.keys() if not m2.contains_key(k))
    post: all(__return__.get(k) == m2.get(k) for k in m2.keys() if not m1.contains_key(k))
    """
    result = SortedMapping()
    for k, v in m1.items():
        result.put(k, v)
    for k, v in m2.items():
        result.put(k, v)
    return result


def invert_mapping(m: SortedMapping) -> SortedMapping:
    """
    Swap keys and values. Only valid when all values are unique.

    pre: len(set(m.values())) == m.size()
    post: __return__.size() == m.size()
    post: all(__return__.contains_key(v) for k, v in m.items())
    post: all(__return__.get(v) == k for k, v in m.items())
    """
    result = SortedMapping()
    for k, v in m.items():
        result.put(v, k)
    return result


def range_lookup(m: SortedMapping, lo: int, hi: int) -> SortedMapping:
    """
    Return a submapping containing only keys k where lo <= k <= hi.

    pre: lo <= hi
    post: all(lo <= k <= hi for k in __return__.keys())
    post: __return__.size() <= m.size()
    post: all(__return__.get(k) == m.get(k) for k in __return__.keys())
    post: all(__return__.contains_key(k) for k in m.keys() if lo < k < hi)
    """
    result = SortedMapping()
    left = bisect.bisect_left(m._keys, lo)
    right = bisect.bisect_left(m._keys, hi)
    for i in range(left, right):
        result.put(m._keys[i], m._values[i])
    return result


def sum_values_in_range(m: SortedMapping, lo_key: int, hi_key: int) -> int:
    """
    Sum all values whose keys are in [lo_key, hi_key].

    pre: lo_key <= hi_key
    post: __return__ == sum(v for k, v in m.items() if lo_key <= k <= hi_key)
    """
    left = bisect.bisect_left(m._keys, lo_key)
    right = bisect.bisect_right(m._keys, hi_key)
    total = 0
    for i in range(left, right):
        total += m._keys[i]
    return total


def keys_with_value_in(m: SortedMapping, values: OrderedSet) -> OrderedSet:
    """
    Return the set of keys whose values are members of the given value set.

    pre: True
    """
    result = OrderedSet()
    for k, v in m.items():
        if values.contains(v):
            result.add(k)
    return result


def key_of_max_value(m: SortedMapping) -> int:
    """
    Return the key with the largest value. For ties, return the smallest key.

    pre: m.size() > 0
    """
    max_val = m.value_at(0)
    max_key = m.key_at(0)
    for i in range(1, m.size()):
        if m.value_at(i) > max_val:
            max_val = m.value_at(i)
            max_key = m.key_at(i)
    return max_key
