#!/usr/bin/env python3
"""Pytest tests: verify agent's inferred parameters against ground truth.
Checks both JSON output files and SQLite results table."""

import json
import os
import sqlite3
import pytest

REPLAYS = 3
DB_PATH = "/app/replays.db"

HIDDEN_KEYS = [
    "nebula_tile_drift_speed",
    "nebula_tile_energy_reduction",
    "nebula_tile_vision_reduction",
    "unit_sap_dropoff_factor",
    "unit_energy_void_factor",
    "energy_node_drift_speed",
    "energy_node_drift_magnitude",
]

FLOAT_PARAMS = {
    "nebula_tile_drift_speed",
    "unit_sap_dropoff_factor",
    "unit_energy_void_factor",
    "energy_node_drift_speed",
}

INT_PARAMS = {
    "nebula_tile_energy_reduction",
    "nebula_tile_vision_reduction",
    "energy_node_drift_magnitude",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def check_param(key, expected, actual, source_label, replay_id):
    if key in FLOAT_PARAMS:
        assert abs(float(actual) - float(expected)) < 1e-4, (
            f"{source_label} replay_{replay_id}: {key} expected {expected}, got {actual}"
        )
    else:
        assert int(actual) == int(expected), (
            f"{source_label} replay_{replay_id}: {key} expected {expected}, got {actual}"
        )


@pytest.fixture(params=range(REPLAYS))
def replay_id(request):
    return request.param


def test_json_results(replay_id):
    """Check that JSON result files exist and contain correct inferred parameters."""
    gt_path = f"/tests/ground_truth/replay_{replay_id}.json"
    result_path = f"/app/results/replay_{replay_id}.json"

    assert os.path.exists(gt_path), f"Ground truth not found: {gt_path}"
    assert os.path.exists(result_path), (
        f"JSON result not found: {result_path}. "
        f"Did infer_params.py run and call replay-tool submit?"
    )

    gt = load_json(gt_path)
    result = load_json(result_path)

    for key in HIDDEN_KEYS:
        assert key in result, f"Missing key '{key}' in JSON results for replay_{replay_id}"
        check_param(key, gt[key], result[key], "JSON", replay_id)


def test_sqlite_results(replay_id):
    """Check that SQLite results table contains correct inferred parameters."""
    gt_path = f"/tests/ground_truth/replay_{replay_id}.json"
    assert os.path.exists(gt_path), f"Ground truth not found: {gt_path}"
    gt = load_json(gt_path)

    assert os.path.exists(DB_PATH), f"Database not found: {DB_PATH}"
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        "SELECT param_name, param_value FROM results WHERE replay_id = ?",
        (replay_id,),
    ).fetchall()
    db.close()

    result = {name: val for name, val in rows}

    assert len(result) >= len(HIDDEN_KEYS), (
        f"Incomplete SQLite results for replay_{replay_id}: "
        f"got {len(result)}/{len(HIDDEN_KEYS)} parameters. "
        f"Did you use replay-tool submit?"
    )

    for key in HIDDEN_KEYS:
        assert key in result, (
            f"Missing key '{key}' in SQLite results for replay_{replay_id}"
        )
        check_param(key, gt[key], result[key], "SQLite", replay_id)
