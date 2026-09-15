import time
from typing import Optional, Callable, Dict

from .oracle import TimestampOracle
from .storage import MemoryStorage, Column

# Lock time-to-live in milliseconds.
LOCK_TTL_MS = 100

# Maximum retries when encountering an active lock during reads.
MAX_RETRIES = 3

# Backoff time in milliseconds between retries.
BACKOFF_TIME_MS = 50


class Transaction:
    """
    Percolator-style distributed transaction with snapshot isolation.
    Implements two-phase commit over a multi-versioned key-value store.
    """

    def __init__(self, oracle: TimestampOracle, storage: MemoryStorage):
        self._oracle = oracle
        self._storage = storage
        self._start_ts: Optional[int] = None
        self._writes: Dict[bytes, bytes] = {}
        self._commit_filter: Optional[Callable[[bytes, bool], bool]] = None

    def set_commit_filter(
        self, filter_fn: Optional[Callable[[bytes, bool], bool]]
    ) -> None:
        self._commit_filter = filter_fn

    def begin(self) -> None:
        self._start_ts = self._oracle.get_timestamp()
        self._writes = {}

    # ------------------------------------------------------------------
    # get – snapshot read with lock resolution
    # ------------------------------------------------------------------

    def get(self, key: bytes) -> bytes:
        for attempt in range(MAX_RETRIES + 1):
            # 1. Check for locks from other transactions
            lock_entry = self._storage.read(
                key, Column.LOCK, ts_end_inclusive=self._start_ts
            )
            if lock_entry is not None:
                (_, lock_ts), (primary_key, lock_time_ns) = lock_entry
                if self._try_resolve_lock(key, lock_ts, primary_key, lock_time_ns):
                    continue  # lock resolved – retry the read
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_TIME_MS / 1000.0)
                    continue
                return b""

            # 2. Read write column: latest commit_ts <= start_ts
            write_entry = self._storage.read(
                key, Column.WRITE, ts_end_inclusive=self._start_ts
            )
            if write_entry is None:
                return b""

            (_, _commit_ts), data_start_ts = write_entry

            # 3. Read data column at (key, data_start_ts)
            data_entry = self._storage.read(
                key,
                Column.DATA,
                ts_start_inclusive=data_start_ts,
                ts_end_inclusive=data_start_ts,
            )
            if data_entry is None:
                return b""
            return data_entry[1]

        return b""

    # ------------------------------------------------------------------
    # Lock resolution helpers
    # ------------------------------------------------------------------

    def _try_resolve_lock(
        self,
        key: bytes,
        lock_ts: int,
        primary_key: bytes,
        lock_time_ns: int,
    ) -> bool:
        """Attempt to resolve a lock on *key*.  Returns True if resolved."""

        # Case A: key IS the primary
        if primary_key == key:
            elapsed_ms = (time.time_ns() - lock_time_ns) / 1_000_000
            if elapsed_ms >= LOCK_TTL_MS:
                # TTL expired – roll back
                self._storage.erase(key, Column.LOCK, lock_ts)
                self._storage.erase(key, Column.DATA, lock_ts)
                return True
            return False  # lock is still fresh

        # Case B: key is a secondary – look up the primary
        primary_lock = self._storage.read(
            primary_key,
            Column.LOCK,
            ts_start_inclusive=lock_ts,
            ts_end_inclusive=lock_ts,
        )

        if primary_lock is None:
            # Primary's lock is gone.  Was it committed or rolled back?
            commit_ts = self._find_commit_ts(primary_key, lock_ts)
            if commit_ts is not None:
                # Primary committed → roll forward this secondary
                self._storage.write(key, Column.WRITE, commit_ts, lock_ts)
                self._storage.erase(key, Column.LOCK, lock_ts)
            else:
                # Primary was rolled back → roll back this secondary
                self._storage.erase(key, Column.LOCK, lock_ts)
                self._storage.erase(key, Column.DATA, lock_ts)
            return True

        # Primary lock still exists – check TTL
        _, (_, primary_lock_time_ns) = primary_lock
        elapsed_ms = (time.time_ns() - primary_lock_time_ns) / 1_000_000
        if elapsed_ms >= LOCK_TTL_MS:
            # Stale – roll back the whole transaction
            self._storage.erase(primary_key, Column.LOCK, lock_ts)
            self._storage.erase(primary_key, Column.DATA, lock_ts)
            self._storage.erase(key, Column.LOCK, lock_ts)
            self._storage.erase(key, Column.DATA, lock_ts)
            return True

        return False  # active lock – back off

    def _find_commit_ts(self, primary_key: bytes, start_ts: int) -> Optional[int]:
        """Search the Write column for a record proving *primary_key* committed
        with the given *start_ts*.  Returns the commit_ts or None."""
        entries = self._storage.read_all(primary_key, Column.WRITE)
        for (_, commit_ts), val_start_ts in entries:
            if val_start_ts == start_ts:
                return commit_ts
        return None

    # ------------------------------------------------------------------
    # set – buffer locally
    # ------------------------------------------------------------------

    def set(self, key: bytes, value: bytes) -> None:
        self._writes[key] = value

    # ------------------------------------------------------------------
    # commit – two-phase commit
    # ------------------------------------------------------------------

    def commit(self) -> bool:
        if not self._writes:
            return True

        keys = sorted(self._writes.keys())
        primary = keys[0]
        secondaries = keys[1:]

        # ---- Phase 1: Prewrite ----
        prewritten = []
        for key in [primary] + secondaries:
            if self._prewrite(key, self._writes[key], primary):
                prewritten.append(key)
            else:
                # Conflict – clean up all prewrites so far
                for k in prewritten:
                    self._storage.erase(k, Column.LOCK, self._start_ts)
                    self._storage.erase(k, Column.DATA, self._start_ts)
                return False

        # ---- Phase 2: Commit ----
        commit_ts = self._oracle.get_timestamp()

        # 2a. Commit primary
        if self._commit_filter is None or self._commit_filter(primary, True):
            self._storage.write(
                primary, Column.WRITE, commit_ts, self._start_ts
            )
            self._storage.erase(primary, Column.LOCK, self._start_ts)
        else:
            # Primary commit dropped – clean up everything
            for k in prewritten:
                self._storage.erase(k, Column.LOCK, self._start_ts)
                self._storage.erase(k, Column.DATA, self._start_ts)
            return False

        # 2b. Commit secondaries
        for key in secondaries:
            if self._commit_filter is None or self._commit_filter(key, False):
                self._storage.write(
                    key, Column.WRITE, commit_ts, self._start_ts
                )
                self._storage.erase(key, Column.LOCK, self._start_ts)
            # If filtered, leave the lock for reader-side resolution

        return True

    # ------------------------------------------------------------------
    # Prewrite – atomic check-and-set for a single key
    # ------------------------------------------------------------------

    def _prewrite(self, key: bytes, value: bytes, primary: bytes) -> bool:
        """Prewrite one key.  Returns True on success, False on conflict."""
        with self._storage.get_mutex():
            # Check write-write conflict: any commit after our start_ts
            write_entry = self._storage.read(
                key, Column.WRITE, ts_start_inclusive=self._start_ts + 1
            )
            if write_entry is not None:
                return False

            # Check lock conflict: any existing lock on this key
            lock_entry = self._storage.read(key, Column.LOCK)
            if lock_entry is not None:
                return False

            # Write data
            self._storage.write(
                key, Column.DATA, self._start_ts, value
            )
            # Acquire lock
            self._storage.write(
                key,
                Column.LOCK,
                self._start_ts,
                (primary, time.time_ns()),
            )
            return True
