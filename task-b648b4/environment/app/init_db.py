"""Initialize the policy database with schema and seed data."""

import sqlite3
import os

DB_PATH = "/app/db/policies.db"


def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_policies (
            policy_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            enforcement_mode TEXT,
            quota_limit INTEGER,
            quota_window TEXT,
            description TEXT,
            updated_at TEXT
        )
    """)

    # Production policy seed data
    policies = [
        ("quota-compute-001", "compute.googleapis.com", "ENFORCED", 1000, "1m",
         "Compute Engine API rate limit", "2025-06-01T00:00:00Z"),
        ("quota-storage-001", "storage.googleapis.com", "ENFORCED", 5000, "1m",
         "Cloud Storage API rate limit", "2025-06-01T00:00:00Z"),
        ("quota-bigquery-001", "bigquery.googleapis.com", "SHADOW", 200, "1m",
         "BigQuery API rate limit (shadow mode)", "2025-06-01T00:00:00Z"),
        ("quota-pubsub-001", "pubsub.googleapis.com", "ENFORCED", 10000, "1m",
         "Pub/Sub API rate limit", "2025-06-01T00:00:00Z"),
        ("quota-spanner-001", "spanner.googleapis.com", "ENFORCED", 500, "1m",
         "Cloud Spanner API rate limit", "2025-06-01T00:00:00Z"),
        ("quota-gke-001", "container.googleapis.com", "ENFORCED", 2000, "1m",
         "GKE API rate limit", "2025-06-01T00:00:00Z"),
        ("quota-dns-001", "dns.googleapis.com", "DISABLED", 3000, "1m",
         "Cloud DNS API rate limit (disabled)", "2025-06-01T00:00:00Z"),
    ]

    for p in policies:
        conn.execute(
            "INSERT OR IGNORE INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)", p
        )

    # Records from automated quota synchronization batch (2025-06-12 10:45)
    conn.execute(
        "INSERT OR IGNORE INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("quota-iam-special-002", "iam.googleapis.com", None, None, None,
         "Auto-generated policy from quota update", "2025-06-12T10:45:00Z")
    )
    conn.execute(
        "INSERT OR IGNORE INTO active_policies VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("quota-logging-special-003", "logging.googleapis.com", "", "", "",
         "Auto-generated policy from quota update", "2025-06-12T10:45:00Z")
    )

    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    init()
