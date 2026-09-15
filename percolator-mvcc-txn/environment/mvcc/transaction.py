"""Snapshot-isolated transactions over a multi-versioned column store."""

import time
from typing import Optional, Callable, Dict

from .oracle import TimestampOracle
from .storage import MemoryStorage, Column

# Lock time-to-live in milliseconds.
LOCK_TTL_MS = 100

# Maximum number of retries when encountering an active lock during reads.
MAX_RETRIES = 3

# Backoff time in milliseconds between retries.
BACKOFF_TIME_MS = 50


class Transaction:
    """Snapshot-isolated transaction over a multi-versioned column store."""

    def __init__(self, oracle: TimestampOracle, storage: MemoryStorage):
        self._oracle = oracle
        self._storage = storage
        self._start_ts: Optional[int] = None
        self._writes: Dict[bytes, bytes] = {}
        self._commit_filter: Optional[Callable[[bytes, bool], bool]] = None

    def set_commit_filter(
        self, filter_fn: Optional[Callable[[bytes, bool], bool]]
    ) -> None:
        """Install a filter fn(key: bytes, is_primary: bool) -> bool.
        During commit, only keys where fn returns True have their commit
        finalized.  Used for testing partial failure scenarios."""
        self._commit_filter = filter_fn

    def begin(self) -> None:
        """Start the transaction."""
        self._start_ts = self._oracle.get_timestamp()
        self._writes = {}

    def get(self, key: bytes) -> bytes:
        """Read the committed value for key visible in this transaction's
        snapshot.  Returns b"" if no committed value exists."""
        raise NotImplementedError

    def set(self, key: bytes, value: bytes) -> None:
        """Buffer a write for commit."""
        self._writes[key] = value

    def commit(self) -> bool:
        """Atomically commit all buffered writes.
        Returns True on success, False on abort."""
        raise NotImplementedError
