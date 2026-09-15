"""Sorted mapping from int keys to int values, maintaining sorted key order."""

import bisect
from typing import List, Optional, Tuple


class SortedMapping:
    """A mapping from int keys to int values, keys always in sorted order.

    Invariants:
    - _keys is sorted in ascending order with no duplicates
    - len(_keys) == len(_values)
    - _keys[i] maps to _values[i]
    """

    def __init__(self, pairs=None):
        if pairs is None:
            self._keys: List[int] = []
            self._values: List[int] = []
        else:
            seen = {}
            for k, v in pairs:
                seen[k] = v
            sorted_items = sorted(seen.items())
            self._keys = [k for k, v in sorted_items]
            self._values = [v for k, v in sorted_items]

    def put(self, key: int, value: int) -> None:
        idx = bisect.bisect_left(self._keys, key)
        if idx < len(self._keys) and self._keys[idx] == key:
            self._values[idx] = value
        else:
            self._keys.insert(idx, key)
            self._values.insert(idx, value)

    def get(self, key: int) -> Optional[int]:
        idx = bisect.bisect_left(self._keys, key)
        if idx < len(self._keys) and self._keys[idx] == key:
            return self._values[idx]
        return None

    def contains_key(self, key: int) -> bool:
        idx = bisect.bisect_left(self._keys, key)
        return idx < len(self._keys) and self._keys[idx] == key

    def remove(self, key: int) -> bool:
        idx = bisect.bisect_left(self._keys, key)
        if idx < len(self._keys) and self._keys[idx] == key:
            self._keys.pop(idx)
            self._values.pop(idx)
            return True
        return False

    def size(self) -> int:
        return len(self._keys)

    def keys(self) -> List[int]:
        return list(self._keys)

    def values(self) -> List[int]:
        return list(self._values)

    def items(self) -> List[Tuple[int, int]]:
        return list(zip(self._keys, self._values))

    def key_at(self, idx: int) -> int:
        return self._keys[idx]

    def value_at(self, idx: int) -> int:
        return self._values[idx]

    def __eq__(self, other):
        if not isinstance(other, SortedMapping):
            return NotImplemented
        return self._keys == other._keys and self._values == other._values

    def __repr__(self):
        return f"SortedMapping({list(zip(self._keys, self._values))})"

    def __len__(self):
        return len(self._keys)

    def __deepcopy__(self, memo):
        new = SortedMapping()
        new._keys = list(self._keys)
        new._values = list(self._values)
        return new
