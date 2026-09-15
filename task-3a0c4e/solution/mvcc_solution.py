
"""MVCC Transaction Engine — reference implementation with Redis backend."""

import threading
import time
import pickle
import uuid
from enum import Enum
from typing import Optional, Tuple, Any
from collections import OrderedDict

import redis as redis_lib

LOCK_TTL_SECS = 0.5


class Column(Enum):
    WRITE = "write"
    DATA = "data"
    LOCK = "lock"


class TimestampOracle:
    """Thread-safe, strictly-increasing timestamp generator."""

    def __init__(self):
        self._counter = 0
        self._lock = threading.Lock()

    def get_timestamp(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter


class KvTable:
    """Multi-version key-value store backed by Redis.

    Each column family is stored as a set of Redis hashes.
    Key schema:  {namespace}:{column}:{hex(raw_key)}
    Hash field:  str(timestamp)
    Hash value:  pickle(value)
    """

    def __init__(self, redis_client, namespace: str = ""):
        self._r = redis_client
        self._ns = namespace

    def _rkey(self, raw_key: bytes, column: Column) -> str:
        return f"{self._ns}:{column.value}:{raw_key.hex()}"

    def read(
        self,
        key: bytes,
        column: Column,
        ts_start: Optional[int] = None,
        ts_end: Optional[int] = None,
    ) -> Optional[Tuple[Tuple[bytes, int], Any]]:
        rk = self._rkey(key, column)
        all_fields = self._r.hgetall(rk)
        if not all_fields:
            return None

        best_ts = -1
        best_val = None
        for field_b, val_b in all_fields.items():
            ts = int(field_b.decode())
            if ts_start is not None and ts < ts_start:
                continue
            if ts_end is not None and ts > ts_end:
                continue
            if ts > best_ts:
                best_ts = ts
                best_val = pickle.loads(val_b)

        if best_ts < 0:
            return None
        return ((key, best_ts), best_val)

    def write(self, key: bytes, column: Column, ts: int, value: Any):
        rk = self._rkey(key, column)
        self._r.hset(rk, str(ts), pickle.dumps(value))

    def erase(self, key: bytes, column: Column, ts: int):
        rk = self._rkey(key, column)
        self._r.hdel(rk, str(ts))


class MemoryStorage:
    """Thread-safe transactional storage over a KvTable (Redis-backed)."""

    def __init__(self):
        self._ns = uuid.uuid4().hex[:12]
        self._r = redis_lib.Redis(host="localhost", port=6379, db=0)
        self._table = KvTable(self._r, self._ns)
        self._mu = threading.Lock()

    def get(self, key: bytes, start_ts: int) -> bytes:
        with self._mu:
            # Check for stale locks and clean up if expired
            lock_entry = self._table.read(key, Column.LOCK)
            if lock_entry is not None:
                lock_info = lock_entry[1]
                primary_key, lock_mono = lock_info
                if time.monotonic() - lock_mono >= LOCK_TTL_SECS:
                    lock_ts = lock_entry[0][1]
                    self._resolve_lock(key, lock_ts, primary_key)

            # Snapshot read: find latest committed write visible at start_ts
            write_entry = self._table.read(
                key, Column.WRITE, ts_start=0, ts_end=start_ts
            )
            if write_entry is None:
                return b""
            data_ts = write_entry[1]
            data_entry = self._table.read(
                key, Column.DATA, ts_start=data_ts, ts_end=data_ts
            )
            if data_entry is None:
                return b""
            return data_entry[1]

    def _resolve_lock(
        self, key: bytes, lock_ts: int, primary_key: bytes
    ):
        """Resolve an expired lock by inspecting the primary's state."""
        if key == primary_key:
            # This IS the primary — no commit happened, roll back
            self._table.erase(key, Column.LOCK, lock_ts)
            self._table.erase(key, Column.DATA, lock_ts)
        else:
            # Secondary key — check what happened to the primary
            primary_lock = self._table.read(
                primary_key, Column.LOCK, ts_start=lock_ts, ts_end=lock_ts
            )
            if primary_lock is not None:
                # Primary still locked and expired — roll back both
                p_info = primary_lock[1]
                if time.monotonic() - p_info[1] >= LOCK_TTL_SECS:
                    self._table.erase(primary_key, Column.LOCK, lock_ts)
                    self._table.erase(primary_key, Column.DATA, lock_ts)
                    self._table.erase(key, Column.LOCK, lock_ts)
                    self._table.erase(key, Column.DATA, lock_ts)
            else:
                # Primary lock gone — did it commit?
                write_entry = self._table.read(
                    primary_key, Column.WRITE, ts_start=lock_ts
                )
                if write_entry is not None and write_entry[1] == lock_ts:
                    # Primary committed — roll forward this secondary
                    commit_ts = write_entry[0][1]
                    self._table.write(key, Column.WRITE, commit_ts, lock_ts)
                    self._table.erase(key, Column.LOCK, lock_ts)
                else:
                    # Primary rolled back — roll back this secondary too
                    self._table.erase(key, Column.LOCK, lock_ts)
                    self._table.erase(key, Column.DATA, lock_ts)

    def prewrite(
        self, key: bytes, value: bytes, start_ts: int, primary_key: bytes
    ) -> bool:
        with self._mu:
            # Conflict: committed write after our start timestamp
            write_after = self._table.read(key, Column.WRITE, ts_start=start_ts)
            if write_after is not None:
                return False
            # Conflict: another transaction holds a lock
            existing_lock = self._table.read(key, Column.LOCK)
            if existing_lock is not None:
                return False
            # Write data and acquire lock
            self._table.write(key, Column.DATA, start_ts, value)
            self._table.write(
                key, Column.LOCK, start_ts, (primary_key, time.monotonic())
            )
            return True

    def commit(
        self, key: bytes, start_ts: int, commit_ts: int, is_primary: bool = False
    ) -> bool:
        with self._mu:
            if is_primary:
                lock = self._table.read(
                    key, Column.LOCK, ts_start=start_ts, ts_end=start_ts
                )
                if lock is None:
                    return False
            # Record the commit and release the lock
            self._table.write(key, Column.WRITE, commit_ts, start_ts)
            self._table.erase(key, Column.LOCK, start_ts)
            return True


class Client:
    """Transaction client. Buffers writes and commits them atomically."""

    def __init__(self, tso: TimestampOracle, storage: MemoryStorage):
        self._tso = tso
        self._storage = storage
        self._start_ts = 0
        self._writes: OrderedDict = OrderedDict()

    def begin(self):
        self._start_ts = self._tso.get_timestamp()
        self._writes = OrderedDict()

    def get(self, key: bytes) -> bytes:
        return self._storage.get(key, self._start_ts)

    def set(self, key: bytes, value: bytes):
        self._writes[key] = value

    def commit(self) -> bool:
        if not self._writes:
            return True

        keys = list(self._writes.keys())
        primary = keys[0]

        # Phase 1: prepare all keys
        for k in keys:
            if not self._storage.prewrite(
                k, self._writes[k], self._start_ts, primary
            ):
                return False

        commit_ts = self._tso.get_timestamp()

        # Phase 2: commit primary first, then secondaries
        if not self._storage.commit(
            primary, self._start_ts, commit_ts, is_primary=True
        ):
            return False
        for k in keys[1:]:
            self._storage.commit(k, self._start_ts, commit_ts)

        return True
