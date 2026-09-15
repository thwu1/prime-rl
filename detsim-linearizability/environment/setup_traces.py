#!/usr/bin/env python3
"""Generate pre-built simulation traces for the task database."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dessim import Simulator, init_db

CONFIGS = [
    # Run 1: No faults, simple sequential clients
    {
        "label": "clean_sequential",
        "seed": 100,
        "config": {
            "simulation": {"node_count": 5, "duration": 500, "seed": 100, "election_timeout": 100.0},
            "clients": {"count": 2, "request_interval": 60.0, "write_ratio": 0.4},
            "faults": {"schedule": []},
        },
    },
    # Run 2: No faults, high concurrency
    {
        "label": "clean_concurrent",
        "seed": 201,
        "config": {
            "simulation": {"node_count": 5, "duration": 600, "seed": 201, "election_timeout": 100.0},
            "clients": {"count": 5, "request_interval": 30.0, "write_ratio": 0.5},
            "faults": {"schedule": []},
        },
    },
    # Run 3: Secondary crash (should be fine)
    {
        "label": "secondary_crash",
        "seed": 302,
        "config": {
            "simulation": {"node_count": 5, "duration": 600, "seed": 302, "election_timeout": 100.0},
            "clients": {"count": 3, "request_interval": 40.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "crash", "target": 3, "time": 200, "recover_after": 150},
            ]},
        },
    },
    # Run 4: Primary crash with recovery -> potential lost writes
    {
        "label": "primary_crash_recover",
        "seed": 403,
        "config": {
            "simulation": {"node_count": 5, "duration": 800, "seed": 403, "election_timeout": 80.0},
            "clients": {"count": 3, "request_interval": 35.0, "write_ratio": 0.6},
            "faults": {"schedule": [
                {"type": "crash", "target": "primary", "time": 250, "recover_after": 120},
            ]},
        },
    },
    # Run 5: Network partition -> split-brain (primary isolated)
    {
        "label": "partition_split_brain",
        "seed": 504,
        "config": {
            "simulation": {"node_count": 5, "duration": 800, "seed": 504, "election_timeout": 60.0},
            "clients": {"count": 5, "request_interval": 35.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4],
                 "time": 200, "heal_after": 300},
            ]},
        },
    },
    # Run 6: Partition + crash -> complex failure
    {
        "label": "partition_and_crash",
        "seed": 605,
        "config": {
            "simulation": {"node_count": 5, "duration": 900, "seed": 605, "election_timeout": 70.0},
            "clients": {"count": 4, "request_interval": 40.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0, 1], "set_b": [2, 3, 4], "time": 180, "heal_after": 250},
                {"type": "crash", "target": 0, "time": 220, "recover_after": 200},
            ]},
        },
    },
    # Run 7: Quick partition (heals fast, might be OK)
    {
        "label": "quick_partition",
        "seed": 706,
        "config": {
            "simulation": {"node_count": 5, "duration": 600, "seed": 706, "election_timeout": 150.0},
            "clients": {"count": 3, "request_interval": 50.0, "write_ratio": 0.4},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4],
                 "time": 200, "heal_after": 40},
            ]},
        },
    },
    # Run 8: Multiple sequential crashes
    {
        "label": "cascading_crashes",
        "seed": 807,
        "config": {
            "simulation": {"node_count": 5, "duration": 1000, "seed": 807, "election_timeout": 80.0},
            "clients": {"count": 3, "request_interval": 45.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "crash", "target": "primary", "time": 200, "recover_after": 100},
                {"type": "crash", "target": "primary", "time": 450, "recover_after": 100},
            ]},
        },
    },
    # Run 9: Long partition with many writes
    {
        "label": "long_partition",
        "seed": 908,
        "config": {
            "simulation": {"node_count": 5, "duration": 1000, "seed": 908, "election_timeout": 60.0},
            "clients": {"count": 5, "request_interval": 25.0, "write_ratio": 0.6},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4],
                 "time": 100, "heal_after": 600},
            ]},
        },
    },
    # Run 10: No faults, reads only
    {
        "label": "reads_only",
        "seed": 1009,
        "config": {
            "simulation": {"node_count": 5, "duration": 400, "seed": 1009, "election_timeout": 100.0},
            "clients": {"count": 3, "request_interval": 40.0, "write_ratio": 0.0},
            "faults": {"schedule": []},
        },
    },
    # Run 11: Asymmetric partition (2 vs 3)
    {
        "label": "asymmetric_partition",
        "seed": 1110,
        "config": {
            "simulation": {"node_count": 5, "duration": 800, "seed": 1110, "election_timeout": 60.0},
            "clients": {"count": 5, "request_interval": 30.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0, 1], "set_b": [2, 3, 4],
                 "time": 200, "heal_after": 300},
            ]},
        },
    },
    # Run 12: Primary crash no recovery
    {
        "label": "primary_crash_permanent",
        "seed": 1211,
        "config": {
            "simulation": {"node_count": 5, "duration": 800, "seed": 1211, "election_timeout": 70.0},
            "clients": {"count": 3, "request_interval": 40.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "crash", "target": "primary", "time": 200},
            ]},
        },
    },
    # Run 13: 3-way partition
    {
        "label": "three_way_partition",
        "seed": 1312,
        "config": {
            "simulation": {"node_count": 5, "duration": 900, "seed": 1312, "election_timeout": 60.0},
            "clients": {"count": 5, "request_interval": 30.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4], "time": 150, "heal_after": 100},
                {"type": "partition", "set_a": [0, 1], "set_b": [2, 3, 4], "time": 350, "heal_after": 200},
            ]},
        },
    },
    # Run 14: Partition heals then re-partitions
    {
        "label": "partition_flap",
        "seed": 1413,
        "config": {
            "simulation": {"node_count": 5, "duration": 1000, "seed": 1413, "election_timeout": 60.0},
            "clients": {"count": 4, "request_interval": 35.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4], "time": 150, "heal_after": 150},
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4], "time": 500, "heal_after": 200},
            ]},
        },
    },
    # Run 15: No faults, write-heavy
    {
        "label": "clean_write_heavy",
        "seed": 1514,
        "config": {
            "simulation": {"node_count": 5, "duration": 500, "seed": 1514, "election_timeout": 100.0},
            "clients": {"count": 3, "request_interval": 30.0, "write_ratio": 0.8},
            "faults": {"schedule": []},
        },
    },
    # Run 16: Partition with crash in minority (reduced ops for performance)
    {
        "label": "minority_crash_partition",
        "seed": 1615,
        "config": {
            "simulation": {"node_count": 5, "duration": 500, "seed": 1615, "election_timeout": 60.0},
            "clients": {"count": 3, "request_interval": 50.0, "write_ratio": 0.5},
            "faults": {"schedule": [
                {"type": "partition", "set_a": [0], "set_b": [1, 2, 3, 4], "time": 200, "heal_after": 250},
                {"type": "crash", "target": 0, "time": 250, "recover_after": 50},
            ]},
        },
    },
]


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/app/traces.db"
    init_db(db_path)

    print(f"Generating {len(CONFIGS)} simulation runs...")
    for i, entry in enumerate(CONFIGS):
        cfg = entry["config"]
        seed = entry["seed"]
        label = entry["label"]
        sim = Simulator(cfg, seed)
        sim.run()
        rid = sim.save_to_db(db_path)
        n_ops = len(sim.ops_log)
        n_ev = len(sim.events_log)
        print(f"  run {rid} ({label}): seed={seed}, {n_ops} ops, {n_ev} events")

    # Save config metadata (labels + configs) for reference
    meta = []
    for i, entry in enumerate(CONFIGS):
        meta.append({
            "run_id": i + 1,
            "label": entry["label"],
            "seed": entry["seed"],
        })
    meta_path = os.path.join(os.path.dirname(db_path), "run_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Done. Database: {db_path}, Metadata: {meta_path}")


if __name__ == "__main__":
    main()
