#!/usr/bin/env python3
"""Database Connector - Connection pooling for regional policy databases.

Provides a simple connection pool for SQLite databases.  In production this
would target Cloud Spanner; here we use SQLite to simulate the same
read-heavy workload pattern.

Known issues (2025-06-12):
  - When multiple service-control instances restart simultaneously after a
    crash, they all hit the database at once with zero delay between retries,
    creating a thundering-herd effect that can overload the datastore.
  - Failed/stale connections are not properly cleaned up, leading to pool
    exhaustion under sustained failure conditions.
"""
import sqlite3
import logging

logger = logging.getLogger('service_control.db_connector')


class DatabaseConnector:
    """Simple SQLite connection pool with retry logic."""

    def __init__(self, db_path, pool_size=5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool = []
        self._max_retries = 10

    def get_connection(self):
        """Obtain a database connection, either from the pool or by creating
        a new one.

        Returns:
            sqlite3.Connection

        Raises:
            ConnectionError: if all retry attempts fail.
        """
        # Try to reuse a pooled connection
        if self._pool:
            conn = self._pool.pop()
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                # Connection is stale - fall through to create a new one
                # BUG: stale connection is never closed, it just leaks
                pass

        # Create a new connection, retrying on failure
        for attempt in range(self._max_retries):
            try:
                conn = sqlite3.connect(self.db_path, timeout=5)
                conn.row_factory = sqlite3.Row
                return conn
            except sqlite3.Error as e:
                logger.warning(
                    f"Connection attempt {attempt + 1}/{self._max_retries} "
                    f"failed: {e}"
                )
                # BUG: no delay between retries.  When many instances restart
                # at the same time this creates a thundering-herd effect.
                continue

        raise ConnectionError(
            f"Failed to connect to {self.db_path} after "
            f"{self._max_retries} attempts"
        )

    def return_connection(self, conn):
        """Return a connection to the pool for reuse."""
        if len(self._pool) < self.pool_size:
            self._pool.append(conn)
        else:
            conn.close()
