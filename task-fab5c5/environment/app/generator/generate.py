#!/usr/bin/env python3
"""
Bot Management Feature File Generator

Generates the feature configuration file used by the FL2 proxy's bot
management ML model. The feature file is a JSON document listing all
ML features (columns) from the http_requests_features table.

This generator queries column metadata from a ClickHouse shard's
system_columns table, simulating how the real system constructs
feature definitions from database metadata.

The feature file is refreshed every 5 minutes and published to the
entire network, allowing rapid response to changing bot tactics.
"""

import sqlite3
import json
import random
import os
import logging
from datetime import datetime

logging.basicConfig(
    filename='/app/logs/generator.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

SHARD_DIR = "/app/db/shards"
OUTPUT_DIR = "/app/features"


def get_available_shards():
    """Discover available database shards."""
    shards = []
    if not os.path.isdir(SHARD_DIR):
        return shards
    for f in sorted(os.listdir(SHARD_DIR)):
        if f.startswith("shard_") and f.endswith(".db"):
            shards.append(os.path.join(SHARD_DIR, f))
    return shards


def generate_feature_file(shard_path=None):
    """Generate bot management feature configuration file.

    Queries column metadata from the specified shard to build the
    feature list. If no shard is specified, one is selected at random
    (simulating load-balanced access to the distributed database).

    Args:
        shard_path: Path to a specific shard database file.
                    If None, a random shard is selected.

    Returns:
        Tuple of (output_path, feature_count)
    """
    if shard_path is None:
        shards = get_available_shards()
        if not shards:
            raise RuntimeError("No database shards available")
        shard_path = random.choice(shards)

    logger.info(f"Generating feature file from shard: {shard_path}")

    conn = sqlite3.connect(shard_path)
    cursor = conn.cursor()

    # Query column metadata for the features table.
    # This constructs the list of ML features from database schema metadata.
    cursor.execute("""
        SELECT name, type
        FROM system_columns
        WHERE table_name = 'http_requests_features'
        ORDER BY name
    """)

    columns = cursor.fetchall()
    conn.close()

    features = []
    for col_name, col_type in columns:
        features.append({
            "name": col_name,
            "type": col_type,
            "enabled": True,
            "weight": 1.0
        })

    feature_file = {
        "version": 2,
        "generated_at": datetime.utcnow().isoformat(),
        "shard_source": os.path.basename(shard_path),
        "features": features,
        "feature_count": len(features)
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "bot_features.json")

    with open(output_path, 'w') as f:
        json.dump(feature_file, f, indent=2)

    logger.info(f"Generated feature file with {len(features)} features")
    return output_path, len(features)


if __name__ == "__main__":
    import sys
    shard = sys.argv[1] if len(sys.argv) > 1 else None
    path, count = generate_feature_file(shard)
    print(f"Generated {count} features -> {path}")
