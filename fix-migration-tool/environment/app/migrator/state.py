"""Migration state tracking in the target database."""
import sqlite3
import datetime


class MigrationState:
    """Tracks which migrations have been applied to a database."""

    TRACKING_TABLE = '_schema_migrations'

    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_tracking_table()

    def _ensure_tracking_table(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(f'''
                CREATE TABLE IF NOT EXISTS {self.TRACKING_TABLE} (
                    migration_id TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
            ''')
            conn.commit()
        finally:
            conn.close()

    def is_applied(self, migration_id):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                f'SELECT 1 FROM {self.TRACKING_TABLE} '
                f"WHERE migration_id = ? AND status = 'applied'",
                (migration_id,)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def mark_applied(self, migration_id, checksum):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                f'INSERT INTO {self.TRACKING_TABLE} '
                f'(migration_id, checksum, applied_at) '
                f'VALUES (?, ?, ?)',
                (migration_id, checksum, datetime.datetime.now().isoformat())
            )
            conn.commit()
        finally:
            conn.close()

    def get_applied_checksum(self, migration_id):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                f'SELECT checksum FROM {self.TRACKING_TABLE} '
                f"WHERE migration_id = ? AND status = 'applied'",
                (migration_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def get_all_applied(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                f'SELECT migration_id, checksum, applied_at FROM {self.TRACKING_TABLE} '
                f"WHERE status = 'applied'"
            )
            return cursor.fetchall()
        finally:
            conn.close()
