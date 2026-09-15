#!/usr/bin/env python3
"""
Feature Configuration Loader

Loads the generated feature configuration file into the proxy's
ML model runtime. Preallocates memory for feature arrays based
on a fixed maximum to ensure predictable performance.

The maximum feature count (MAX_FEATURES) is set as an upper bound
for memory preallocation. Exceeding this limit indicates a problem
with the configuration pipeline.
"""

import json
import logging
import sys
import os

MAX_FEATURES = 200

logger = logging.getLogger('config_loader')


def load_features(config_path):
    """Load features from a configuration file.

    Reads the config, validates the feature count against the
    preallocated limit, and returns the feature array.

    Args:
        config_path: Path to the JSON configuration file

    Returns:
        List of feature definitions

    Raises:
        RuntimeError: If feature count exceeds MAX_FEATURES
    """
    with open(config_path) as f:
        config = json.load(f)

    features = config.get('features', [])
    feature_count = len(features)

    logger.info("Loading config: %s (%d features)", config_path, feature_count)

    # Validate against preallocated limit
    # This limit exists for memory preallocation performance optimization
    if feature_count > MAX_FEATURES:
        # Equivalent to Rust: Result::unwrap() on Err
        raise RuntimeError(
            f"Feature count {feature_count} exceeds maximum allocation "
            f"limit of {MAX_FEATURES}. Aborting to prevent unbounded "
            f"memory consumption."
        )

    # Preallocate feature array
    feature_array = [None] * MAX_FEATURES
    for i, feature in enumerate(features):
        feature_array[i] = feature

    logger.info(
        "Features loaded successfully: %d/%d slots used",
        feature_count, MAX_FEATURES,
    )
    return features


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else '/app/configs/features_latest.json'

    if not os.path.exists(config_path):
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    try:
        features = load_features(config_path)
        print(f"Loaded {len(features)} features successfully")
    except RuntimeError as e:
        logger.critical("FATAL: %s", e)
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/app/logs/pipeline.log'),
        ],
    )
    main()
