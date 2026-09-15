#!/usr/bin/env python3
"""Initialize cluster_config.db with anti-affinity rules and scheduling configuration."""
import sqlite3
import os

DB_PATH = "/app/cluster_config.db"


def init():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE anti_affinity (
            group_a TEXT NOT NULL,
            group_b TEXT NOT NULL,
            constraint_id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)

    conn.execute("""
        CREATE TABLE scheduling_policy (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            description TEXT
        )
    """)

    # Anti-affinity pairs: groups in these pairs must not have tasks co-located
    # on the same agent. Rules are bidirectional (if A-B exists, B cannot be
    # placed with A and vice versa).
    pairs = [
        ("grp-x", "grp-y"),
        ("gang-a", "other-b"),
        ("grp-alpha", "grp-beta"),
        ("grp-red", "grp-blue"),
        ("svc-frontend", "svc-backend"),
    ]
    conn.executemany(
        "INSERT INTO anti_affinity (group_a, group_b) VALUES (?, ?)", pairs
    )

    # Scheduling policy configuration
    configs = [
        ("placement_mode", "multi_resource",
         "Placement considers both gpu_slots and mem_mb when assigning tasks to agents"),
        ("gang_failure_action", "redistribute",
         "When a gang group cannot be fully scheduled, redistribute its offered slots"),
        ("preemption_scope", "cross_priority",
         "Preemption candidates include tasks from strictly lower priority groups"),
    ]
    conn.executemany(
        "INSERT INTO scheduling_policy (key, value, description) VALUES (?, ?, ?)",
        configs,
    )

    conn.commit()
    conn.close()
    print(f"Initialized {DB_PATH}")


if __name__ == "__main__":
    init()
