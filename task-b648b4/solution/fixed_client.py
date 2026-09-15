"""
Service Control Client for API Gateway workers - FIXED VERSION.
Uses exponential backoff with full jitter and proper session cleanup.
"""


import requests
import time
import random
import logging

logger = logging.getLogger("gateway.client")


class ServiceControlClient:
    """Client for checking API requests against Service Control policies."""

    def __init__(self, base_url, timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._connected = False
        self._max_reconnect_attempts = 50

    def check_request(self, service_name, api_method):
        try:
            resp = self._session.post(
                f"{self.base_url}/check",
                json={"service": service_name, "method": api_method},
                timeout=self.timeout
            )
            self._connected = True
            return resp.json()
        except (requests.ConnectionError, requests.Timeout):
            self._connected = False
            logger.warning("Connection to service_control lost, attempting reconnect")
            self._reconnect()
            return {"allowed": True, "reason": "fail_open_connection_error"}

    def _reconnect(self):
        """Reconnect with exponential backoff, full jitter, and session cleanup."""
        base_delay = 0.1
        max_delay = 30.0

        # Close old session to prevent resource leak
        old_session = self._session
        try:
            old_session.close()
        except Exception:
            pass
        self._session = requests.Session()

        for attempt in range(self._max_reconnect_attempts):
            try:
                resp = self._session.get(
                    f"{self.base_url}/health",
                    timeout=2
                )
                if resp.status_code == 200:
                    self._connected = True
                    logger.info("Reconnected to service_control")
                    return
            except (requests.ConnectionError, requests.Timeout):
                pass

            # Exponential backoff with full jitter to prevent thundering herd
            exp_delay = min(base_delay * (2 ** attempt), max_delay)
            jittered_delay = random.uniform(0, exp_delay)
            time.sleep(jittered_delay)

        raise ConnectionError(
            f"Failed to reconnect after {self._max_reconnect_attempts} attempts"
        )

    def health_check(self):
        try:
            resp = self._session.get(f"{self.base_url}/health", timeout=2)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False
