"""
Sharded Concurrent Map — distributes keys across N left-right map instances.
"""

import hashlib
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, "/app")
from left_right_map import LeftRightMap, WriteHandle, ReadHandle


def _shard_index(key: Any, num_shards: int) -> int:
    """Deterministic shard assignment using SHA-256."""
    h = hashlib.sha256(str(key).encode("utf-8")).hexdigest()
    return int(h, 16) % num_shards


class ShardedWriteHandle:
    def __init__(self, writers: List[WriteHandle], num_shards: int):
        self._writers = writers
        self._num_shards = num_shards

    def shard_for_key(self, key: Any) -> int:
        return _shard_index(key, self._num_shards)

    def insert(self, key: Any, value: Any) -> None:
        self._writers[_shard_index(key, self._num_shards)].insert(key, value)

    def remove_value(self, key: Any, value: Any) -> None:
        self._writers[_shard_index(key, self._num_shards)].remove_value(key, value)

    def remove_entry(self, key: Any) -> None:
        self._writers[_shard_index(key, self._num_shards)].remove_entry(key)

    def clear(self) -> None:
        for w in self._writers:
            w.clear()

    def publish(self) -> None:
        for w in self._writers:
            w.publish()

    def has_pending(self) -> bool:
        return any(w.has_pending() for w in self._writers)

    def destroy(self) -> None:
        for w in self._writers:
            w.destroy()


class ShardedReadHandle:
    def __init__(self, readers: List[ReadHandle], num_shards: int):
        self._readers = readers
        self._num_shards = num_shards

    def get(self, key: Any) -> Optional[List]:
        return self._readers[_shard_index(key, self._num_shards)].get(key)

    def contains_key(self, key: Any) -> bool:
        return self._readers[_shard_index(key, self._num_shards)].contains_key(key)

    def len(self) -> int:
        return sum(r.len() for r in self._readers)

    def keys(self) -> List:
        result = []
        for r in self._readers:
            result.extend(r.keys())
        return result

    def shard_lens(self) -> Dict[int, int]:
        return {i: self._readers[i].len() for i in range(self._num_shards)}

    def clone(self) -> "ShardedReadHandle":
        return ShardedReadHandle(
            [r.clone() for r in self._readers],
            self._num_shards,
        )


class ShardedMap:
    @staticmethod
    def new(num_shards: int) -> Tuple[ShardedWriteHandle, ShardedReadHandle]:
        writers = []
        readers = []
        for _ in range(num_shards):
            w, r = LeftRightMap.new()
            writers.append(w)
            readers.append(r)
        return (
            ShardedWriteHandle(writers, num_shards),
            ShardedReadHandle(readers, num_shards),
        )
