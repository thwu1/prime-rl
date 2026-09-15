#!/usr/bin/env python3
"""Generate energy field observation data for the inference task."""
import numpy as np
import json
import os

MAP_W = 24
MAP_H = 24
MAX_NODES = 6
MIN_E = -20
MAX_E = 20


def compute_energy_field(node_positions, node_fn_specs, node_masks):
    """Compute energy field matching the Lux AI S3 engine exactly.

    Parameters
    ----------
    node_positions : list of [x, y] for each of the 6 node slots
    node_fn_specs  : list of [fn_type, x, y, z] for each slot
    node_masks     : list of bool for each slot
    """
    # Build coordinate grid: mm[a, b] = [a, b], shape (W, H, 2)
    X, Y = np.meshgrid(np.arange(MAP_W), np.arange(MAP_H))
    mm = np.stack([X, Y]).T.astype(np.float64)  # (W, H, 2)

    contributions = np.zeros((MAX_NODES, MAP_W, MAP_H), dtype=np.float64)

    for n in range(MAX_NODES):
        if not node_masks[n]:
            continue
        pos = np.array(node_positions[n], dtype=np.float64)
        diff = mm - pos
        dist = np.sqrt(diff[..., 0] ** 2 + diff[..., 1] ** 2)

        fn_type = int(node_fn_specs[n][0])
        x = float(node_fn_specs[n][1])
        y = float(node_fn_specs[n][2])
        z = float(node_fn_specs[n][3])

        if fn_type == 0:
            contributions[n] = np.sin(dist * x + y) * z
        else:
            contributions[n] = (x / (dist + 1) + y) * z

    # Mean adjustment (matches engine)
    mean_val = contributions.mean()
    if mean_val < 0.25:
        contributions = contributions + (0.25 - mean_val)

    # Sum, round, clip
    field = np.round(contributions.sum(axis=0)).astype(int)
    field = np.clip(field, MIN_E, MAX_E)
    return field


def generate_observations(field, obs_fraction, seed):
    """Sample a random subset of tiles as observations."""
    rng = np.random.RandomState(seed)
    total = MAP_W * MAP_H
    n_obs = int(total * obs_fraction)

    indices = np.arange(total)
    rng.shuffle(indices)
    observed = sorted(indices[:n_obs].tolist())

    obs = []
    for idx in observed:
        x = idx // MAP_H
        y = idx % MAP_H
        obs.append({"x": int(x), "y": int(y), "energy": int(field[x, y])})
    return obs


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------
# Mirror rule: primary (a, b) -> mirror (23-b, 23-a)
# Paired nodes share identical fn_specs.

SCENARIOS = [
    {
        "id": 1,
        "node_positions": [[5, 7], [0, 0], [0, 0],
                           [16, 18], [0, 0], [0, 0]],
        "node_fn_specs": [[0, 1.0, 0.5, 3.0], [0, 0, 0, 0], [0, 0, 0, 0],
                          [0, 1.0, 0.5, 3.0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "node_masks": [True, False, False, True, False, False],
        "obs_fraction": 0.80,
        "obs_seed": 101,
        "num_active_pairs": 1,
    },
    {
        "id": 2,
        "node_positions": [[3, 8], [10, 2], [0, 0],
                           [15, 20], [21, 13], [0, 0]],
        "node_fn_specs": [[0, 0.8, 1.2, 5.0], [1, 3.0, 0.5, 4.0], [0, 0, 0, 0],
                          [0, 0.8, 1.2, 5.0], [1, 3.0, 0.5, 4.0], [0, 0, 0, 0]],
        "node_masks": [True, True, False, True, True, False],
        "obs_fraction": 0.55,
        "obs_seed": 202,
        "num_active_pairs": 2,
    },
    {
        "id": 3,
        "node_positions": [[7, 3], [2, 14], [0, 0],
                           [20, 16], [9, 21], [0, 0]],
        "node_fn_specs": [[0, 1.5, 0.0, 6.0], [1, 5.0, -0.3, 3.0], [0, 0, 0, 0],
                          [0, 1.5, 0.0, 6.0], [1, 5.0, -0.3, 3.0], [0, 0, 0, 0]],
        "node_masks": [True, True, False, True, True, False],
        "obs_fraction": 0.40,
        "obs_seed": 303,
        "num_active_pairs": 2,
    },
    {
        "id": 4,
        "node_positions": [[4, 4], [2, 11], [9, 1],
                           [19, 19], [12, 21], [22, 14]],
        "node_fn_specs": [[0, 1.2, 1.0, 4.0], [1, 4.0, 0.2, 5.0], [0, 0.6, 2.0, 3.5],
                          [0, 1.2, 1.0, 4.0], [1, 4.0, 0.2, 5.0], [0, 0.6, 2.0, 3.5]],
        "node_masks": [True, True, True, True, True, True],
        "obs_fraction": 0.35,
        "obs_seed": 404,
        "num_active_pairs": 3,
    },
    {
        "id": 5,
        "node_positions": [[6, 5], [8, 10], [3, 16],
                           [18, 17], [13, 15], [7, 20]],
        "node_fn_specs": [[0, 1.3, 0.8, 7.0], [1, 2.5, 0.1, 6.0], [0, 0.9, 1.5, 4.5],
                          [0, 1.3, 0.8, 7.0], [1, 2.5, 0.1, 6.0], [0, 0.9, 1.5, 4.5]],
        "node_masks": [True, True, True, True, True, True],
        "obs_fraction": 0.30,
        "obs_seed": 505,
        "num_active_pairs": 3,
    },
]


def main():
    os.makedirs("/app/data", exist_ok=True)

    for s in SCENARIOS:
        field = compute_energy_field(
            s["node_positions"], s["node_fn_specs"], s["node_masks"]
        )
        obs = generate_observations(field, s["obs_fraction"], s["obs_seed"])

        data = {
            "scenario_id": s["id"],
            "map_width": MAP_W,
            "map_height": MAP_H,
            "num_active_node_pairs": s["num_active_pairs"],
            "observations": obs,
        }

        path = f"/app/data/scenario_{s['id']}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Scenario {s['id']}: {len(obs)} observations, "
              f"field range [{field.min()}, {field.max()}]")

    print("Data generation complete.")


if __name__ == "__main__":
    main()
