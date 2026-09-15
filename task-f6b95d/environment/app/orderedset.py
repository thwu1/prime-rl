"""Ordered set data structure maintaining unique elements in sorted order."""

import bisect
from typing import List, Optional


class OrderedSet:
    """A set that maintains its elements in sorted order with no duplicates."""

    def __init__(self, elements=None):
        if elements is None:
            self._data: List[int] = []
        else:
            self._data = sorted(set(elements))

    def add(self, val: int) -> None:
        idx = bisect.bisect_left(self._data, val)
        if idx < len(self._data) and self._data[idx] == val:
            return
        self._data.insert(idx, val)

    def remove(self, val: int) -> bool:
        idx = bisect.bisect_left(self._data, val)
        if idx < len(self._data) and self._data[idx] == val:
            self._data.pop(idx)
            return True
        return False

    def contains(self, val: int) -> bool:
        idx = bisect.bisect_left(self._data, val)
        return idx < len(self._data) and self._data[idx] == val

    def size(self) -> int:
        return len(self._data)

    def to_list(self) -> List[int]:
        return list(self._data)

    def kth(self, k: int) -> int:
        return self._data[k]

    def minimum(self) -> Optional[int]:
        return self._data[0] if self._data else None

    def maximum(self) -> Optional[int]:
        return self._data[-1] if self._data else None

    def __eq__(self, other):
        if not isinstance(other, OrderedSet):
            return NotImplemented
        return self._data == other._data

    def __repr__(self):
        return f"OrderedSet({self._data})"

    def __len__(self):
        return len(self._data)

    def __deepcopy__(self, memo):
        new = OrderedSet()
        new._data = list(self._data)
        return new
