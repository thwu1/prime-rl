#!/usr/bin/env python3
"""Generate test snapshot database for pool compaction task."""
import json
import sqlite3
import sys

sys.path.insert(0, "/app")
from pvec import PersistentVector
from serialize import serialize_pool


def main():
    conn = sqlite3.connect("/app/snapshots.db")
    conn.execute(
        "CREATE TABLE raw_pools ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT UNIQUE NOT NULL,"
        "  pool_json TEXT NOT NULL"
        ")"
    )

    pools = []

    # Snapshot 1: incrementally built counter vectors [0..i] for i in 0..9
    s1 = {}
    v = PersistentVector()
    for i in range(10):
        v = v.push_back(i)
        s1[f"counter_{i}"] = v
    pools.append(("snapshot_1", serialize_pool(s1)))

    # Snapshot 2: same base data + modifications (overlaps with snapshot_1)
    v_base = PersistentVector()
    for i in range(10):
        v_base = v_base.push_back(i)
    s2 = {
        "counter_9": v_base,
        "modified_0": v_base.set(0, 999),
        "extended": v_base.push_back(10).push_back(11).push_back(12),
    }
    pools.append(("snapshot_2", serialize_pool(s2)))

    # Snapshot 3: periodic snapshots at every 3rd element up to 14
    s3 = {}
    v = PersistentVector()
    for i in range(15):
        v = v.push_back(i)
        if i in (2, 5, 8, 11, 14):
            s3[f"triple_{i}"] = v
    pools.append(("snapshot_3", serialize_pool(s3)))

    # Snapshot 4: deep trees (50 elements)
    s4 = {}
    v = PersistentVector()
    for i in range(50):
        v = v.push_back(i)
        if i in (15, 30, 49):
            s4[f"deep_{i}"] = v
    pools.append(("snapshot_4", serialize_pool(s4)))

    # Snapshot 5: string vectors + a numeric duplicate of counter_7
    s5 = {}
    v = PersistentVector()
    for i in range(8):
        v = v.push_back(f"item_{i}")
        s5[f"str_{i}"] = v
    dup = PersistentVector()
    for i in range(8):
        dup = dup.push_back(i)
    s5["dup_counter_7"] = dup
    pools.append(("snapshot_5", serialize_pool(s5)))

    for name, pool in pools:
        conn.execute(
            "INSERT INTO raw_pools (name, pool_json) VALUES (?, ?)",
            (name, json.dumps(pool)),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
