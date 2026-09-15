"""
Persistent MVCC Key-Value Store with SQLite Backend — Reference Implementation
"""


import json
import sqlite3
import threading
import zlib
from abc import ABC, abstractmethod


def _key_hash(key: str) -> int:
    return zlib.crc32(key.encode()) & 0xFFFFFFFF


class ConflictError(Exception):
    pass


class Watermark:
    def __init__(self):
        self._readers: dict[int, int] = {}

    def add_reader(self, read_ts: int) -> None:
        self._readers[read_ts] = self._readers.get(read_ts, 0) + 1

    def remove_reader(self, read_ts: int) -> None:
        if read_ts in self._readers:
            self._readers[read_ts] -= 1
            if self._readers[read_ts] == 0:
                del self._readers[read_ts]

    def watermark(self) -> int | None:
        if not self._readers:
            return None
        return min(self._readers.keys())


class CompactionFilter(ABC):
    @abstractmethod
    def filter(self, key: str) -> bool:
        ...


class _CommittedTxnRecord:
    __slots__ = ("key_hashes", "write_keys")

    def __init__(self, key_hashes: set[int], write_keys: set[str]):
        self.key_hashes = key_hashes
        self.write_keys = write_keys


class MVCCStore:
    def __init__(self, db_path: str, serializable: bool = True):
        self._db_path = db_path
        self._serializable = serializable
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_tables()
        self._load_state()
        self._watermark = Watermark()
        self._commit_lock = threading.Lock()
        self._compaction_filters: list[CompactionFilter] = []

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS versions (
                key TEXT NOT NULL,
                ts INTEGER NOT NULL,
                value TEXT,
                PRIMARY KEY (key, ts)
            );
            CREATE TABLE IF NOT EXISTS committed_txns (
                commit_ts INTEGER PRIMARY KEY,
                key_hashes TEXT NOT NULL,
                write_keys TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (
                mkey TEXT PRIMARY KEY,
                mvalue TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def _load_state(self):
        row = self._conn.execute(
            "SELECT mvalue FROM metadata WHERE mkey = 'latest_commit_ts'"
        ).fetchone()
        self._latest_commit_ts = int(row[0]) if row else 0

        self._committed_txns: dict[int, _CommittedTxnRecord] = {}
        for row in self._conn.execute(
            "SELECT commit_ts, key_hashes, write_keys FROM committed_txns"
        ):
            self._committed_txns[row[0]] = _CommittedTxnRecord(
                key_hashes=set(json.loads(row[1])),
                write_keys=set(json.loads(row[2])),
            )

    def new_txn(self) -> "Transaction":
        read_ts = self._latest_commit_ts
        self._watermark.add_reader(read_ts)
        return Transaction(self, read_ts, self._serializable)

    def _get_version(self, key: str, read_ts: int) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM versions WHERE key = ? AND ts <= ? "
            "ORDER BY ts DESC LIMIT 1",
            (key, read_ts),
        ).fetchone()
        if row is None:
            return None
        return row[0]

    def _scan_versions(
        self, start: str, end: str, read_ts: int
    ) -> list[tuple[str, str]]:
        cursor = self._conn.execute(
            """
            SELECT v.key, v.value
            FROM versions v
            INNER JOIN (
                SELECT key, MAX(ts) AS max_ts
                FROM versions
                WHERE ts <= ?
                GROUP BY key
            ) latest ON v.key = latest.key AND v.ts = latest.max_ts
            WHERE v.key >= ? AND v.key < ? AND v.value IS NOT NULL
            ORDER BY v.key
            """,
            (read_ts, start, end),
        )
        return [(row[0], row[1]) for row in cursor]

    def _commit_txn(self, txn: "Transaction") -> int:
        with self._commit_lock:
            commit_ts = self._latest_commit_ts + 1

            if self._serializable and txn._write_set:
                for ts, record in self._committed_txns.items():
                    if txn._read_ts < ts:
                        for kh in txn._read_set:
                            if kh in record.key_hashes:
                                raise ConflictError(
                                    f"Read-write conflict with txn at ts={ts}"
                                )
                        for scan_start, scan_end in txn._scan_ranges:
                            for wk in record.write_keys:
                                if scan_start <= wk < scan_end:
                                    raise ConflictError(
                                        f"Phantom conflict: '{wk}' in "
                                        f"[{scan_start}, {scan_end})"
                                    )

            for key, value in txn._local_storage.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO versions (key, ts, value) "
                    "VALUES (?, ?, ?)",
                    (key, commit_ts, value),
                )

            if self._serializable and txn._write_set:
                key_hashes = set(_key_hash(k) for k in txn._write_set)
                rec = _CommittedTxnRecord(key_hashes, set(txn._write_set))
                self._committed_txns[commit_ts] = rec
                self._conn.execute(
                    "INSERT INTO committed_txns "
                    "(commit_ts, key_hashes, write_keys) VALUES (?, ?, ?)",
                    (
                        commit_ts,
                        json.dumps(sorted(key_hashes)),
                        json.dumps(sorted(txn._write_set)),
                    ),
                )

            self._latest_commit_ts = commit_ts
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (mkey, mvalue) "
                "VALUES ('latest_commit_ts', ?)",
                (str(commit_ts),),
            )
            self._conn.commit()
            return commit_ts

    def gc(self) -> int:
        wm = self._watermark.watermark()
        if wm is None:
            wm = self._latest_commit_ts

        removed = 0

        keys = [
            row[0]
            for row in self._conn.execute(
                "SELECT DISTINCT key FROM versions WHERE ts <= ?", (wm,)
            ).fetchall()
        ]

        for key in keys:
            filter_match = any(
                f.filter(key) for f in self._compaction_filters
            )

            if filter_match:
                count = self._conn.execute(
                    "SELECT count(*) FROM versions "
                    "WHERE key = ? AND ts <= ?",
                    (key, wm),
                ).fetchone()[0]
                self._conn.execute(
                    "DELETE FROM versions WHERE key = ? AND ts <= ?",
                    (key, wm),
                )
                removed += count
                continue

            versions_below = self._conn.execute(
                "SELECT ts, value FROM versions "
                "WHERE key = ? AND ts <= ? ORDER BY ts DESC",
                (key, wm),
            ).fetchall()

            if not versions_below:
                continue

            if len(versions_below) == 1:
                if versions_below[0][1] is None:
                    self._conn.execute(
                        "DELETE FROM versions WHERE key = ? AND ts = ?",
                        (key, versions_below[0][0]),
                    )
                    removed += 1
                continue

            latest = versions_below[0]

            if latest[1] is None:
                self._conn.execute(
                    "DELETE FROM versions WHERE key = ? AND ts <= ?",
                    (key, wm),
                )
                removed += len(versions_below)
            else:
                for v in versions_below[1:]:
                    self._conn.execute(
                        "DELETE FROM versions WHERE key = ? AND ts = ?",
                        (key, v[0]),
                    )
                    removed += 1

        self._conn.execute(
            "DELETE FROM committed_txns WHERE commit_ts <= ?", (wm,)
        )
        to_remove = [ts for ts in self._committed_txns if ts <= wm]
        for ts in to_remove:
            del self._committed_txns[ts]

        self._conn.commit()
        return removed

    def add_compaction_filter(self, f: CompactionFilter) -> None:
        self._compaction_filters.append(f)

    def remove_compaction_filter(self, f: CompactionFilter) -> None:
        self._compaction_filters.remove(f)

    def close(self) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None


