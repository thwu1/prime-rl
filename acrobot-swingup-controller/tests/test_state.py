"""Tests for acrobot swing-up controller.

"""

import sys
import math
import json

import pytest

sys.path.insert(0, '/app')

from plant import DoublePendulumPlant
from simulator import simulate
from scoring import compute_realai_score


@pytest.fixture(scope="module")
def params():
    with open('/app/params.json') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def plant(params):
    return DoublePendulumPlant(params)


@pytest.fixture(scope="module")
def trajectory(plant, params):
    from controller import AcrobotController
    ctrl = AcrobotController(plant, params)
    return simulate(plant, ctrl, params)


def test_controller_interface(plant, params):
    """Controller class must exist with the required interface."""
    from controller import AcrobotController
    ctrl = AcrobotController(plant, params)
    result = ctrl.get_control_output([0.0, 0.0, 0.0, 0.0], 0.0)
    assert isinstance(result, (int, float)), \
        "get_control_output must return a scalar number"


def test_trajectory_finite(trajectory):
    """All trajectory values must be finite (no NaN/Inf)."""
    for entry in trajectory:
        for val in entry:
            assert math.isfinite(val), f"Non-finite value in trajectory: {entry}"


def test_simulation_length(trajectory, params):
    """Simulation must run for the full duration."""
    expected = int(round(params['T'] / params['dt'])) + 1
    actual = len(trajectory)
    assert actual >= expected - 10, (
        f"Simulation ended early: {actual} steps (expected ~{expected})"
    )


def test_torque_limits(trajectory, params):
    """All applied torques must be within the allowed range."""
    tau_max = params['tau_max']
    for t, q1, q2, q1d, q2d, tau in trajectory:
        assert abs(tau) <= tau_max + 1e-6, (
            f"Torque {tau:.4f} exceeds limit {tau_max} at t={t:.4f}"
        )


def test_swingup_achieved(trajectory, params):
    """End-effector must reach height threshold and stay there."""
    l1 = params['l1']
    l2 = params['l2']
    h_thresh = params['ee_height_threshold']
    stab_time = params['stabilization_time']

    above_start = None
    success = False

    for t, q1, q2, q1d, q2d, tau in trajectory:
        y_ee = -l1 * math.cos(q1) - l2 * math.cos(q1 + q2)
        if y_ee >= h_thresh:
            if above_start is None:
                above_start = t
            if t - above_start >= stab_time:
                success = True
                break
        else:
            above_start = None

    assert success, (
        f"Swing-up failed: end-effector never stayed above {h_thresh}m "
        f"for {stab_time}s within the {params['T']}s simulation"
    )


def test_realai_score(trajectory, params):
    """RealAI Score must exceed the minimum threshold."""
    score, details = compute_realai_score(trajectory, params)
    min_score = params['min_realai_score']
    assert score >= min_score, (
        f"RealAI Score {score:.4f} < minimum {min_score}. Details: {details}"
    )
