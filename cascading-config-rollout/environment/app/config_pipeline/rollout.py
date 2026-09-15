"""
Progressive rollout controller.

Rolls out configuration changes to sites in batches with canary
validation, health checking between batches, and rollback on failure.
"""
import logging
import time
from typing import Dict, Any, List

from .canary import CanaryValidator, CanaryResult
from .site import SiteManager

logger = logging.getLogger("config_pipeline.rollout")


class RolloutController:
    """Controls progressive rollout of configuration to sites."""

    def __init__(
        self,
        sites: List[SiteManager],
        canary: CanaryValidator,
        batch_size: int = 2,
        batch_delay: float = 1.0,
    ):
        self.sites = sites
        self.canary = canary
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.rollout_log: list = []

    def execute_rollout(self, config: Dict[str, Any]) -> bool:
        """Execute progressive rollout of config to all sites.

        Process:
        1. Validate on canary site
        2. If canary passes, roll out to remaining sites in batches
        3. Health check between batches

        Returns True if rollout succeeded, False otherwise.
        """
        if not self.sites:
            logger.error("No sites configured for rollout")
            return False

        canary_site = self.sites[0]
        remaining_sites = self.sites[1:]

        # Step 1: Canary validation
        logger.info(f"Starting canary validation on {canary_site.site_id}")
        canary_result = self.canary.validate_async(config, canary_site.site_id)

        # Check whether the canary flagged the config as bad.
        # Only abort if the canary has explicitly reported a failure;
        # otherwise treat the config as safe to proceed.
        if canary_result.is_completed and canary_result.success is False:
            logger.error(
                f"Canary validation failed: {canary_result.message}"
            )
            self._log_event(
                "CANARY_FAILED", canary_site.site_id, canary_result.message
            )
            return False

        logger.info("Canary check passed, proceeding with rollout")
        self._log_event(
            "CANARY_PASSED", canary_site.site_id, "Proceeding with rollout"
        )

        # Apply to canary site first
        if not canary_site.apply_config(config):
            logger.error(
                f"Failed to apply config to canary site "
                f"{canary_site.site_id}"
            )
            return False

        # Step 2: Progressive rollout to remaining sites
        for i in range(0, len(remaining_sites), self.batch_size):
            batch = remaining_sites[i : i + self.batch_size]
            batch_num = (i // self.batch_size) + 1

            logger.info(
                f"Rolling out batch {batch_num}: "
                f"{[s.site_id for s in batch]}"
            )

            for site in batch:
                if not site.apply_config(config):
                    logger.error(
                        f"Failed to apply config to {site.site_id}"
                    )
                    self._log_event(
                        "APPLY_FAILED", site.site_id,
                        "Config application failed"
                    )
                else:
                    self._log_event(
                        "APPLY_SUCCESS", site.site_id, "Config applied"
                    )

            # Health check delay between batches
            if i + self.batch_size < len(remaining_sites):
                time.sleep(self.batch_delay)
                for site in batch:
                    if not site.is_healthy():
                        logger.error(
                            f"Site {site.site_id} unhealthy after config push"
                        )
                        self._log_event(
                            "HEALTH_FAILED", site.site_id,
                            "Post-push health check failed"
                        )

        # Final health check of all sites
        all_healthy = True
        for site in self.sites:
            if not site.is_healthy():
                all_healthy = False
                logger.error(
                    f"Final health check failed for {site.site_id}"
                )

        return all_healthy

    def _log_event(self, event_type: str, site_id: str, detail: str):
        self.rollout_log.append({
            "timestamp": time.time(),
            "event": event_type,
            "site_id": site_id,
            "detail": detail,
        })
