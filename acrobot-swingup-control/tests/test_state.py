
"""
Tests for acrobot swing-up controller.

Runs a deterministic 10-second simulation and verifies swing-up success
and stabilization quality.
"""
import sys
import numpy as np
import pytest

sys.path.insert(0, "/app")

from plant import DoublePendulumPlant
from simulator import Simulator
from config import PARAMS, SIM_CONFIG
from my_controller import MyController


@pytest.fixture(scope="module")
def sim_result():
    """Run the simulation once and share the result across tests."""
    plant = DoublePendulumPlant(**PARAMS)
    controller = MyController(plant)
    sim = Simulator(plant)
    T, X, U = sim.simulate(
        controller,
        SIM_CONFIG["x0"],
        SIM_CONFIG["dt"],
        SIM_CONFIG["t_final"],
    )
    return {"plant": plant, "T": T, "X": X, "U": U}


# ── basic interface tests ─────────────────────────────────────────────

def test_controller_importable():
    """Controller class can be instantiated."""
    plant = DoublePendulumPlant(**PARAMS)
    controller = MyController(plant)
    assert hasattr(controller, "get_control_output")


def test_controller_output_valid():
    """get_control_output returns a finite 2-element array."""
    plant = DoublePendulumPlant(**PARAMS)
    controller = MyController(plant)

    for x_test in [
        [0.0, 0.0, 0.0, 0.0],
        [np.pi, 0.0, 0.0, 0.0],
        [1.5, 0.3, 2.0, -1.0],
        [np.pi + 0.1, -0.2, 0.5, -0.5],
    ]:
        u = np.asarray(
            controller.get_control_output(np.array(x_test), 1.0), dtype=float
        )
        assert u.shape == (2,), f"Expected shape (2,), got {u.shape}"
        assert np.all(np.isfinite(u)), f"Non-finite output {u} for state {x_test}"


# ── simulation quality tests ──────────────────────────────────────────

def test_simulation_completes_without_divergence(sim_result):
    """Simulation must finish with all states and controls finite."""
    X = sim_result["X"]
    U = sim_result["U"]
    assert np.all(np.isfinite(X)), "State trajectory contains NaN or Inf"
    assert np.all(np.isfinite(U)), "Control trajectory contains NaN or Inf"
    # Sanity: velocities should stay physically reasonable
    assert np.all(np.abs(X[:, 2:]) < 100.0), (
        "Joint velocities exceed 100 rad/s — simulation likely unstable"
    )


def test_swingup_success(sim_result):
    """End-effector must be above threshold at the final timestep."""
    plant = sim_result["plant"]
    X = sim_result["X"]
    threshold = SIM_CONFIG["threshold_height"]

    _, ee_y_final = plant.forward_kinematics(X[-1, :2])
    assert ee_y_final >= threshold, (
        f"End-effector height {ee_y_final:.4f} m < threshold {threshold} m "
        f"at t = {SIM_CONFIG['t_final']} s"
    )


def test_stabilization_last_2_seconds(sim_result):
    """End-effector must stay above threshold for the final 2 seconds."""
    plant = sim_result["plant"]
    T = sim_result["T"]
    X = sim_result["X"]
    threshold = SIM_CONFIG["threshold_height"]
    dt = SIM_CONFIG["dt"]

    t_check_start = SIM_CONFIG["t_final"] - 2.0
    n_start = int(round(t_check_start / dt))

    min_height = float("inf")
    min_time = 0.0
    for i in range(n_start, len(X)):
        _, ee_y = plant.forward_kinematics(X[i, :2])
        if ee_y < min_height:
            min_height = ee_y
            min_time = T[i]

    assert min_height >= threshold, (
        f"End-effector dropped to {min_height:.4f} m at t = {min_time:.3f} s "
        f"(must stay >= {threshold} m for t in [{t_check_start}, {SIM_CONFIG['t_final']}])"
    )
