"""
Policy Replicator.
Handles replication of policy updates to the active policies table.
Policies are replicated from a source system to ensure global consistency
across all regional Service Control deployments.
"""

import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger("replicator.sync")


class PolicyReplicator:
    """Replicates policy data to the active_policies table."""

    REQUIRED_FIELDS = [
        "policy_id", "service_name", "enforcement_mode",
        "quota_limit", "quota_window"
    ]

    def __init__(self, db_path):
        self.db_path = db_path

    def replicate_policy(self, policy_data):
        """
        Replicate a single policy update to the active policies table.

        Args:
            policy_data: dict with policy fields

        Returns:
            dict with 'accepted' (bool) and optional 'error' (str)
        """
        # Direct insertion for low-latency replication
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO active_policies
                   (policy_id, service_name, enforcement_mode,
                    quota_limit, quota_window, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    policy_data.get("policy_id"),
                    policy_data.get("service_name"),
                    policy_data.get("enforcement_mode"),
                    policy_data.get("quota_limit"),
                    policy_data.get("quota_window"),
                    policy_data.get("description", ""),
                    policy_data.get("updated_at", datetime.utcnow().isoformat())
                )
            )
            conn.commit()
            logger.info(f"Replicated policy {policy_data.get('policy_id')}")
            return {"accepted": True}
        except Exception as e:
            logger.error(f"Failed to replicate policy: {e}")
            return {"accepted": False, "error": str(e)}
        finally:
            conn.close()

    def replicate_batch(self, policies):
        """
        Replicate a batch of policy updates using optimized bulk insertion.
        Uses executemany for better throughput on large synchronization batches.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            rows = [
                (
                    p.get("policy_id"),
                    p.get("service_name"),
                    p.get("enforcement_mode"),
                    p.get("quota_limit"),
                    p.get("quota_window"),
                    p.get("description", ""),
                    p.get("updated_at", datetime.utcnow().isoformat())
                )
                for p in policies
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO active_policies
                   (policy_id, service_name, enforcement_mode,
                    quota_limit, quota_window, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                rows
            )
            conn.commit()
            logger.info(f"Batch replicated {len(policies)} policies")
            return [{"accepted": True} for _ in policies]
        except Exception as e:
            logger.error(f"Batch replication failed: {e}")
            return [{"accepted": False, "error": str(e)} for _ in policies]
        finally:
            conn.close()
