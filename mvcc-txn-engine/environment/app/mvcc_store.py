"""Persistent MVCC key-value store backed by SQLite."""


from abc import ABC, abstractmethod


class ConflictError(Exception):
    """Raised when a serializable transaction detects a conflict at commit time."""
    pass


class Watermark:
    """Tracks the minimum read timestamp across all active transactions."""

    def __init__(self):
        raise NotImplementedError

    def add_reader(self, read_ts: int) -> None:
        raise NotImplementedError

    def remove_reader(self, read_ts: int) -> None:
        raise NotImplementedError

    def watermark(self) -> int | None:
        """Returns the minimum active read timestamp, or None if no active readers."""
        raise NotImplementedError


class CompactionFilter(ABC):
    @abstractmethod
    def filter(self, key: str) -> bool:
        """Return True if the key should be removed during garbage collection."""
        ...


class MVCCStore:
    def __init__(self, db_path: str, serializable: bool = True):
        raise NotImplementedError

    def new_txn(self) -> "Transaction":
        raise NotImplementedError

    def gc(self) -> int:
        """Remove obsolete versions and return the count of versions removed."""
        raise NotImplementedError

    def add_compaction_filter(self, f: CompactionFilter) -> None:
        raise NotImplementedError

    def remove_compaction_filter(self, f: CompactionFilter) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Flush all state and close the database connection."""
        raise NotImplementedError


class Transaction:
    def __init__(self, store: MVCCStore, read_ts: int, serializable: bool):
        raise NotImplementedError

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def put(self, key: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def scan(self, start: str, end: str) -> list[tuple[str, str]]:
        raise NotImplementedError

    def commit(self) -> int:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError
