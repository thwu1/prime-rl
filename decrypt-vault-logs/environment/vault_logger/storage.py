"""
Persistent storage layer (SQLite) for encrypted audit entries.
"""

import sqlite3
from .config import DB_PATH


class AuditStore:
    """Thin wrapper around the ``log_entries`` table."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS log_entries (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id      INTEGER NOT NULL,
        entry_seq       INTEGER NOT NULL,
        entry_type      TEXT    NOT NULL,
        engine_version  INTEGER NOT NULL,
        ciphertext      BLOB   NOT NULL,
        created_at      INTEGER NOT NULL
    );
    """
    IDX_SESSION = """
    CREATE INDEX IF NOT EXISTS idx_session_seq
        ON log_entries(session_id, entry_seq);
    """
    IDX_ENGINE = """
    CREATE INDEX IF NOT EXISTS idx_engine
        ON log_entries(engine_version);
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._conn = None

    def connect(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(self.SCHEMA)
        self._conn.execute(self.IDX_SESSION)
        self._conn.execute(self.IDX_ENGINE)
        self._conn.commit()

    def store_entry(self, session_id: int, entry_seq: int,
                    entry_type: str, engine_version: int,
                    ciphertext: bytes, created_at: int):
        self._conn.execute(
            'INSERT INTO log_entries '
            '(session_id, entry_seq, entry_type, engine_version, '
            'ciphertext, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (session_id, entry_seq, entry_type, engine_version,
             ciphertext, created_at),
        )
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
