#!/usr/bin/env python3
"""Set up regional policy databases with sample data.

Creates three SQLite databases (one per simulated region) with identical
schema and data, including a corrupt record that was replicated via the
global metadata pipeline on 2025-06-12.
"""
import os
import sqlite3

REGIONS = ['region1', 'region2', 'region3']
DATA_DIR = '/app/data'

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    id            INTEGER PRIMARY KEY,
    service_name  TEXT    NOT NULL UNIQUE,
    quota_limit   INTEGER NOT NULL,
    policy_type   TEXT    NOT NULL,
    metadata_json TEXT    NOT NULL,
    allowed_actions TEXT  NOT NULL
);
"""

# Normal, well-formed policy records
GOOD_POLICIES = [
    (1, 'compute.googleapis.com', 10000, 'standard',
     '{"rate_limit": {"tier": "standard", "burst": 100, "window_seconds": 60}, '
     '"description": "Compute Engine API"}',
     'instances.create,instances.delete,instances.get,instances.list'),

    (2, 'storage.googleapis.com', 50000, 'standard',
     '{"rate_limit": {"tier": "standard", "burst": 500, "window_seconds": 60}, '
     '"description": "Cloud Storage API"}',
     'objects.create,objects.get,objects.list,objects.delete,buckets.create,buckets.get'),

    (3, 'bigquery.googleapis.com', 5000, 'premium',
     '{"rate_limit": {"tier": "premium", "burst": 200, "window_seconds": 60}, '
     '"description": "BigQuery API"}',
     'jobs.insert,jobs.get,jobs.list,tables.get,tables.list,datasets.get'),

    (4, 'pubsub.googleapis.com', 20000, 'standard',
     '{"rate_limit": {"tier": "standard", "burst": 1000, "window_seconds": 60}, '
     '"description": "Cloud Pub/Sub API"}',
     'topics.publish,subscriptions.pull,topics.create,subscriptions.create'),

    (5, 'spanner.googleapis.com', 8000, 'enterprise',
     '{"rate_limit": {"tier": "enterprise", "burst": 300, "window_seconds": 60}, '
     '"description": "Cloud Spanner API"}',
     'sessions.create,sessions.read,sessions.commit,sessions.delete'),

    (6, 'cloudresourcemanager.googleapis.com', 3000, 'standard',
     '{"rate_limit": {"tier": "standard", "burst": 50, "window_seconds": 60}, '
     '"description": "Cloud Resource Manager API"}',
     'projects.get,projects.list,projects.create'),

    (7, 'container.googleapis.com', 15000, 'premium',
     '{"rate_limit": {"tier": "premium", "burst": 400, "window_seconds": 60}, '
     '"description": "Google Kubernetes Engine API"}',
     'clusters.create,clusters.get,clusters.delete,nodes.list'),
]

# Corrupt record - pushed via automated quota update on 2025-06-12 ~10:45 PDT.
# The metadata_json has null rate_limit and null burst_config fields.
# This was replicated globally within seconds.
CORRUPT_POLICY = (
    99, 'internal-quota-sync', 1000, 'internal',
    '{"rate_limit": null, "description": "Internal quota synchronization service", '
    '"burst_config": null}',
    'sync,replicate'
)


def setup_database(db_path):
    """Create or recreate a regional policy database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(SCHEMA)

    for record in GOOD_POLICIES:
        cursor.execute(
            "INSERT INTO policies VALUES (?, ?, ?, ?, ?, ?)", record
        )

    # Insert the corrupt record
    cursor.execute(
        "INSERT INTO policies VALUES (?, ?, ?, ?, ?, ?)", CORRUPT_POLICY
    )

    conn.commit()
    conn.close()
    print(f"  Created {db_path} with {len(GOOD_POLICIES) + 1} records")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("Setting up regional policy databases...")
    for region in REGIONS:
        db_path = os.path.join(DATA_DIR, f'policies_{region}.db')
        setup_database(db_path)
    print("Done.")


if __name__ == '__main__':
    main()
