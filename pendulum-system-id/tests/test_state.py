
import json
import math
import os
import sys
import hashlib

sys.path.insert(0, '/app')
from simulator import simulate, load_config

# SHA-256 fingerprint of the ground truth physical parameters.
# Computed over "m2={m2:.2f},l1={l1:.2f},l2={l2:.2f},b1={b1:.3f},b2={b2:.3f}"
# using the true values. Enables exact-match verification without
# exposing parameter values in plaintext.
_PARAM_FINGERPRINT = "4ffa69cb6bc2ec0c718c2e862399da3b50cec2360407f01815fc1c12d88a3fb7"


def _load_estimated():
    path = '/app/estimated_params.json'
    assert os.path.exists(path), f"{path} not found"
    with open(path) as f:
        params = json.load(f)
    return params


def _load_validation():
    """Load validation trajectories and their initial conditions."""
    with open('/tests/validation_ics.json') as f:
        ics = json.load(f)
    trajs = []
    for i in range(1, len(ics) + 1):
        with open(f'/tests/validation_traj_{i}.json') as f:
            trajs.append(json.load(f))
    return ics, trajs


def _trajectory_rmse(simulated, observed):
    """Compute RMSE between simulated and observed joint position trajectories."""
    n = len(observed)
    assert len(simulated) == n, f"Length mismatch: {len(simulated)} vs {n}"
    sq_err = 0.0
    for i in range(n):
        dq1 = simulated[i][0] - observed[i][0]
        dq2 = simulated[i][1] - observed[i][1]
        sq_err += dq1 * dq1 + dq2 * dq2
    return math.sqrt(sq_err / (2 * n))


def test_output_format():
    """Estimated parameters file exists with all required keys and valid values."""
    params = _load_estimated()
    required = ["m2", "l1", "l2", "b1", "b2", "qd1_0", "qd2_0"]
    for key in required:
        assert key in params, f"Missing key: {key}"
        val = params[key]
        assert isinstance(val, (int, float)), f"{key} must be numeric, got {type(val)}"
        assert math.isfinite(val), f"{key} must be finite, got {val}"
    for key in ["m2", "l1", "l2", "b1", "b2"]:
        assert params[key] > 0, f"{key} must be positive, got {params[key]}"


def test_physical_plausibility():
    """Estimated physical parameters are within physically reasonable ranges."""
    est = _load_estimated()
    assert 0.05 < est["m2"] < 10.0, f"m2={est['m2']} outside plausible range"
    for key in ["l1", "l2"]:
        assert 0.05 < est[key] < 5.0, f"{key}={est[key]} outside plausible range"
    for key in ["b1", "b2"]:
        assert 0.0001 < est[key] < 5.0, f"{key}={est[key]} outside plausible range"
    for key in ["qd1_0", "qd2_0"]:
        assert -20.0 < est[key] < 20.0, f"{key}={est[key]} outside plausible range"


def test_primary_trajectory():
    """Simulation with estimated parameters reproduces the observed trajectory."""
    est = _load_estimated()
    config = load_config('/app/data/config.json')

    with open('/app/data/trajectory.json') as f:
        observed = json.load(f)

    m1 = config["m1"]
    simulated = simulate(
        config["q1_0"], config["q2_0"],
        est["qd1_0"], est["qd2_0"],
        m1, est["m2"],
        est["l1"], est["l2"],
        est["b1"], est["b2"],
        config["g"], config["dt"], config["n_steps"]
    )
    sim_pos = [[s[0], s[1]] for s in simulated]

    rmse = _trajectory_rmse(sim_pos, observed)
    assert rmse < 0.05, (
        f"Primary trajectory RMSE = {rmse:.6f} exceeds threshold 0.05 rad"
    )


def test_validation_trajectory_1():
    """Estimated physical parameters generalize to validation trajectory 1.

    Uses a different set of initial conditions (with known velocities)
    to verify physical parameters are correct and not a spurious fit.
    """
    est = _load_estimated()
    config = load_config('/app/data/config.json')
    ics, trajs = _load_validation()

    ic = ics[0]
    observed = trajs[0]
    m1 = config["m1"]

    simulated = simulate(
        ic["q1_0"], ic["q2_0"],
        ic["qd1_0"], ic["qd2_0"],
        m1, est["m2"],
        est["l1"], est["l2"],
        est["b1"], est["b2"],
        config["g"], config["dt"], config["n_steps"]
    )
    sim_pos = [[s[0], s[1]] for s in simulated]

    rmse = _trajectory_rmse(sim_pos, observed)
    assert rmse < 0.05, (
        f"Validation trajectory 1 RMSE = {rmse:.6f} exceeds threshold 0.05 rad. "
        f"Physical parameters do not generalize to IC: {ic}"
    )


def test_validation_trajectory_2():
    """Estimated physical parameters generalize to validation trajectory 2."""
    est = _load_estimated()
    config = load_config('/app/data/config.json')
    ics, trajs = _load_validation()

    ic = ics[1]
    observed = trajs[1]
    m1 = config["m1"]

    simulated = simulate(
        ic["q1_0"], ic["q2_0"],
        ic["qd1_0"], ic["qd2_0"],
        m1, est["m2"],
        est["l1"], est["l2"],
        est["b1"], est["b2"],
        config["g"], config["dt"], config["n_steps"]
    )
    sim_pos = [[s[0], s[1]] for s in simulated]

    rmse = _trajectory_rmse(sim_pos, observed)
    assert rmse < 0.05, (
        f"Validation trajectory 2 RMSE = {rmse:.6f} exceeds threshold 0.05 rad. "
        f"Physical parameters do not generalize to IC: {ic}"
    )


def test_parameter_fingerprint():
    """Estimated physical parameters match the ground truth fingerprint.

    Verifies that the estimated parameters, when rounded to the precision
    used for fingerprinting, produce the correct SHA-256 hash. This ensures
    quantitative accuracy without revealing exact values in the test code.
    """
    est = _load_estimated()
    param_str = (
        f"m2={est['m2']:.2f},"
        f"l1={est['l1']:.2f},"
        f"l2={est['l2']:.2f},"
        f"b1={est['b1']:.3f},"
        f"b2={est['b2']:.3f}"
    )
    computed_hash = hashlib.sha256(param_str.encode()).hexdigest()
    assert computed_hash == _PARAM_FINGERPRINT, (
        f"Parameter fingerprint mismatch. Estimated physical parameters "
        f"(rounded) do not match ground truth. "
        f"Got hash: {computed_hash}"
    )
