#!/usr/bin/env python3
"""
Configuration Pipeline Orchestrator

Runs the full configuration pipeline:
1. Generate feature config from API
2. Load and validate the config
3. Run prefix cleanup task

This runs every 5 minutes in production. The pipeline is critical
for keeping the bot management ML model up-to-date.
"""

import logging
import sys
import os

logger = logging.getLogger('pipeline')


def run_pipeline():
    """Execute the full configuration pipeline."""
    logger.info("=" * 60)
    logger.info("Starting configuration pipeline run")
    logger.info("=" * 60)

    # Step 1: Generate feature config
    logger.info("Step 1: Generating feature configuration...")
    try:
        from config_generator import main as generate_config
        config_path = generate_config()
        logger.info("Step 1 complete: config at %s", config_path)
    except Exception as e:
        logger.critical("Step 1 FAILED: %s", e)
        return False

    # Step 2: Load and validate config
    logger.info("Step 2: Loading feature configuration...")
    try:
        from config_loader import load_features
        features = load_features(config_path)
        logger.info("Step 2 complete: %d features loaded", len(features))
    except RuntimeError as e:
        logger.critical("Step 2 FAILED: %s", e)
        return False
    except Exception as e:
        logger.critical("Step 2 FAILED (unexpected): %s", e)
        return False

    # Step 3: Run cleanup task
    logger.info("Step 3: Running prefix cleanup...")
    try:
        from cleanup_task import run_cleanup
        withdrawn, errors = run_cleanup()
        logger.info(
            "Step 3 complete: %d prefixes withdrawn, %d errors",
            withdrawn, errors,
        )
    except Exception as e:
        logger.critical("Step 3 FAILED: %s", e)
        return False

    logger.info("Pipeline run completed successfully")
    return True


if __name__ == '__main__':
    os.makedirs('/app/logs', exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/app/logs/pipeline.log'),
        ],
    )

    success = run_pipeline()
    sys.exit(0 if success else 1)
