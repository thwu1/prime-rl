"""Regional data store for policy and quota data.

Each region maintains its own data store backed by SQLite.
Policy data is replicated across regions by the DataReplicator.
"""

import sqlite3
import logging
from typing import List, Optional

from .models import Policy

logger = logging.getLogger(__name__)


class RegionalDataStore:
    """Provides access to regional policy data stored in SQLite."""

    def __init__(self, db_path: str, region_id: str):
        self.db_path = db_path
        self.region_id = region_id
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        """Establish connection to the regional data store."""
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        logger.info(f"Connected to regional store for {self.region_id}")

    def close(self):
        """Close the data store connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_policies(self, project_id: str) -> List[Policy]:
        """Retrieve all enabled policies for a given project."""
        cursor = self._conn.execute(
            "SELECT * FROM policies WHERE project_id = ? AND enabled = 1",
            (project_id,)
        )
        rows = cursor.fetchall()
        return [
            Policy(
                policy_id=row['policy_id'],
                project_id=row['project_id'],
                api_name=row['api_name'],
                max_requests=row['max_requests'],
                current_usage=row['current_usage'],
                rate_limit=row['rate_limit'],
                rate_limit_window=row['rate_limit_window'],
                enabled=bool(row['enabled'])
            )
            for row in rows
        ]

    def insert_policy(self, policy_data: dict):
        """Insert or replace a policy in the regional store."""
        self._conn.execute(
            """INSERT OR REPLACE INTO policies
               (policy_id, project_id, api_name, max_requests, current_usage,
                rate_limit, rate_limit_window, enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                policy_data['policy_id'],
                policy_data['project_id'],
                policy_data['api_name'],
                policy_data.get('max_requests'),
                policy_data.get('current_usage', 0),
                policy_data.get('rate_limit'),
                policy_data.get('rate_limit_window'),
                policy_data.get('enabled', 1),
            )
        )
        self._conn.commit()

    def delete_policy(self, policy_id: str):
        """Remove a policy from the regional store."""
        self._conn.execute(
            "DELETE FROM policies WHERE policy_id = ?",
            (policy_id,)
        )
        self._conn.commit()

    def get_all_policies(self) -> List[Policy]:
        """Retrieve every policy (enabled or not) for audit purposes."""
        cursor = self._conn.execute("SELECT * FROM policies")
        rows = cursor.fetchall()
        return [
            Policy(
                policy_id=row['policy_id'],
                project_id=row['project_id'],
                api_name=row['api_name'],
                max_requests=row['max_requests'],
                current_usage=row['current_usage'],
                rate_limit=row['rate_limit'],
                rate_limit_window=row['rate_limit_window'],
                enabled=bool(row['enabled'])
            )
            for row in rows
        ]
