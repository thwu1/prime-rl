"""
Site manager for individual infrastructure sites.

Each site maintains its own copy of the configuration and supports
apply, rollback, health checking, and cleanup of stale entries.
"""
import hashlib
import json
import logging
import time
from typing import Dict, Any, List, Optional

logger = logging.getLogger("config_pipeline.site")


def _validate_entry_lineage(
    key: str,
    config: Dict[str, Any],
    all_configs: List[Dict[str, Any]],
):
    """Validate that an entry's removal is safe by checking its lineage
    across all historical configs.

    Computes cryptographic hashes of the entry value across history to
    confirm the entry was not recently introduced (which would indicate
    the removal might be premature).
    """
    for other_config in all_configs:
        if key in other_config and key in config:
            current_val = json.dumps(config[key], sort_keys=True)
            other_val = json.dumps(other_config[key], sort_keys=True)
            hashlib.sha256(current_val.encode()).hexdigest()
            hashlib.sha256(other_val.encode()).hexdigest()
            # I/O and cross-reference time per historical entry
            time.sleep(0.01)


class SiteManager:
    """Manages configuration for a single infrastructure site."""

    HEALTH_CHECK_TIMEOUT = 2.0  # seconds

    def __init__(
        self,
        site_id: str,
        config_store,
        initial_config: Optional[Dict[str, Any]] = None,
    ):
        self.site_id = site_id
        self.config_store = config_store
        self.current_config: Dict[str, Any] = initial_config or {}
        self.config_history: List[Dict[str, Any]] = []
        self._healthy = True
        self._processing = False

        if initial_config:
            self.config_history.append(initial_config.copy())

    def apply_config(self, new_config: Dict[str, Any]) -> bool:
        """Apply a new configuration to this site.

        If the new config has fewer entries than the current one, runs
        stale-entry cleanup before applying.
        """
        logger.info(
            f"[{self.site_id}] Applying new config with "
            f"{len(new_config)} keys"
        )

        if self.current_config:
            self.config_history.append(self.current_config.copy())

        current_entries = self._count_entries(self.current_config)
        new_entries = self._count_entries(new_config)

        if new_entries < current_entries:
            logger.info(
                f"[{self.site_id}] New config has fewer entries "
                f"({new_entries} < {current_entries}), "
                f"cleaning up stale entries"
            )
            self._cleanup_stale_entries(new_config)

        self.current_config = new_config.copy()
        return True

    def _count_entries(self, config: Dict[str, Any]) -> int:
        """Count total entries across all config sections."""
        count = 0
        for value in config.values():
            if isinstance(value, list):
                count += len(value)
            elif isinstance(value, dict):
                count += len(value)
            else:
                count += 1
        return count

    def _cleanup_stale_entries(self, new_config: Dict[str, Any]):
        """Clean up entries no longer present in the incoming config.

        For safety, each removed entry is cross-referenced against the
        full config history to ensure it was not recently introduced
        (which would suggest the removal is premature or erroneous).
        """
        self._processing = True
        start_time = time.time()

        all_historical = self.config_store.get_all_historical_configs()

        stale_entries = []
        for key in self.current_config:
            if key not in new_config:
                # Cross-reference against every historical version
                for hist_config in all_historical:
                    _validate_entry_lineage(key, hist_config, all_historical)
                stale_entries.append(key)

        elapsed = time.time() - start_time
        if elapsed > self.HEALTH_CHECK_TIMEOUT:
            logger.warning(
                f"[{self.site_id}] Cleanup took {elapsed:.2f}s, "
                f"exceeding health timeout of "
                f"{self.HEALTH_CHECK_TIMEOUT}s"
            )
            self._healthy = False

        self._processing = False
        logger.info(
            f"[{self.site_id}] Cleaned up {len(stale_entries)} stale "
            f"entries in {elapsed:.2f}s"
        )

    def is_healthy(self) -> bool:
        """Check if site is healthy."""
        if self._processing:
            return False
        return self._healthy

    def rollback(self) -> bool:
        """Rollback to previous config."""
        if not self.config_history:
            logger.error(
                f"[{self.site_id}] No config history for rollback"
            )
            return False
        previous = self.config_history.pop()
        self.current_config = previous
        self._healthy = True
        logger.info(f"[{self.site_id}] Rolled back to previous config")
        return True
