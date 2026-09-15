#!/usr/bin/env python3
"""Compaction and structural diff helper."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, "/app")
from pool_store import PoolStore
from diff_engine import StructuralDiff


def find_version_pairs(vector_names):
    """Group vectors by common prefix and return consecutive pairs."""
    groups = {}
    for name in vector_names:
        parts = name.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            prefix = parts[0]
            idx = int(parts[1])
            groups.setdefault(prefix, []).append((idx, name))

    pairs = []
    for prefix in sorted(groups):
        sorted_vecs = sorted(groups[prefix])
        for i in range(len(sorted_vecs) - 1):
            pairs.append((sorted_vecs[i][1], sorted_vecs[i + 1][1]))
    return pairs


def main():
    conn = sqlite3.connect("/app/snapshots.db")
    rows = conn.execute(
        "SELECT name, pool_json FROM raw_pools ORDER BY id"
    ).fetchall()
    conn.close()

    total_raw = sum(len(json.loads(r[1])["nodes"]) for r in rows)

    if os.path.exists("/app/compacted.db"):
        os.unlink("/app/compacted.db")

    store = PoolStore("/app/compacted.db")
    for name, pjson in rows:
        store.import_pool(json.loads(pjson), name)

    exported = store.export_all()
    with open("/app/exported_pool.json", "w") as f:
        json.dump(exported, f)

    # Structural diffs between related version pairs
    differ = StructuralDiff(store)
    all_names = [
        row[0]
        for row in store.conn.execute("SELECT name FROM vectors").fetchall()
    ]
    pairs = find_version_pairs(all_names)

    diff_summary = {}
    for name_a, name_b in pairs:
        result = differ.diff(name_a, name_b)
        label = f"{name_a}->{name_b}"
        diff_summary[label] = {
            "nodes_visited": result["stats"]["nodes_visited"],
            "nodes_skipped": result["stats"]["nodes_skipped"],
            "modifications": len(result["modified"]),
            "additions": len(result["added"]),
        }

    stats = store.stats()
    integrity = store.verify_integrity()
    report = {
        "total_raw_nodes": total_raw,
        "compacted_nodes": stats["total_nodes"],
        "reduction_pct": (
            round(100 * (1 - stats["total_nodes"] / total_raw), 1)
            if total_raw > 0
            else 0
        ),
        "vectors_imported": stats["total_vectors"],
        "integrity": integrity,
        "diff_summary": diff_summary,
    }
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    store.close()


if __name__ == "__main__":
    main()
