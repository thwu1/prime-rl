import threading
from typing import Optional, Tuple, Any, List


class Column:
    """Column family identifiers for the multi-versioned storage."""

    WRITE = "write"
    DATA = "data"
    LOCK = "lock"


class MemoryStorage:
    """
    Multi-versioned key-value store with three column families (Write, Data, Lock).
    Thread-safe with RLock for atomic multi-operation sequences.
    """

    def __init__(self):
        self._mutex = threading.RLock()
        self._columns = {
            Column.WRITE: {},
            Column.DATA: {},
            Column.LOCK: {},
        }

    def get_mutex(self) -> threading.RLock:
        return self._mutex

    def _get_col(self, column: str) -> dict:
        return self._columns[column]

    def read(
        self,
        key: bytes,
        column: str,
        ts_start_inclusive: Optional[int] = None,
        ts_end_inclusive: Optional[int] = None,
    ) -> Optional[Tuple[Tuple[bytes, int], Any]]:
        with self._mutex:
            col = self._get_col(column)
            best = None
            best_ts = -1
            for (k, ts), val in col.items():
                if k != key:
                    continue
                if ts_start_inclusive is not None and ts < ts_start_inclusive:
                    continue
                if ts_end_inclusive is not None and ts > ts_end_inclusive:
                    continue
                if ts > best_ts:
                    best_ts = ts
                    best = ((k, ts), val)
            return best

    def read_all(
        self,
        key: bytes,
        column: str,
        ts_start_inclusive: Optional[int] = None,
        ts_end_inclusive: Optional[int] = None,
    ) -> List[Tuple[Tuple[bytes, int], Any]]:
        with self._mutex:
            col = self._get_col(column)
            results = []
            for (k, ts), val in col.items():
                if k != key:
                    continue
                if ts_start_inclusive is not None and ts < ts_start_inclusive:
                    continue
                if ts_end_inclusive is not None and ts > ts_end_inclusive:
                    continue
                results.append(((k, ts), val))
            results.sort(key=lambda x: x[0][1], reverse=True)
            return results

    def write(self, key: bytes, column: str, ts: int, value: Any) -> None:
        with self._mutex:
            self._get_col(column)[(key, ts)] = value

    def erase(self, key: bytes, column: str, ts: int) -> None:
        with self._mutex:
            self._get_col(column).pop((key, ts), None)
