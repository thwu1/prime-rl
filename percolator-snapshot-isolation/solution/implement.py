#!/usr/bin/env python3
"""Implements the distributed transaction protocol with SQLite-backed storage.

Writes complete implementations to /app/percolator/storage.py and
/app/percolator/client.py.
"""

import os

STORAGE_CODE = '''\
import sqlite3
import threading
from .errors import RequestDroppedError, ResponseDroppedError


class Column:
    WRITE = "write"
    DATA = "data"
    LOCK = "lock"


class CommitHooks:
    def __init__(self):
        self.drop_req = False
        self.drop_resp = False
        self.fail_primary = False


class KvTable:
    """Multi-version key-value store backed by SQLite.

    Three tables keyed by (key BLOB, ts INTEGER):
      kv_write: ..., start_ts INTEGER
      kv_data:  ..., value BLOB
      kv_lock:  ..., primary_key BLOB
    """

    _SCHEMA = {
        Column.WRITE: ("kv_write", "start_ts"),
        Column.DATA:  ("kv_data",  "value"),
        Column.LOCK:  ("kv_lock",  "primary_key"),
    }

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE kv_write (
                key BLOB NOT NULL, ts INTEGER NOT NULL,
                start_ts INTEGER NOT NULL, PRIMARY KEY (key, ts));
            CREATE TABLE kv_data (
                key BLOB NOT NULL, ts INTEGER NOT NULL,
                value BLOB NOT NULL, PRIMARY KEY (key, ts));
            CREATE TABLE kv_lock (
                key BLOB NOT NULL, ts INTEGER NOT NULL,
                primary_key BLOB NOT NULL, PRIMARY KEY (key, ts));
        """)

    def read(self, key, column, ts_start=None, ts_end=None):
        table, val_col = self._SCHEMA[column]
        wheres = ["key = ?"]
        params = [key]
        if ts_start is not None:
            wheres.append("ts >= ?")
            params.append(ts_start)
        if ts_end is not None:
            wheres.append("ts <= ?")
            params.append(ts_end)
        row = self.conn.execute(
            f"SELECT key, ts, {val_col} FROM {table}"
            f" WHERE {' AND '.join(wheres)} ORDER BY ts DESC LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            return None
        return ((row[0], row[1]), row[2])

    def write_record(self, key, column, ts, value):
        table, val_col = self._SCHEMA[column]
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} (key, ts, {val_col})"
            f" VALUES (?, ?, ?)",
            (key, ts, value),
        )

    def erase(self, key, column, ts):
        table, _ = self._SCHEMA[column]
        self.conn.execute(
            f"DELETE FROM {table} WHERE key = ? AND ts = ?",
            (key, ts),
        )


class MemoryStorage:
    def __init__(self):
        self.kv = KvTable()
        self._mutex = threading.Lock()
        self._hooks = None

    def set_hooks(self, hooks):
        self._hooks = hooks

    def get(self, key, start_ts):
        with self._mutex:
            lock_entry = self.kv.read(key, Column.LOCK, ts_end=start_ts)
            if lock_entry is not None:
                self.back_off_maybe_clean_up_lock(key, start_ts)
                lock_entry = self.kv.read(key, Column.LOCK, ts_end=start_ts)
                if lock_entry is not None:
                    return b""

            write_entry = self.kv.read(key, Column.WRITE, ts_end=start_ts)
            if write_entry is None:
                return b""

            (_, _), data_ts = write_entry
            data_entry = self.kv.read(
                key, Column.DATA, ts_start=data_ts, ts_end=data_ts
            )
            if data_entry is None:
                return b""
            return data_entry[1]

    def prewrite(self, key, value, start_ts, primary_key):
        with self._mutex:
            if self.kv.read(key, Column.WRITE, ts_start=start_ts) is not None:
                return False
            if self.kv.read(key, Column.LOCK) is not None:
                return False
            self.kv.write_record(key, Column.DATA, start_ts, value)
            self.kv.write_record(key, Column.LOCK, start_ts, primary_key)
            return True

    def commit(self, key, start_ts, commit_ts, is_primary=False):
        if self._hooks and self._hooks.drop_req:
            if not (is_primary and not self._hooks.fail_primary):
                raise RequestDroppedError("commit request dropped")

        with self._mutex:
            lock_entry = self.kv.read(
                key, Column.LOCK, ts_start=start_ts, ts_end=start_ts
            )
            if lock_entry is None:
                return False
            self.kv.write_record(key, Column.WRITE, commit_ts, start_ts)
            self.kv.erase(key, Column.LOCK, start_ts)

        if self._hooks and self._hooks.drop_resp:
            raise ResponseDroppedError("commit response dropped")

        return True

    def back_off_maybe_clean_up_lock(self, key, caller_start_ts):
        lock_entry = self.kv.read(key, Column.LOCK, ts_end=caller_start_ts)
        if lock_entry is None:
            return

        (_, lock_ts), primary_key = lock_entry
        if primary_key == key:
            return

        primary_lock = self.kv.read(
            primary_key, Column.LOCK, ts_start=lock_ts, ts_end=lock_ts
        )

        if primary_lock is None:
            row = self.kv.conn.execute(
                "SELECT ts FROM kv_write WHERE key = ? AND start_ts = ?",
                (primary_key, lock_ts),
            ).fetchone()

            if row is not None:
                committed_ts = row[0]
                self.kv.write_record(key, Column.WRITE, committed_ts, lock_ts)
                self.kv.erase(key, Column.LOCK, lock_ts)
            else:
                self.kv.erase(key, Column.LOCK, lock_ts)
                self.kv.erase(key, Column.DATA, lock_ts)
'''

CLIENT_CODE = '''\
from .errors import RequestDroppedError, ResponseDroppedError


class Client:
    """Transaction client with snapshot isolation."""

    def __init__(self, tso, storage):
        self._tso = tso
        self._storage = storage
        self._start_ts = 0
        self._write_buffer = {}

    def begin(self):
        self._start_ts = self._tso.get_timestamp()
        self._write_buffer = {}

    def get(self, key):
        return self._storage.get(key, self._start_ts)

    def set(self, key, value):
        self._write_buffer[key] = value

    def commit(self):
        if not self._write_buffer:
            return True

        keys = list(self._write_buffer.keys())
        primary = keys[0]

        for key in keys:
            if not self._storage.prewrite(
                key, self._write_buffer[key], self._start_ts, primary
            ):
                return False

        commit_ts = self._tso.get_timestamp()

        try:
            success = self._storage.commit(
                primary, self._start_ts, commit_ts, is_primary=True
            )
            if not success:
                return False
        except RequestDroppedError:
            return False
        except ResponseDroppedError:
            raise

        for key in keys[1:]:
            try:
                self._storage.commit(
                    key, self._start_ts, commit_ts, is_primary=False
                )
            except (RequestDroppedError, ResponseDroppedError):
                pass

        return True
'''


def main():
    target_dir = '/app/percolator'
    os.makedirs(target_dir, exist_ok=True)
    for name, code in [('storage.py', STORAGE_CODE), ('client.py', CLIENT_CODE)]:
        with open(os.path.join(target_dir, name), 'w') as f:
            f.write(code)


if __name__ == '__main__':
    main()
