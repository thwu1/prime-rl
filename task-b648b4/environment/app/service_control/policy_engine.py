"""
Policy Engine for Service Control.
Evaluates API requests against quota and enforcement policies.

Recent changes:
  - 2025-05-29: Added enhanced quota checking for improved rate limiting
  - 2025-06-01: Updated policy cache refresh mechanism
"""

import sqlite3
import logging
import time
from datetime import datetime

logger = logging.getLogger("service_control.policy_engine")


class PolicyEngine:
    """Evaluates API requests against active policies loaded from the database."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._policies_cache = {}
        self._last_refresh = 0
        self._refresh_interval = 30  # seconds
        self.refresh_policies()

    def refresh_policies(self):
        """Load all active policies from the database into memory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT * FROM active_policies")
            self._policies_cache = {}
            for row in cursor:
                policy = dict(row)
                self._policies_cache[policy["policy_id"]] = policy
            self._last_refresh = time.time()
            logger.info(f"Loaded {len(self._policies_cache)} policies")
        finally:
            conn.close()

    def _maybe_refresh(self):
        """Refresh policies if the cache is stale."""
        if time.time() - self._last_refresh > self._refresh_interval:
            self.refresh_policies()

    def evaluate_request(self, service_name, api_method):
        """
        Check if an API request is allowed by quota and enforcement policies.

        Returns dict with 'allowed' (bool) and 'reason' (str).
        """
        self._maybe_refresh()

        matching = [p for p in self._policies_cache.values()
                    if p["service_name"] == service_name]

        if not matching:
            return {"allowed": True, "reason": "no_matching_policy"}

        for policy in matching:
            result = self._check_policy(policy, api_method)
            if not result["allowed"]:
                return result

        return {"allowed": True, "reason": "all_checks_passed"}

    def _check_policy(self, policy, api_method):
        """Evaluate a single policy against the request."""
        # Determine enforcement mode
        mode = policy["enforcement_mode"].upper()

        if mode == "DISABLED":
            return {"allowed": True, "reason": "enforcement_disabled"}

        # Enhanced quota checking (added 2025-05-29)
        quota_result = self._enhanced_quota_check(policy, api_method)

        if mode == "ENFORCED":
            return quota_result
        elif mode == "SHADOW":
            # Log but don't enforce
            logger.debug(f"Shadow mode result for {api_method}: {quota_result}")
            return {"allowed": True, "reason": "shadow_mode"}

        return {"allowed": True, "reason": "unknown_mode_passthrough"}

    def _enhanced_quota_check(self, policy, api_method):
        """
        Enhanced quota checking with per-method granularity.
        Added 2025-05-29 for improved rate limiting accuracy.
        """
        limit = int(policy["quota_limit"])
        window = policy["quota_window"].strip()

        # Parse window duration
        window_seconds = self._parse_window(window)

        # In a real system, this would check actual usage counters.
        # For this simulation, we check if the limit is reasonable.
        if limit <= 0:
            return {"allowed": False, "reason": "zero_quota_limit",
                    "policy_id": policy["policy_id"]}

        return {"allowed": True, "reason": "within_quota",
                "quota_remaining": limit, "window": window}

    def _parse_window(self, window_str):
        """Parse a window duration string like '1m', '1h', '1d' into seconds."""
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        unit = window_str[-1].lower()
        value = int(window_str[:-1])
        return value * multipliers.get(unit, 60)
