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
        """Return ((key, ts), value) for the latest matching entry, or None."""
        raise NotImplementedError

    def write_record(self, key, column, ts, value):
        """Insert or replace a record at (key, ts) in column."""
        raise NotImplementedError

    def erase(self, key, column, ts):
        """Delete the record at (key, ts) in column if it exists."""
        raise NotImplementedError


class MemoryStorage:
    def __init__(self):
        self.kv = KvTable()
        self._mutex = threading.Lock()
        self._hooks = None

    def set_hooks(self, hooks):
        self._hooks = hooks

    def get(self, key, start_ts):
        """Read key as of start_ts. Returns value bytes, or b"" if unavailable."""
        raise NotImplementedError

    def prewrite(self, key, value, start_ts, primary_key):
        """Attempt to prewrite. Returns True on success, False on conflict."""
        raise NotImplementedError

    def commit(self, key, start_ts, commit_ts, is_primary=False):
        """Finalize a prewritten key. Returns True/False.
        May raise RequestDroppedError or ResponseDroppedError per hooks."""
        raise NotImplementedError

    def back_off_maybe_clean_up_lock(self, key, caller_start_ts):
        """Handle a lock encountered during get. Called with self._mutex held."""
        raise NotImplementedError
