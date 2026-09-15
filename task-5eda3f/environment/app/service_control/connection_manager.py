"""Database connection management with retry logic.

Manages a pool of SQLite connections and retries failed connection
attempts.
"""

import time
import sqlite3
import logging
import threading
from typing import Optional, List

logger = logging.getLogger(__name__)


class ConnectionManager:

    def __init__(self, db_path: str, max_connections: int = 10,
                 max_retries: int = 10):
        self.db_path = db_path
        self.max_connections = max_connections
        self.max_retries = max_retries
        self._pool: List[sqlite3.Connection] = []
        self._active = 0
        self._lock = threading.Lock()
        self._retry_history: List[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_connection(self) -> sqlite3.Connection:
        """Obtain a connection, reusing a pooled one if available."""
        with self._lock:
            if self._pool:
                conn = self._pool.pop()
                self._active += 1
                return conn
        return self._retry_connect()

    def release_connection(self, conn: sqlite3.Connection):
        """Return a connection to the pool."""
        with self._lock:
            self._active -= 1
            if len(self._pool) < self.max_connections:
                self._pool.append(conn)
            else:
                conn.close()

    def close_all(self):
        """Drain the pool and close every connection."""
        with self._lock:
            for conn in self._pool:
                conn.close()
            self._pool.clear()

    # ------------------------------------------------------------------
    # Retry internals
    # ------------------------------------------------------------------

    def _retry_connect(self) -> sqlite3.Connection:
        """Attempt to connect with retries on failure."""
        for attempt in range(self.max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=5)
                conn.row_factory = sqlite3.Row
                with self._lock:
                    self._active += 1
                    self._retry_history.append(time.time())
                return conn
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                logger.warning(
                    "Connection attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                self._retry_history.append(time.time())
                time.sleep(0.5)

        raise ConnectionError(
            f"Failed to connect to {self.db_path} after "
            f"{self.max_retries} attempts"
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_retry_delays(self) -> List[float]:
        """Return inter-attempt delays (useful for post-incident analysis)."""
        if len(self._retry_history) < 2:
            return []
        return [
            self._retry_history[i + 1] - self._retry_history[i]
            for i in range(len(self._retry_history) - 1)
        ]
