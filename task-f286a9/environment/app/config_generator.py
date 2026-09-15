#!/usr/bin/env python3
"""
Feature Configuration Generator

Fetches feature metadata from the API and generates configuration
files for the bot management ML model. These config files are
distributed to all edge proxy instances for real-time bot scoring.

The generator runs every 5 minutes to keep the model updated with
the latest feature definitions.
"""

import json
import requests
import logging
import os
from datetime import datetime

API_BASE = os.environ.get('API_BASE', 'http://localhost:8080')
CONFIG_DIR = '/app/configs'

logger = logging.getLogger('config_generator')


def fetch_features(table='http_requests_features'):
    """Fetch feature definitions from the metadata API."""
    resp = requests.get(f"{API_BASE}/api/features", params={"table": table})
    resp.raise_for_status()
    return resp.json()


def generate_config(features):
    """Generate a feature configuration file from API response."""
    config = {
        "version": datetime.utcnow().isoformat(),
        "table": "http_requests_features",
        "feature_count": len(features),
        "features": [],
    }

    for feat in features:
        config["features"].append({
            "name": feat["name"],
            "type": feat["type"],
            "enabled": True,
            "weight": 1.0,
        })

    return config


def write_config(config, path=None):
    """Write the configuration file to disk."""
    if path is None:
        path = os.path.join(CONFIG_DIR, 'features_latest.json')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)

    size_kb = os.path.getsize(path) / 1024
    logger.info(
        "Config written: %s (%d features, %.1fKB)",
        path, config['feature_count'], size_kb,
    )
    return path


def main():
    logger.info("Starting feature config generation")

    features = fetch_features()
    logger.info("Retrieved %d features from API", len(features))

    config = generate_config(features)
    path = write_config(config)

    logger.info("Config generation complete: %s", path)
    return path


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
