"""
Fix all interacting defects in the config rollout pipeline,
implement the missing circuit breaker, and produce a root cause analysis.
"""

import sys
import os
import json

PIPELINE_DIR = "/app/config_pipeline"


def write_fixed_merger():
    """Fix defect 1: set intersection -> set union in deep_merge_keys."""
    path = os.path.join(PIPELINE_DIR, "merger.py")
    with open(path) as f:
        src = f.read()

    old = "confirmed_keys = primary_keys & secondary_keys"
    new = "confirmed_keys = primary_keys | secondary_keys"
    if old not in src:
        print("[warn] merger.py: expected pattern not found")
        return False

    src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    print("[fix] merger.py: deep_merge_keys now uses set union (|)")
    return True


def write_fixed_canary():
    """Fix defect 4: accept ip_ranges as alternative to ip_blocks."""
    path = os.path.join(PIPELINE_DIR, "canary.py")
    content = '''\
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

    REQUIRED_KEYS = {"routing_rules", "service_endpoints"}
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

            # Check that at least one IP field is present
            if "ip_blocks" not in config and "ip_ranges" not in config:
                msg = (
                    f"Canary FAILED on {site_id}: "
                    f"missing both ip_blocks and ip_ranges"
                )
                logger.error(msg)
                result.set_result(False, msg)
                return

            # Check IP entries are nonempty (accept either field name)
            ip_entries = config.get("ip_blocks", config.get("ip_ranges", []))
            if len(ip_entries) < self.MIN_IP_BLOCKS:
                msg = (
                    f"Canary FAILED on {site_id}: "
                    f"insufficient IP entries ({len(ip_entries)} "
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
'''
    with open(path, "w") as f:
        f.write(content)
    print("[fix] canary.py: accepts ip_ranges as alternative to ip_blocks")
    return True


def write_fixed_rollout():
    """Fix defects 2 and 5: wait for canary + integrate circuit breaker."""
    path = os.path.join(PIPELINE_DIR, "rollout.py")
    content = '''\
"""
Progressive rollout controller.

Rolls out configuration changes to sites in batches with canary
validation, health checking between batches, and rollback on failure.
"""
import logging
import time
from typing import Dict, Any, List

from .canary import CanaryValidator, CanaryResult
from .circuit_breaker import CircuitBreaker
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
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=0.5, window_size=3
        )

    def execute_rollout(self, config: Dict[str, Any]) -> bool:
        """Execute progressive rollout of config to all sites.

        Process:
        1. Validate on canary site (wait for async result)
        2. If canary passes, roll out to remaining sites in batches
        3. Health check between batches; trip circuit breaker on failures

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

        # Wait for the canary to finish before proceeding
        canary_result.wait(timeout=30.0)
        if not canary_result.is_completed or canary_result.success is False:
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
                batch_failures = 0
                for site in batch:
                    if not site.is_healthy():
                        batch_failures += 1
                        logger.error(
                            f"Site {site.site_id} unhealthy after config push"
                        )
                        self._log_event(
                            "HEALTH_FAILED", site.site_id,
                            "Post-push health check failed"
                        )
                self.circuit_breaker.record_batch(
                    len(batch), batch_failures
                )
                if self.circuit_breaker.is_tripped():
                    logger.error(
                        "Circuit breaker tripped! Halting rollout."
                    )
                    return False

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
'''
    with open(path, "w") as f:
        f.write(content)
    print("[fix] rollout.py: canary wait added + circuit breaker integrated")
    return True


def write_fixed_site():
    """Fix defect 3: replace O(n*m^2) cleanup with efficient key-set diff."""
    path = os.path.join(PIPELINE_DIR, "site.py")
    content = '''\
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
    """Validate that an entry\'s removal is safe by checking its lineage
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

        Uses efficient key-set difference rather than expensive
        historical lineage validation.
        """
        self._processing = True
        start_time = time.time()

        stale_entries = [
            key for key in self.current_config if key not in new_config
        ]

        elapsed = time.time() - start_time
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
'''
    with open(path, "w") as f:
        f.write(content)
    print("[fix] site.py: replaced O(n*m^2) cleanup with key-set diff")
    return True


