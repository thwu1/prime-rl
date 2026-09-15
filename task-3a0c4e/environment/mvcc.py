
"""MVCC Transaction Engine — implement all methods.

Storage must use Redis on localhost:6379.  Start the Redis server
before running any operations.
"""

import threading
import time
from enum import Enum
from typing import Optional, Tuple, Any

LOCK_TTL_SECS = 0.5


class Column(Enum):
    WRITE = "write"
    DATA = "data"
    LOCK = "lock"


class TimestampOracle:
    """Thread-safe, strictly-increasing timestamp generator."""

    def __init__(self):
        raise NotImplementedError

    def get_timestamp(self) -> int:
        raise NotImplementedError


class KvTable:
    """Multi-version key-value store with three column families.

    Each column maps (key: bytes, timestamp: int) to a value.
    All data must be persisted in Redis.
    """

    def __init__(self):
        raise NotImplementedError

    def read(
        self,
        key: bytes,
        column: Column,
        ts_start: Optional[int] = None,
        ts_end: Optional[int] = None,
    ) -> Optional[Tuple[Tuple[bytes, int], Any]]:
        """Return ((key, ts), value) for the entry with the largest
        timestamp in [ts_start, ts_end], or None if no match."""
        raise NotImplementedError

    def write(self, key: bytes, column: Column, ts: int, value: Any):
        """Store value at (key, ts) in column."""
        raise NotImplementedError

    def erase(self, key: bytes, column: Column, ts: int):
        """Remove the entry at (key, ts) from column, if present."""
        raise NotImplementedError


class MemoryStorage:
    """Thread-safe transactional storage over a KvTable."""

    def __init__(self):
        raise NotImplementedError

    def get(self, key: bytes, start_ts: int) -> bytes:
        """Read key at snapshot timestamp start_ts.
        Returns b"" if no committed value is visible."""
        raise NotImplementedError

    def prewrite(
        self, key: bytes, value: bytes, start_ts: int, primary_key: bytes
    ) -> bool:
        """Prepare a write for key. Returns False on conflict."""
        raise NotImplementedError

    def commit(
        self, key: bytes, start_ts: int, commit_ts: int, is_primary: bool = False
    ) -> bool:
        """Finalize a prepared write. Returns False if the operation
        cannot proceed."""
        raise NotImplementedError


class Client:
    """Transaction client. Buffers writes and commits them atomically."""

    def __init__(self, tso: TimestampOracle, storage: MemoryStorage):
        raise NotImplementedError

    def begin(self):
        """Start a new transaction."""
        raise NotImplementedError

    def get(self, key: bytes) -> bytes:
        """Read key from storage at this transaction's snapshot."""
        raise NotImplementedError

    def set(self, key: bytes, value: bytes):
        """Buffer a write (not visible until commit)."""
        raise NotImplementedError

    def commit(self) -> bool:
        """Commit all buffered writes atomically. Returns True on success."""
        raise NotImplementedError
