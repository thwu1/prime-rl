"""
Canary validation for configuration changes.

Before a config is rolled out to all sites, it is validated on a
canary site to catch issues early. Validation runs asynchronously
and results are communicated via a CanaryResult object.
"""
import logging
import time
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger("config_pipeline.canary")


class CanaryResult:
    """Holds the result of a canary validation."""

    def __init__(self):
        self._success: Optional[bool] = None
        self._message: str = ""
        self._completed = threading.Event()

    def set_result(self, success: bool, message: str = ""):
        self._success = success
        self._message = message
        self._completed.set()

    @property
    def is_completed(self) -> bool:
        return self._completed.is_set()

    @property
    def success(self) -> Optional[bool]:
        return self._success

    @property
    def message(self) -> str:
        return self._message

    def wait(self, timeout: float = None) -> bool:
        """Wait for result. Returns True if completed within timeout."""
        return self._completed.wait(timeout=timeout)


class CanaryValidator:
    """Validates configuration changes on a canary site before full rollout."""

    REQUIRED_KEYS = {"ip_blocks", "routing_rules", "service_endpoints"}
    MIN_IP_BLOCKS = 1

    def __init__(self, validation_delay: float = 0.5):
        self.validation_delay = validation_delay

    def validate_async(
        self, config: Dict[str, Any], site_id: str
    ) -> CanaryResult:
        """Start async validation of config on canary site.

        Returns a CanaryResult that will be populated when validation
        completes. Callers should wait on the result before proceeding.
        """
        result = CanaryResult()

        def _do_validate():
            time.sleep(self.validation_delay)  # simulate validation work

            # Check required keys
            missing_keys = self.REQUIRED_KEYS - set(config.keys())
            if missing_keys:
                msg = (
                    f"Canary FAILED on {site_id}: "
                    f"missing required keys: {missing_keys}"
                )
                logger.error(msg)
                result.set_result(False, msg)
                return

            # Check IP blocks are nonempty
            ip_blocks = config.get("ip_blocks", [])
            if len(ip_blocks) < self.MIN_IP_BLOCKS:
                msg = (
                    f"Canary FAILED on {site_id}: "
                    f"insufficient IP blocks ({len(ip_blocks)} "
                    f"< {self.MIN_IP_BLOCKS})"
                )
                logger.error(msg)
                result.set_result(False, msg)
                return

            # Check routing rules
            routing = config.get("routing_rules", {})
            if not routing:
                msg = (
                    f"Canary FAILED on {site_id}: empty routing rules"
                )
                logger.error(msg)
                result.set_result(False, msg)
                return

            logger.info(
                f"Canary PASSED on {site_id}: config validated successfully"
            )
            result.set_result(True, "Validation passed")

        thread = threading.Thread(target=_do_validate, daemon=True)
        thread.start()

        return result
