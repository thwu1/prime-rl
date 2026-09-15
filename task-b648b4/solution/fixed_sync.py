"""
Policy Replicator with data validation - FIXED VERSION.
Validates all required fields before inserting, in both single and batch paths.
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

    def _validate_policy(self, policy_data):
        """Validate that all required fields are present and non-blank."""
        for field in self.REQUIRED_FIELDS:
            value = policy_data.get(field)
            if value is None:
                return False, f"Required field '{field}' is None"
            if isinstance(value, str) and not value.strip():
                return False, f"Required field '{field}' is blank"
        return True, None

    def replicate_policy(self, policy_data):
        """Replicate a single policy update, rejecting invalid data."""
        valid, error = self._validate_policy(policy_data)
        if not valid:
            logger.error("Rejecting policy: %s", error)
            return {"accepted": False, "error": error}

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO active_policies
                   (policy_id, service_name, enforcement_mode,
                    quota_limit, quota_window, description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    policy_data["policy_id"],
                    policy_data["service_name"],
                    policy_data["enforcement_mode"],
                    policy_data["quota_limit"],
                    policy_data["quota_window"],
                    policy_data.get("description", ""),
                    policy_data.get("updated_at", datetime.utcnow().isoformat())
                )
            )
            conn.commit()
            logger.info("Replicated policy %s", policy_data["policy_id"])
            return {"accepted": True}
        except Exception as e:
            logger.error("Failed to replicate policy: %s", e)
            return {"accepted": False, "error": str(e)}
        finally:
            conn.close()

    def replicate_batch(self, policies):
        """Replicate a batch of policies with per-policy validation."""
        results = []
        for policy in policies:
            result = self.replicate_policy(policy)
            results.append(result)
        return results