def write_circuit_breaker():
    """Implement the CircuitBreaker class (defect 5)."""
    path = os.path.join(PIPELINE_DIR, "circuit_breaker.py")
    content = '''\
"""
Circuit breaker for the rollout controller.

Tracks batch-level health outcomes using a rolling window and trips
when the failure rate exceeds a configurable threshold.  Once tripped,
prevents further rollout batches until manually reset.
"""


class CircuitBreaker:
    """Circuit breaker that halts operations when failure rate is excessive.

    Parameters
    ----------
    failure_threshold : float
        Fraction of total sites across tracked batches that may be
        unhealthy before the breaker trips (>=).  Range 0.0--1.0.
    window_size : int
        Maximum number of recent batches to consider when computing
        the rolling failure rate.
    """

    def __init__(self, failure_threshold: float = 0.5, window_size: int = 3):
        self._threshold = failure_threshold
        self._window_size = window_size
        self._batches: list = []
        self._tripped: bool = False

    def record_batch(self, batch_size: int, failures: int) -> None:
        """Record the health outcome of a single rollout batch."""
        self._batches.append((batch_size, failures))
        if len(self._batches) > self._window_size:
            self._batches = self._batches[-self._window_size:]
        if self.failure_rate() >= self._threshold:
            self._tripped = True

    def is_tripped(self) -> bool:
        """Return True if the circuit breaker has tripped (is open)."""
        return self._tripped

    def reset(self) -> None:
        """Manually close (reset) the circuit breaker and clear history."""
        self._batches.clear()
        self._tripped = False

    def failure_rate(self) -> float:
        """Return the rolling failure rate across tracked batches."""
        if not self._batches:
            return 0.0
        total_sites = sum(bs for bs, _ in self._batches)
        total_failures = sum(f for _, f in self._batches)
        return total_failures / total_sites if total_sites > 0 else 0.0
'''
    with open(path, "w") as f:
        f.write(content)
    print("[fix] circuit_breaker.py: implemented CircuitBreaker class")
    return True


def write_rca():
    """Produce the structured root cause analysis."""
    rca = {
        "defects": [
            {
                "module": "merger.py",
                "function": "deep_merge_keys",
                "description": (
                    "Uses set intersection (&) instead of union (|) when "
                    "computing the merged key set from two sources. During "
                    "propagation delay, keys unique to either source (ip_blocks "
                    "in secondary, ip_ranges in primary) are dropped, producing "
                    "a config missing all networking fields."
                )
            },
            {
                "module": "rollout.py",
                "function": "execute_rollout",
                "description": (
                    "Checks canary_result.is_completed immediately after "
                    "launching async validation without waiting for completion. "
                    "Because the canary runs in a background thread with a delay, "
                    "is_completed is always False, making the canary check a "
                    "no-op that lets bad configs through."
                )
            },
            {
                "module": "site.py",
                "function": "_cleanup_stale_entries",
                "description": (
                    "Loads all historical configs and performs O(n*m^2) hash "
                    "comparisons with 10ms I/O sleeps per iteration. With 20+ "
                    "historical versions, cleanup takes >4s, exceeding the 2s "
                    "health-check timeout and marking each site unhealthy."
                )
            },
            {
                "module": "canary.py",
                "function": "CanaryValidator",
                "description": (
                    "REQUIRED_KEYS hardcodes 'ip_blocks' as mandatory. After "
                    "the field migration to 'ip_ranges', post-migration configs "
                    "are incorrectly rejected even when they contain valid "
                    "networking data under the new field name."
                )
            },
            {
                "module": "circuit_breaker.py",
                "function": "CircuitBreaker",
                "description": (
                    "Circuit breaker class was designed (interface documented) "
                    "but never implemented — all methods raise NotImplementedError. "
                    "Without it, batch health failures are logged but the rollout "
                    "continues to the entire fleet, propagating the cascade."
                )
            }
        ]
    }

    os.makedirs("/app/data", exist_ok=True)
    with open("/app/data/rca.json", "w") as f:
        json.dump(rca, f, indent=2)
    print("[rca] Wrote root cause analysis to /app/data/rca.json")
    return True


if __name__ == "__main__":
    results = [
        write_fixed_merger(),
        write_fixed_canary(),
        write_fixed_rollout(),
        write_fixed_site(),
        write_circuit_breaker(),
        write_rca(),
    ]
    if all(results):
        print("\nAll defects fixed, circuit breaker implemented, RCA written.")
    else:
        print("\nWARNING: Some fixes may not have applied correctly.")
        sys.exit(1)
