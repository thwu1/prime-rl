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

  Phase 1: Migration rollout during propagation delay.
  Phase 2: Post-migration steady-state validation (both sources
           converged on ``ip_ranges``).

Usage::

    python3 run_simulation.py

Exit code 0 = both phases succeeded safely
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

PROPAGATION_DELAY = 2.0


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

    health = HealthChecker(sites)

    initial_health = health.check_all()
    assert all(initial_health.values()), (
        f"Sites unhealthy at start: {initial_health}"
    )
    logger.info("All sites healthy")

    # =================================================================
    # PHASE 1: MIGRATION WITH PROPAGATION DELAY
    # =================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "PHASE 1: CONFIG MIGRATION (ip_blocks -> ip_ranges)"
    )
    logger.info("=" * 60)

    migrated_config = create_migrated_config()

    # Update primary; secondary will lag behind
    logger.info(
        "Updating primary config source "
        "(secondary will sync after delay) ..."
    )
    store.update_config(migrated_config, propagation_delay=PROPAGATION_DELAY)
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

    # --- Rollout Phase 1 ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXECUTING PHASE 1 PROGRESSIVE ROLLOUT")
    logger.info("=" * 60)

    canary = CanaryValidator(validation_delay=0.3)
    rollout = RolloutController(
        sites, canary, batch_size=2, batch_delay=0.3
    )
    rollout_success = rollout.execute_rollout(merged_config)

    # --- Phase 1 status ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("PHASE 1 STATUS")
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

    if not (rollout_success and all_healthy and config_intact):
        logger.error("")
        logger.error("PHASE 1 FAILED")
        logger.error(f"  Rollout success: {rollout_success}")
        logger.error(f"  All healthy    : {all_healthy}")
        logger.error(f"  Configs intact : {config_intact}")
        return 1

    logger.info("Phase 1 completed successfully")

    # =================================================================
    # PHASE 2: POST-MIGRATION STEADY STATE
    # =================================================================
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "PHASE 2: POST-MIGRATION STEADY-STATE VALIDATION"
    )
    logger.info("=" * 60)

    # Wait for secondary to finish catching up
    logger.info("Waiting for secondary config source to synchronize ...")
    time.sleep(PROPAGATION_DELAY + 1.0)

    # Re-read and merge — sources should now be consistent
    primary_config_2 = store.get_primary_config()
    secondary_config_2 = store.get_secondary_config()

    logger.info(f"Primary keys  : {sorted(primary_config_2.keys())}")
    logger.info(f"Secondary keys: {sorted(secondary_config_2.keys())}")

    merged_config_2, had_inconsistency_2 = merge_configs(
        primary_config_2, secondary_config_2
    )

    if had_inconsistency_2:
        logger.warning(
            "Unexpected: sources still inconsistent after sync period"
        )
    else:
        logger.info("Config sources are now consistent (both have ip_ranges)")

    logger.info(
        f"Post-migration config keys: {sorted(merged_config_2.keys())}"
    )

    # Rollout the steady-state config
    canary_2 = CanaryValidator(validation_delay=0.2)
    rollout_2 = RolloutController(
        sites, canary_2, batch_size=3, batch_delay=0.2
    )

    logger.info("Executing post-migration rollout ...")
    rollout_success_2 = rollout_2.execute_rollout(merged_config_2)

    final_health_2 = health.check_all()
    all_healthy_2 = all(final_health_2.values())

    if not rollout_success_2 or not all_healthy_2:
        logger.error("")
        logger.error("PHASE 2 FAILED")
        logger.error(f"  Rollout success: {rollout_success_2}")
        logger.error(f"  All healthy    : {all_healthy_2}")
        return 1

    # --- Final ---
    logger.info("")
    logger.info("=" * 60)
    logger.info(
        "RESULT: ALL PHASES COMPLETED SUCCESSFULLY"
    )
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run_simulation())
