
"""Verify reconstructed energy fields against ground truth."""

import json
import math
import os

import numpy as np
import pytest

MAP_W = 24
MAP_H = 24
MAX_NODES = 6
MIN_ENERGY = -20
MAX_ENERGY = 20


# ---------------------------------------------------------------------------
# Forward model — identical to the Lux AI S3 engine energy field computation
# ---------------------------------------------------------------------------

def _compute_ground_truth(node_positions, node_fn_specs, node_masks):
    """Reproduce the exact engine energy field from node parameters."""
    X, Y = np.meshgrid(np.arange(MAP_W), np.arange(MAP_H))
    mm = np.stack([X, Y]).T.astype(np.float64)  # shape (W, H, 2)

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

    mean_val = contributions.mean()
    if mean_val < 0.25:
        contributions += 0.25 - mean_val

    field = np.round(contributions.sum(axis=0)).astype(int)
    return np.clip(field, MIN_ENERGY, MAX_ENERGY)


# ---------------------------------------------------------------------------
# Ground-truth scenario parameters (same as data generator)
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "id": 1,
        "node_positions": [[5, 7], [0, 0], [0, 0],
                           [16, 18], [0, 0], [0, 0]],
        "node_fn_specs": [[0, 1.0, 0.5, 3.0], [0, 0, 0, 0], [0, 0, 0, 0],
                          [0, 1.0, 0.5, 3.0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "node_masks": [True, False, False, True, False, False],
    },
    {
        "id": 2,
        "node_positions": [[3, 8], [10, 2], [0, 0],
                           [15, 20], [21, 13], [0, 0]],
        "node_fn_specs": [[0, 0.8, 1.2, 5.0], [1, 3.0, 0.5, 4.0], [0, 0, 0, 0],
                          [0, 0.8, 1.2, 5.0], [1, 3.0, 0.5, 4.0], [0, 0, 0, 0]],
        "node_masks": [True, True, False, True, True, False],
    },
    {
        "id": 3,
        "node_positions": [[7, 3], [2, 14], [0, 0],
                           [20, 16], [9, 21], [0, 0]],
        "node_fn_specs": [[0, 1.5, 0.0, 6.0], [1, 5.0, -0.3, 3.0], [0, 0, 0, 0],
                          [0, 1.5, 0.0, 6.0], [1, 5.0, -0.3, 3.0], [0, 0, 0, 0]],
        "node_masks": [True, True, False, True, True, False],
    },
    {
        "id": 4,
        "node_positions": [[4, 4], [2, 11], [9, 1],
                           [19, 19], [12, 21], [22, 14]],
        "node_fn_specs": [[0, 1.2, 1.0, 4.0], [1, 4.0, 0.2, 5.0], [0, 0.6, 2.0, 3.5],
                          [0, 1.2, 1.0, 4.0], [1, 4.0, 0.2, 5.0], [0, 0.6, 2.0, 3.5]],
        "node_masks": [True, True, True, True, True, True],
    },
    {
        "id": 5,
        "node_positions": [[6, 5], [8, 10], [3, 16],
                           [18, 17], [13, 15], [7, 20]],
        "node_fn_specs": [[0, 1.3, 0.8, 7.0], [1, 2.5, 0.1, 6.0], [0, 0.9, 1.5, 4.5],
                          [0, 1.3, 0.8, 7.0], [1, 2.5, 0.1, 6.0], [0, 0.9, 1.5, 4.5]],
        "node_masks": [True, True, True, True, True, True],
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "scenario",
    SCENARIOS,
    ids=[f"scenario_{s['id']}" for s in SCENARIOS],
)
def test_energy_field_reconstruction(scenario):
    sid = scenario["id"]
    result_path = f"/app/results/scenario_{sid}.json"

    assert os.path.exists(result_path), f"Result file {result_path} not found"

    with open(result_path) as f:
        result = json.load(f)

    assert "energy_field" in result, "Result must contain 'energy_field' key"

    predicted = np.array(result["energy_field"], dtype=np.float64)
    assert predicted.shape == (MAP_W, MAP_H), (
        f"energy_field must be {MAP_W}x{MAP_H}, got {predicted.shape}"
    )

    # All values must be in valid range
    assert np.all(predicted >= MIN_ENERGY), "Energy values below -20"
    assert np.all(predicted <= MAX_ENERGY), "Energy values above 20"

    # Compute ground truth
    ground_truth = _compute_ground_truth(
        scenario["node_positions"],
        scenario["node_fn_specs"],
        scenario["node_masks"],
    ).astype(np.float64)

    # RMSE check
    rmse = np.sqrt(np.mean((predicted - ground_truth) ** 2))
    assert rmse < 2.0, (
        f"Scenario {sid}: RMSE = {rmse:.4f} exceeds threshold 2.0"
    )
