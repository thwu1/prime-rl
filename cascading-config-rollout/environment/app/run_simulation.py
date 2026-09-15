"""
Configuration Rollout Simulation
=================================

Simulates a multi-site configuration rollout pipeline modeled after
production infrastructure used in large-scale cloud platforms.

Scenario:
  An engineer updates the primary config source (migrating the
  ``ip_blocks`` field to ``ip_ranges`` as part of a naming migration).
  The secondary source has not yet received the update due to
  replication lag.  The config management pipeline must safely handle
  this transient inconsistency.

Usage::

    python3 run_simulation.py

Exit code 0 = rollout succeeded safely
Exit code 1 = rollout caused failures
"""

import json
import logging
import os
import shutil
import sys
import time

from config_pipeline.store import DualSourceConfigStore
from config_pipeline.merger import merge_configs
from config_pipeline.canary import CanaryValidator
from config_pipeline.rollout import RolloutController
from config_pipeline.site import SiteManager
from config_pipeline.health import HealthChecker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/data/simulation.log", mode="w"),
    ],
)
logger = logging.getLogger("simulation")

SITE_IDS = [
    "site-us-east1",
    "site-us-east4",
    "site-us-west1",
    "site-us-west2",
    "site-eu-west1",
    "site-eu-west4",
    "site-asia-east1",
    "site-asia-south1",
]

INITIAL_CONFIG = {
    "ip_blocks": [
        "35.192.0.0/14",
        "35.196.0.0/15",
        "35.198.0.0/16",
        "35.199.0.0/17",
        "35.199.128.0/18",
        "35.200.0.0/13",
        "35.208.0.0/13",
        "35.216.0.0/15",
        "35.218.0.0/16",
        "35.219.0.0/17",
        "35.220.0.0/14",
    ],
    "routing_rules": {
        "default_backend": "backend-pool-1",
        "health_check_path": "/healthz",
        "timeout_ms": 30000,
        "max_retries": 3,
        "failover_pool": "backend-pool-2",
        "drain_timeout_ms": 60000,
    },
    "service_endpoints": {
        "compute": "compute.internal.gcp:443",
        "storage": "storage.internal.gcp:443",
        "pubsub": "pubsub.internal.gcp:443",
        "spanner": "spanner.internal.gcp:443",
        "bigquery": "bigquery.internal.gcp:443",
    },
    "metadata": {
        "version": "2024.01.14",
        "last_updated_by": "config-automation",
        "change_ticket": "CHG-2024-0114",
    },
}


def create_migrated_config():
    """Create config with ip_blocks renamed to ip_ranges (field migration).

    Also removes the unused 35.219.0.0/17 block while migrating.
    """
    migrated = {
        "ip_ranges": [
            ip for ip in INITIAL_CONFIG["ip_blocks"]
            if ip != "35.219.0.0/17"
        ],
        "routing_rules": json.loads(
            json.dumps(INITIAL_CONFIG["routing_rules"])
        ),
        "service_endpoints": json.loads(
            json.dumps(INITIAL_CONFIG["service_endpoints"])
        ),
        "metadata": {
            "version": "2024.01.15",
            "last_updated_by": "config-automation",
            "change_ticket": "CHG-2024-0115-migration",
        },
    }
    return migrated


def run_simulation():
    logger.info("=" * 60)
    logger.info("CONFIGURATION ROLLOUT SIMULATION")
    logger.info("=" * 60)

    store_dir = "/app/data/config_store"
    if os.path.exists(store_dir):
        shutil.rmtree(store_dir)

    # --- Initialize config store ---
    logger.info("Initializing dual-source config store ...")
    store = DualSourceConfigStore(store_dir)

    # Seed with historical versions (makes cleanup cost observable)
    for i in range(20):
        historical = json.loads(json.dumps(INITIAL_CONFIG))
        historical["metadata"]["version"] = f"2023.{12 - i:02d}.01"
        store.primary.put_config(historical)
        store.secondary.put_config(historical)

    store.initialize(INITIAL_CONFIG)

    # --- Initialize sites ---
    logger.info(f"Initializing {len(SITE_IDS)} sites ...")
    sites = [
        SiteManager(sid, store, INITIAL_CONFIG.copy())
        for sid in SITE_IDS
    ]

    canary = CanaryValidator(validation_delay=0.5)
    rollout = RolloutController(
        sites, canary, batch_size=2, batch_delay=0.5
    )
    health = HealthChecker(sites)

    initial_health = health.check_all()
    assert all(initial_health.values()), (
        f"Sites unhealthy at start: {initial_health}"
    )
    logger.info("All sites healthy")

    # === SIMULATE THE INCIDENT ===
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "SIMULATING CONFIG CHANGE: ip_blocks -> ip_ranges migration"
    )
    logger.info("=" * 60)

    migrated_config = create_migrated_config()

    # Update primary; secondary will lag behind
    logger.info(
        "Updating primary config source "
        "(secondary will sync after delay) ..."
    )
    store.update_config(migrated_config, propagation_delay=3.0)
    time.sleep(0.1)  # let primary write settle

    primary_config = store.get_primary_config()
    secondary_config = store.get_secondary_config()

    logger.info(f"Primary keys  : {sorted(primary_config.keys())}")
    logger.info(f"Secondary keys: {sorted(secondary_config.keys())}")

    # --- Merge ---
    logger.info("Merging configs from both sources ...")
    merged_config, had_inconsistency = merge_configs(
        primary_config, secondary_config
    )
    if had_inconsistency:
        logger.warning(
            "CONFIG INCONSISTENCY between primary and secondary"
        )
    logger.info(f"Merged config keys: {sorted(merged_config.keys())}")
    logger.info(
        f"Merged has ip_blocks: {'ip_blocks' in merged_config}, "
        f"ip_ranges: {'ip_ranges' in merged_config}"
    )

    # --- Rollout ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXECUTING PROGRESSIVE ROLLOUT")
    logger.info("=" * 60)

    rollout_success = rollout.execute_rollout(merged_config)

    # --- Final status ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("FINAL STATUS")
    logger.info("=" * 60)

    final_health = health.check_all()
    all_healthy = all(final_health.values())

    for site_id, healthy in final_health.items():
        status = "HEALTHY" if healthy else "UNHEALTHY"
        logger.info(f"  {site_id}: {status}")

    config_intact = True
    for site in sites:
        has_ip = (
            "ip_blocks" in site.current_config
            or "ip_ranges" in site.current_config
        )
        if not has_ip:
            logger.error(
                f"  {site.site_id}: MISSING ip_blocks/ip_ranges!"
            )
            config_intact = False
        if "routing_rules" not in site.current_config:
            logger.error(
                f"  {site.site_id}: MISSING routing_rules!"
            )
            config_intact = False
        if "service_endpoints" not in site.current_config:
            logger.error(
                f"  {site.site_id}: MISSING service_endpoints!"
            )
            config_intact = False

    if rollout_success and all_healthy and config_intact:
        logger.info("")
        logger.info(
            "RESULT: ROLLOUT SUCCEEDED - "
            "All sites healthy with valid configs"
        )
        return 0
    else:
        logger.error("")
        logger.error("RESULT: ROLLOUT FAILED")
        logger.error(f"  Rollout success: {rollout_success}")
        logger.error(f"  All healthy    : {all_healthy}")
        logger.error(f"  Configs intact : {config_intact}")
        return 1


if __name__ == "__main__":
    sys.exit(run_simulation())
