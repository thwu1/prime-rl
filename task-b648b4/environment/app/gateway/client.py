"""
Service Control Client for API Gateway workers.
Handles communication with the Service Control server for policy checks.
"""

import requests
import time
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
        """
        Check if an API request is allowed.
        Falls back to fail-open on connection errors.
        """
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
        """
        Attempt to reconnect to service control.
        Retries until successful or max attempts reached.
        """
        # Create fresh session for reconnection attempt
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

            time.sleep(0.1)

        raise ConnectionError(
            f"Failed to reconnect to service_control after "
            f"{self._max_reconnect_attempts} attempts"
        )

    def health_check(self):
        """Check if service control is healthy."""
        try:
            resp = self._session.get(
                f"{self.base_url}/health",
                timeout=2
            )
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False
