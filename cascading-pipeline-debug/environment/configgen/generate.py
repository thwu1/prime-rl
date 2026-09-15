#!/usr/bin/env python3
"""
Feature config generator for the Bot Management ML model.

Queries the pipeline database to get feature column metadata from the
http_requests_features table and generates a JSON feature configuration file.

The database uses a distributed table layout where the 'default' database
contains distributed tables and the 'r0' database contains the underlying
local replica tables.
"""
import sqlite3
import json
import os
import sys

DB_PATH = "/app/data/pipeline.db"
OUTPUT_PATH = "/app/config/features.json"


def generate_features():
    """Query feature columns and generate the ML model configuration file."""
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Query feature columns from the database metadata
    # This mirrors the ClickHouse system.columns query pattern
    cursor.execute("""
        SELECT column_name, column_type
        FROM feature_columns
        WHERE table_name = 'http_requests_features'
        ORDER BY column_name
    """)

    rows = cursor.fetchall()
    features = []
    for name, ftype in rows:
        features.append({"name": name, "type": ftype})

    config = {
        "version": "2.1",
        "model_id": "bot_score_v3",
        "features": features,
        "feature_count": len(features)
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Generated config with {len(features)} features at {OUTPUT_PATH}")
    conn.close()
    return config


if __name__ == "__main__":
    generate_features()
