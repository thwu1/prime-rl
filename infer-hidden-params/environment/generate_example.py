#!/usr/bin/env python3
"""Generate an example replay and store it in the SQLite database for format reference."""

import gzip
import json
import sqlite3

DB_PATH = "/app/replays.db"
W = H = 24
MAX_UNITS = 16


def compress_json(obj):
    return gzip.compress(json.dumps(obj).encode("utf-8"))


def make_state(steps=0, match_steps=0):
    """Create a minimal game state for format illustration."""
    positions = [[[0, 0] for _ in range(MAX_UNITS)] for _ in range(2)]
    energies = [[[0] for _ in range(MAX_UNITS)] for _ in range(2)]
    masks = [[False] * MAX_UNITS for _ in range(2)]

    positions[0][0] = [0, 0]
    energies[0][0] = [100]
    masks[0][0] = True

    positions[1][0] = [23, 23]
    energies[1][0] = [100]
    masks[1][0] = True

    tile_type = [[0] * W for _ in range(H)]
    for i in range(5, 10):
        for j in range(5, 10):
            tile_type[i][j] = 1

    energy_field = [[0] * W for _ in range(H)]
    energy_nodes = [[10, 5], [14, 19], [0, 0], [0, 0], [0, 0], [0, 0]]
    vision_power = [[[0] * W for _ in range(H)] for _ in range(2)]

    sr = 2
    for t, (ux, uy) in enumerate([(0, 0), (23, 23)]):
        for dx in range(-sr, sr + 1):
            for dy in range(-sr, sr + 1):
                nx, ny = ux + dx, uy + dy
                if 0 <= nx < W and 0 <= ny < H:
                    power = 1 + sr - max(abs(dx), abs(dy))
                    vision_power[t][nx][ny] += power
        vision_power[t][ux][uy] += 10

    return {
        "units": {"position": positions, "energy": energies},
        "units_mask": masks,
        "map_features": {"tile_type": tile_type, "energy": energy_field},
        "energy_nodes": energy_nodes,
        "vision_power_map": vision_power,
        "team_points": [0, 0],
        "team_wins": [0, 0],
        "steps": steps,
        "match_steps": match_steps,
    }


def main():
    db = sqlite3.connect(DB_PATH)

    state0 = make_state(0, 0)
    state1 = make_state(1, 1)
    state1["units"]["position"][0][0] = [1, 0]
    state1["units"]["energy"][0][0] = [98]

    action0 = {
        "player_0": [[2, 0, 0]] + [[0, 0, 0]] * (MAX_UNITS - 1),
        "player_1": [[0, 0, 0]] * MAX_UNITS,
    }

    # Insert example replay (ID 99)
    db.execute(
        "INSERT INTO replays (id, num_steps, description) VALUES (99, 1, 'example')"
    )

    # Insert states as gzip-compressed JSON blobs
    db.execute(
        "INSERT INTO states (replay_id, step_idx, data) VALUES (99, 0, ?)",
        (compress_json(state0),),
    )
    db.execute(
        "INSERT INTO states (replay_id, step_idx, data) VALUES (99, 1, ?)",
        (compress_json(state1),),
    )

    # Insert actions as gzip-compressed JSON blob
    db.execute(
        "INSERT INTO actions (replay_id, step_idx, data) VALUES (99, 0, ?)",
        (compress_json(action0),),
    )

    # Insert ALL params as known (including hidden ones, since this is the example)
    all_params = {
        "max_units": 16,
        "match_count_per_episode": 5,
        "max_steps_in_match": 100,
        "map_height": 24,
        "map_width": 24,
        "num_teams": 2,
        "unit_move_cost": 2,
        "unit_sap_cost": 40,
        "unit_sap_range": 5,
        "unit_sensor_range": 2,
        "nebula_tile_drift_speed": -0.05,
        "nebula_tile_energy_reduction": 1,
        "nebula_tile_vision_reduction": 2,
        "unit_sap_dropoff_factor": 0.5,
        "unit_energy_void_factor": 0.125,
        "energy_node_drift_speed": 0.02,
        "energy_node_drift_magnitude": 5,
    }
    for name, val in all_params.items():
        db.execute(
            "INSERT INTO known_params (replay_id, param_name, param_value) VALUES (99, ?, ?)",
            (name, float(val)),
        )

    db.commit()
    db.close()

    # Also write standalone JSON for easy viewing
    with open("/app/example_replay.json", "w") as f:
        json.dump(
            {
                "states": [state0, state1],
                "actions": [action0],
                "all_params": all_params,
                "note": "This is a format reference. Real replays are in the SQLite database at /app/replays.db.",
            },
            f,
            indent=2,
        )

    print("Example replay stored in database (ID 99) and /app/example_replay.json")


if __name__ == "__main__":
    main()
