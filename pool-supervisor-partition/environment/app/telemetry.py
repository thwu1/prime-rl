"""
Telemetry recorder -- writes connection lifecycle events to SQLite.

Provides a TelemetryRecorder class that persists connection pool events
for diagnostic analysis. The schema supports recording request initiation,
connection establishment, failures, and other lifecycle events.

Usage:
    recorder = TelemetryRecorder("/app/telemetry.db")
    recorder.record_event("request", destination="sfu-1.example.com")
    recorder.record_event("connect", connection_id="abc123",
                          destination="sfu-1.example.com", success=True)
    recorder.close()

"""

import sqlite3
import time
import threading


class TelemetryRecorder:
    """Records connection pool events to a SQLite database.

    Schema::

        connection_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            connection_id TEXT,
            destination TEXT,
            partition_id TEXT,
            duration_ms REAL,
            success INTEGER
        )
    """

    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS connection_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                connection_id TEXT,
                destination TEXT,
                partition_id TEXT,
                duration_ms REAL,
                success INTEGER
            )
        """)
        self._conn.commit()

    def record_event(self, event_type, connection_id=None, destination=None,
                     partition_id=None, duration_ms=None, success=None):
        """Record a connection lifecycle event.

        Args:
            event_type:    Event category (e.g. "request", "connect", "fail").
            connection_id: Unique connection identifier.
            destination:   Target host/endpoint.
            partition_id:  Supervisor partition that handled the event.
            duration_ms:   Duration of the operation in milliseconds.
            success:       Whether the operation succeeded (bool or None).
        """
        with self._lock:
            self._conn.execute(
                """INSERT INTO connection_events
                   (timestamp, event_type, connection_id, destination,
                    partition_id, duration_ms, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), event_type, connection_id, destination,
                 partition_id, duration_ms,
                 1 if success else (0 if success is not None else None))
            )
            self._conn.commit()

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
