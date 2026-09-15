"""SQLite-backed materialization state store.

Provides the same interface as MaterializationState but backed by a SQLite
database, enabling persistent materialization tracking across pipeline runs.
"""

import sqlite3
from reconciler import MaterializationRecord


class SqliteMaterializationStore:
    """Reads and writes materialization records from a SQLite database."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)

    def get_record(self, asset_key, partition_key):
        """Get the latest materialization record for an asset partition.

        When multiple records exist (e.g., from re-materializations),
        returns the one with the highest timestamp.
        Normalizes millisecond timestamps to seconds.
        """
        cursor = self.conn.execute(
            "SELECT run_id, timestamp FROM materializations "
            "WHERE asset_key = ? AND partition_key = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (asset_key, partition_key)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        ts = row[1]
        if ts > 1e12:
            ts = ts / 1000.0
        return MaterializationRecord(row[0], ts)

    def is_materialized(self, asset_key, partition_key):
        """Check if a partition has been materialized."""
        cursor = self.conn.execute(
            "SELECT 1 FROM materializations "
            "WHERE asset_key = ? AND partition_key = ? LIMIT 1",
            (asset_key, partition_key)
        )
        return cursor.fetchone() is not None

    def get_materialized_partitions(self, asset_key):
        """Get all materialized partition keys for an asset."""
        cursor = self.conn.execute(
            "SELECT DISTINCT partition_key FROM materializations WHERE asset_key = ?",
            (asset_key,)
        )
        return {row[0] for row in cursor}

    def mark_materialized(self, asset_key, partition_key, run_id, timestamp):
        """Record a partition materialization."""
        self.conn.execute(
            "INSERT INTO materializations (asset_key, partition_key, run_id, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (asset_key, partition_key, run_id, timestamp)
        )
        self.conn.commit()

    def validate(self):
        """Validate database schema integrity."""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='materializations'"
        )
        if cursor.fetchone() is None:
            return {"status": "ERROR", "message": "materializations table missing"}
        cursor = self.conn.execute("PRAGMA table_info(materializations)")
        columns = {row[1] for row in cursor}
        required = {"asset_key", "partition_key", "run_id", "timestamp"}
        if not required.issubset(columns):
            return {"status": "ERROR", "message": f"Missing columns: {required - columns}"}
        return {"status": "OK", "message": "Schema valid"}

    def close(self):
        """Close the database connection."""
        self.conn.close()
