"""Multi-versioned column-oriented key-value storage."""

import threading
from typing import Optional, Tuple, Any, List


class Column:
    """Column identifiers."""

    WRITE = "write"
    DATA = "data"
    LOCK = "lock"


class MemoryStorage:
    """Versioned key-value store with entries indexed by (key, column, timestamp).
    All operations must be thread-safe."""

    def __init__(self):
        raise NotImplementedError

    def get_mutex(self) -> threading.RLock:
        """Return the storage-wide reentrant mutex for external atomic sequences."""
        raise NotImplementedError

    def read(
        self,
        key: bytes,
        column: str,
        ts_start_inclusive: Optional[int] = None,
        ts_end_inclusive: Optional[int] = None,
    ) -> Optional[Tuple[Tuple[bytes, int], Any]]:
        """Read the entry with the highest timestamp in [ts_start, ts_end]
        for the given key and column.  Returns ((key, ts), value) or None.
        Unbounded on either side when the corresponding parameter is None."""
        raise NotImplementedError

    def read_all(
        self,
        key: bytes,
        column: str,
        ts_start_inclusive: Optional[int] = None,
        ts_end_inclusive: Optional[int] = None,
    ) -> List[Tuple[Tuple[bytes, int], Any]]:
        """Read all entries in [ts_start, ts_end] for the given key and column.
        Returns list of ((key, ts), value), ordered by timestamp descending."""
        raise NotImplementedError

    def write(self, key: bytes, column: str, ts: int, value: Any) -> None:
        """Write value at (key, column, ts)."""
        raise NotImplementedError

    def erase(self, key: bytes, column: str, ts: int) -> None:
        """Erase the entry at (key, column, ts) if it exists."""
        raise NotImplementedError
