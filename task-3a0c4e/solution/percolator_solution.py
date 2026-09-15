
"""
Percolator-style MVCC Transaction Engine — reference implementation.
"""

import threading
import time
from enum import Enum
from typing import Optional, Tuple, Any, Dict, List

LOCK_TTL_SECS = 0.5


class Column(Enum):
    WRITE = "write"
    DATA = "data"
    LOCK = "lock"


class TimestampOracle:
    def __init__(self):
        self._counter = 0
        self._lock = threading.Lock()

    def get_timestamp(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter


class KvTable:
    def __init__(self):
        self._columns: Dict[Column, Dict[Tuple[bytes, int], Any]] = {
            Column.WRITE: {},
            Column.DATA: {},
            Column.LOCK: {},
        }

    def read(
        self,
        key: bytes,
        column: Column,
        ts_start: Optional[int] = None,
        ts_end: Optional[int] = None,
    ) -> Optional[Tuple[Tuple[bytes, int], Any]]:
        col = self._columns[column]
        best = None
        for (k, ts), val in col.items():
            if k != key:
                continue
            if ts_start is not None and ts < ts_start:
                continue
            if ts_end is not None and ts > ts_end:
                continue
            if best is None or ts > best[0][1]:
                best = ((k, ts), val)
        return best

    def write(self, key: bytes, column: Column, ts: int, value: Any):
        self._columns[column][(key, ts)] = value

    def erase(self, key: bytes, column: Column, ts: int):
        self._columns[column].pop((key, ts), None)


class MemoryStorage:
    def __init__(self):
        self._table = KvTable()
        self._mu = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: bytes, start_ts: int) -> bytes:
        for _ in range(300):
            with self._mu:
                lock_entry = self._table.read(
                    key, Column.LOCK, ts_start=0, ts_end=start_ts
                )
                if lock_entry is None:
                    return self._read_committed(key, start_ts)

                (_, lock_ts), (primary_key, creation_time) = lock_entry
                if time.monotonic() - creation_time > LOCK_TTL_SECS:
                    cleaned = self._clean_up_lock(key, lock_ts, primary_key)
                    if cleaned:
                        # Re-check immediately (still holding the lock)
                        if self._table.read(key, Column.LOCK, ts_start=0, ts_end=start_ts) is None:
                            return self._read_committed(key, start_ts)
                        # Lock replaced or another lock appeared; loop again
                        continue

            # Lock not yet expired, or cleanup couldn't proceed — back off
            time.sleep(0.01)

        raise TimeoutError(f"Could not read key {key!r}: lock not released")

    def prewrite(
        self, key: bytes, value: bytes, start_ts: int, primary_key: bytes
    ) -> bool:
        with self._mu:
            # 1. Write-write conflict
            ww = self._table.read(key, Column.WRITE, ts_start=start_ts, ts_end=None)
            if ww is not None:
                return False

            # 2. Lock conflict
            lc = self._table.read(key, Column.LOCK, ts_start=0, ts_end=None)
            if lc is not None:
                return False

            # 3. Write data + lock
            self._table.write(key, Column.DATA, start_ts, value)
            self._table.write(
                key, Column.LOCK, start_ts, (primary_key, time.monotonic())
            )
            return True

    def commit(
        self, key: bytes, start_ts: int, commit_ts: int, is_primary: bool
    ) -> bool:
        with self._mu:
            if is_primary:
                lock = self._table.read(
                    key, Column.LOCK, ts_start=start_ts, ts_end=start_ts
                )
                if lock is None:
                    return False

            self._table.write(key, Column.WRITE, commit_ts, start_ts)
            self._table.erase(key, Column.LOCK, start_ts)
            return True

    # ------------------------------------------------------------------
    # Internal helpers (must be called with self._mu held)
    # ------------------------------------------------------------------

    def _read_committed(self, key: bytes, start_ts: int) -> bytes:
        write_entry = self._table.read(
            key, Column.WRITE, ts_start=0, ts_end=start_ts
        )
        if write_entry is None:
            return b""
        (_, _commit_ts), data_start_ts = write_entry
        data_entry = self._table.read(
            key, Column.DATA, ts_start=data_start_ts, ts_end=data_start_ts
        )
        if data_entry is None:
            return b""
        return data_entry[1]

    def _clean_up_lock(
        self, key: bytes, lock_ts: int, primary_key: bytes
    ) -> bool:
        """Attempt to resolve an expired lock. Returns True if resolved."""
        if primary_key == key:
            # This IS the primary — roll back unconditionally.
            self._table.erase(key, Column.LOCK, lock_ts)
            self._table.erase(key, Column.DATA, lock_ts)
            return True

        # Secondary key — inspect primary.
        primary_lock = self._table.read(
            primary_key, Column.LOCK, ts_start=lock_ts, ts_end=lock_ts
        )
        if primary_lock is not None:
            # Primary lock still present — check if it too has expired.
            (_, _), (_, p_creation_time) = primary_lock
            if time.monotonic() - p_creation_time > LOCK_TTL_SECS:
                # Both expired → roll back primary and secondary.
                self._table.erase(primary_key, Column.LOCK, lock_ts)
                self._table.erase(primary_key, Column.DATA, lock_ts)
                self._table.erase(key, Column.LOCK, lock_ts)
                self._table.erase(key, Column.DATA, lock_ts)
                return True
            # Primary not expired yet — can't decide; caller should back off.
            return False

        # Primary lock gone — did the transaction commit?
        commit_ts_found = None
        for (k, ts), val in list(self._table._columns[Column.WRITE].items()):
            if k == primary_key and val == lock_ts:
                commit_ts_found = ts
                break

        if commit_ts_found is not None:
            # Primary committed → roll forward this secondary.
            self._table.write(key, Column.WRITE, commit_ts_found, lock_ts)
            self._table.erase(key, Column.LOCK, lock_ts)
            return True

        # Primary was rolled back → roll back this secondary too.
        self._table.erase(key, Column.LOCK, lock_ts)
        self._table.erase(key, Column.DATA, lock_ts)
        return True


class Client:
    def __init__(self, tso: TimestampOracle, storage: MemoryStorage):
        self._tso = tso
        self._storage = storage
        self._start_ts: int = 0
        self._writes: Dict[bytes, bytes] = {}

    def begin(self):
        self._start_ts = self._tso.get_timestamp()
        self._writes = {}

    def get(self, key: bytes) -> bytes:
        return self._storage.get(key, self._start_ts)

    def set(self, key: bytes, value: bytes):
        self._writes[key] = value

    def commit(self) -> bool:
        if not self._writes:
            return True

        keys = list(self._writes.keys())
        primary_key = keys[0]

        # Phase 1 — prewrite
        for key in keys:
            if not self._storage.prewrite(
                key, self._writes[key], self._start_ts, primary_key
            ):
                return False

        # Phase 2 — commit
        commit_ts = self._tso.get_timestamp()

        if not self._storage.commit(
            primary_key, self._start_ts, commit_ts, is_primary=True
        ):
            return False

        for key in keys[1:]:
            self._storage.commit(key, self._start_ts, commit_ts, is_primary=False)

        return True
