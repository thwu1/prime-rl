"""
Health checker for monitoring site fleet status.
"""
import logging
from typing import List, Dict

from .site import SiteManager

logger = logging.getLogger("config_pipeline.health")


class HealthChecker:
    """Monitors health of all sites in the fleet."""

    def __init__(self, sites: List[SiteManager], check_interval: float = 1.0):
        self.sites = sites
        self.check_interval = check_interval

    def check_all(self) -> Dict[str, bool]:
        """Check health of all sites. Returns {site_id: healthy}."""
        results = {}
        for site in self.sites:
            results[site.site_id] = site.is_healthy()

        unhealthy = [sid for sid, h in results.items() if not h]
        if unhealthy:
            logger.warning(f"Unhealthy sites: {unhealthy}")
        else:
            logger.info("All sites healthy")

        return results
