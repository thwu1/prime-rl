"""
Left-Right Concurrent Multi-Value Map — Implementation

Uses the left-right concurrency pattern: two copies of a dict, epoch-based
reader tracking, and an operational log with swap_index for dual application.
"""

import threading
import copy
import time
from typing import Optional, List, Any, Tuple


class _SharedState:
    """Shared mutable state between read and write handles."""

    def __init__(self):
        self.read_copy: Optional[dict] = {}
        self.write_copy: dict = {}
        self.epochs_lock = threading.Lock()
        self.epoch_trackers: list = []  # each element is [int]
        self.dropped = False


class ReadGuard:
    """RAII guard giving read access to a snapshot of the map."""

    def __init__(self, data: dict, epoch_ref: list):
        self._data = data
        self._epoch_ref = epoch_ref
        self._released = False

    def _check(self):
        if self._released:
            raise RuntimeError("ReadGuard already released")

    def get(self, key: Any) -> Optional[List]:
        self._check()
        if key in self._data:
            return self._data[key]
        return None

    def contains_key(self, key: Any) -> bool:
        self._check()
        return key in self._data

    def len(self) -> int:
        self._check()
        return len(self._data)

    def keys(self) -> List:
        self._check()
        return list(self._data.keys())

    def release(self):
        if not self._released:
            self._epoch_ref[0] += 1  # odd -> even
            self._released = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()

    def __del__(self):
        self.release()


class ReadHandle:
    """Per-thread read handle with its own epoch counter."""

    def __init__(self, state: _SharedState):
        self._state = state
        self._epoch: list = [0]  # even = idle
        with self._state.epochs_lock:
            self._state.epoch_trackers.append(self._epoch)

    def enter(self) -> Optional[ReadGuard]:
        if self._state.dropped:
            return None
        self._epoch[0] += 1  # even -> odd (entering)
        data = self._state.read_copy
        if data is None:
            self._epoch[0] += 1  # restore even
            return None
        return ReadGuard(data, self._epoch)

    def get(self, key: Any) -> Optional[List]:
        guard = self.enter()
        if guard is None:
            return None
        try:
            return guard.get(key)
        finally:
            guard.release()

    def contains_key(self, key: Any) -> bool:
        guard = self.enter()
        if guard is None:
            return False
        try:
            return guard.contains_key(key)
        finally:
            guard.release()

    def len(self) -> int:
        guard = self.enter()
        if guard is None:
            return 0
        try:
            return guard.len()
        finally:
            guard.release()

    def keys(self) -> List:
        guard = self.enter()
        if guard is None:
            return []
        try:
            return guard.keys()
        finally:
            guard.release()

    def clone(self) -> "ReadHandle":
        new = ReadHandle.__new__(ReadHandle)
        new._state = self._state
        new._epoch = [0]
        with new._state.epochs_lock:
            new._state.epoch_trackers.append(new._epoch)
        return new

    def was_dropped(self) -> bool:
        return self._state.dropped


class WriteHandle:
    """Single-writer handle with oplog and publish mechanics."""

    def __init__(self, state: _SharedState):
        self._state = state
        self._oplog: list = []
        self._swap_index: int = 0
        self._first: bool = True
        self._second: bool = True
        self._last_epochs: list = []

    # ------------------------------------------------------------------
    # Operation buffering
    # ------------------------------------------------------------------

    def insert(self, key: Any, value: Any):
        if self._first:
            self._state.write_copy.setdefault(key, []).append(value)
        else:
            self._oplog.append(("insert", key, value))

    def remove_value(self, key: Any, value: Any):
        if self._first:
            w = self._state.write_copy
            if key in w:
                try:
                    w[key].remove(value)
                except ValueError:
                    pass
                if not w[key]:
                    del w[key]
        else:
            self._oplog.append(("remove_value", key, value))

    def remove_entry(self, key: Any):
        if self._first:
            self._state.write_copy.pop(key, None)
        else:
            self._oplog.append(("remove_entry", key, None))

    def clear(self):
        if self._first:
            self._state.write_copy.clear()
        else:
            self._oplog.append(("clear", None, None))

    def has_pending(self) -> bool:
        return self._swap_index < len(self._oplog)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish(self):
        self._state.epochs_lock.acquire()
        try:
            self._wait_for_readers()
            self._update_and_swap()
        finally:
            self._state.epochs_lock.release()

    def _wait_for_readers(self):
        """Spin until every active reader has completed."""
        for tracker in self._state.epoch_trackers:
            while tracker[0] % 2 == 1:
                self._state.epochs_lock.release()
                time.sleep(0.0001)
                self._state.epochs_lock.acquire()

    @staticmethod
    def _apply_op(data: dict, op: tuple):
        kind, key, value = op
        if kind == "insert":
            data.setdefault(key, []).append(value)
        elif kind == "remove_value":
            if key in data:
                try:
                    data[key].remove(value)
                except ValueError:
                    pass
                if not data[key]:
                    del data[key]
        elif kind == "remove_entry":
            data.pop(key, None)
        elif kind == "clear":
            data.clear()

    def _update_and_swap(self):
        if not self._first:
            w = self._state.write_copy

            if self._second:
                # sync_with: deep copy read into write
                self._state.write_copy = copy.deepcopy(self._state.read_copy)
                w = self._state.write_copy
                self._second = False

            # Replay all pending ops
            for op in self._oplog:
                self._apply_op(w, op)
            self._oplog.clear()
            self._swap_index = 0
        else:
            self._first = False

        # Swap the two copies
        self._state.read_copy, self._state.write_copy = (
            self._state.write_copy,
            self._state.read_copy,
        )

        # Snapshot current reader epochs
        self._last_epochs = [t[0] for t in self._state.epoch_trackers]

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def destroy(self):
        if self._first or self._oplog:
            self.publish()
        if self._oplog:
            self.publish()
        self._state.dropped = True
        self._state.read_copy = None


class LeftRightMap:
    """Factory for creating left-right map handle pairs."""

    @staticmethod
    def new() -> Tuple[WriteHandle, ReadHandle]:
        state = _SharedState()
        w = WriteHandle(state)
        r = ReadHandle(state)
        return w, r
