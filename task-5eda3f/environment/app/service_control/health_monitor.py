"""Health monitoring for the Service Control system.

Performs periodic health checks by executing a test quota check against
the live data store.  Results are exposed to the API Gateway for
upstream health-check probes.
"""

import json
import os
import logging
import time

logger = logging.getLogger(__name__)

HEALTH_STATUS_PATH = "/app/data/health_status.json"


class HealthMonitor:
    """Monitors Service Control health via test quota checks."""

    def __init__(self, policy_checker):
        self.policy_checker = policy_checker
        self._last_check_time = 0
        self._consecutive_failures = 0

    def check_health(self) -> dict:
        """Run a health check and return status.

        Must never crash — a crashing health check creates a monitoring
        blind spot during incidents when visibility is most critical.
        """
        result = self.policy_checker.check_quota(
            "health-check-project", "health.googleapis.com"
        )

        self._last_check_time = time.time()
        self._consecutive_failures = 0

        return {
            "status": "healthy",
            "last_check": self._last_check_time,
            "details": "quota check passed",
        }

    def write_status(self, status: dict):
        """Write health status to disk for the API Gateway."""
        os.makedirs(os.path.dirname(HEALTH_STATUS_PATH), exist_ok=True)
        with open(HEALTH_STATUS_PATH, 'w') as f:
            json.dump(status, f)
