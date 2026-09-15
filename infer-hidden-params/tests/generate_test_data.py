#!/usr/bin/env python3
"""Generate test replays with known hidden parameters and store in SQLite database."""

import sys
import os
import gzip
import json
import sqlite3

sys.path.insert(0, "/tests")
from simulator import generate_replay

DB_PATH = "/app/replays.db"

TEST_CONFIGS = [
    {
        "seed": 42,
        "params": {
            "unit_move_cost": 3,
            "unit_sap_cost": 40,
            "unit_sap_range": 5,
            "unit_sensor_range": 2,
            "nebula_tile_drift_speed": -0.1,
            "nebula_tile_energy_reduction": 2,
            "nebula_tile_vision_reduction": 3,
            "unit_sap_dropoff_factor": 0.5,
            "unit_energy_void_factor": 0.125,
            "energy_node_drift_speed": 0.03,
            "energy_node_drift_magnitude": 4,
            "spawn_rate": 3,
            "init_unit_energy": 100,
        },
    },
    {
        "seed": 137,
        "params": {
            "unit_move_cost": 2,
            "unit_sap_cost": 35,
            "unit_sap_range": 4,
            "unit_sensor_range": 3,
            "nebula_tile_drift_speed": 0.05,
            "nebula_tile_energy_reduction": 5,
            "nebula_tile_vision_reduction": 1,
            "unit_sap_dropoff_factor": 0.25,
            "unit_energy_void_factor": 0.25,
            "energy_node_drift_speed": 0.01,
            "energy_node_drift_magnitude": 3,
            "spawn_rate": 3,
            "init_unit_energy": 100,
        },
    },
    {
        "seed": 7,
        "params": {
            "unit_move_cost": 4,
            "unit_sap_cost": 45,
            "unit_sap_range": 6,
            "unit_sensor_range": 1,
            "nebula_tile_drift_speed": -0.025,
            "nebula_tile_energy_reduction": 0,
            "nebula_tile_vision_reduction": 5,
            "unit_sap_dropoff_factor": 1.0,
            "unit_energy_void_factor": 0.0625,
            "energy_node_drift_speed": 0.05,
            "energy_node_drift_magnitude": 5,
            "spawn_rate": 3,
            "init_unit_energy": 100,
        },
    },
]

HIDDEN_KEYS = [
    "nebula_tile_drift_speed",
    "nebula_tile_energy_reduction",
    "nebula_tile_vision_reduction",
    "unit_sap_dropoff_factor",
    "unit_energy_void_factor",
    "energy_node_drift_speed",
    "energy_node_drift_magnitude",
]


def compress_json(obj):
    return gzip.compress(json.dumps(obj).encode("utf-8"))


def main():
    os.makedirs("/tests/ground_truth", exist_ok=True)

    db = sqlite3.connect(DB_PATH)

    for i, cfg in enumerate(TEST_CONFIGS):
        print(f"Generating replay {i}...")
        replay = generate_replay(cfg["seed"], cfg["params"], n_steps=200)

        # Insert replay record
        db.execute(
            "INSERT INTO replays (id, num_steps, description) VALUES (?, ?, ?)",
            (i, 200, f"test_replay_{i}"),
        )

        # Insert states as gzip-compressed JSON blobs
        for step_idx, state in enumerate(replay["states"]):
            db.execute(
                "INSERT INTO states (replay_id, step_idx, data) VALUES (?, ?, ?)",
                (i, step_idx, compress_json(state)),
            )

        # Insert actions as gzip-compressed JSON blobs
        for step_idx, action in enumerate(replay["actions"]):
            db.execute(
                "INSERT INTO actions (replay_id, step_idx, data) VALUES (?, ?, ?)",
                (i, step_idx, compress_json(action)),
            )

        # Insert known params (observable only, NOT hidden)
        known = replay["known_params"]
        for name, val in known.items():
            db.execute(
                "INSERT INTO known_params (replay_id, param_name, param_value) VALUES (?, ?, ?)",
                (i, name, float(val)),
            )

        # Save ground truth (hidden params only) to filesystem for test verification
        gt = {k: cfg["params"][k] for k in HIDDEN_KEYS}
        gt_path = f"/tests/ground_truth/replay_{i}.json"
        with open(gt_path, "w") as f:
            json.dump(gt, f, indent=2)
        print(f"  Stored replay {i} in database, ground truth at {gt_path}")

    db.commit()
    db.close()
    print("Done generating test data.")


if __name__ == "__main__":
    main()