class Transaction:
    def __init__(
        self, store: MVCCStore, read_ts: int, serializable: bool
    ):
        self._store = store
        self._read_ts = read_ts
        self._serializable = serializable
        self._local_storage: dict[str, str | None] = {}
        self._read_set: set[int] = set()
        self._write_set: set[str] = set()
        self._scan_ranges: list[tuple[str, str]] = []
        self._committed = False
        self._rolled_back = False

    def get(self, key: str) -> str | None:
        assert not self._committed and not self._rolled_back, (
            "Transaction already finished"
        )
        if self._serializable:
            self._read_set.add(_key_hash(key))
        if key in self._local_storage:
            return self._local_storage[key]
        return self._store._get_version(key, self._read_ts)

    def put(self, key: str, value: str) -> None:
        assert not self._committed and not self._rolled_back, (
            "Transaction already finished"
        )
        self._local_storage[key] = value
        self._write_set.add(key)

    def delete(self, key: str) -> None:
        assert not self._committed and not self._rolled_back, (
            "Transaction already finished"
        )
        self._local_storage[key] = None
        self._write_set.add(key)

    def scan(self, start: str, end: str) -> list[tuple[str, str]]:
        assert not self._committed and not self._rolled_back, (
            "Transaction already finished"
        )
        if self._serializable:
            self._scan_ranges.append((start, end))
        store_results = dict(
            self._store._scan_versions(start, end, self._read_ts)
        )
        for key, value in self._local_storage.items():
            if start <= key < end:
                if value is None:
                    store_results.pop(key, None)
                else:
                    store_results[key] = value
        return sorted(store_results.items())

    def commit(self) -> int:
        if self._committed:
            raise RuntimeError("Transaction already committed")
        if self._rolled_back:
            raise RuntimeError("Transaction already rolled back")
        self._committed = True
        if not self._write_set:
            self._store._watermark.remove_reader(self._read_ts)
            return self._read_ts
        try:
            ts = self._store._commit_txn(self)
            self._store._watermark.remove_reader(self._read_ts)
            return ts
        except ConflictError:
            self._store._watermark.remove_reader(self._read_ts)
            raise

    def rollback(self) -> None:
        if self._committed:
            raise RuntimeError("Transaction already committed")
        if self._rolled_back:
            raise RuntimeError("Transaction already rolled back")
        self._rolled_back = True
        self._store._watermark.remove_reader(self._read_ts)
