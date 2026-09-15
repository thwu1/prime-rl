
import json
import os

import numpy as np
import pytest

RESULTS_PATH = "/app/results.json"

EXPECTED_SCENARIOS = [
    "translation_step",
    "attitude_step",
    "convergence_translation",
    "convergence_attitude",
    "convergence_combined",
    "idle_mode",
]


def _quat_error_angle(q, q_target):
    """Compute the rotation angle (radians) between two quaternions in [x,y,z,w] format."""
    q = np.array(q, dtype=float)
    q_target = np.array(q_target, dtype=float)
    # q_err = q* (conjugate) * q_target
    qc = np.array([-q[0], -q[1], -q[2], q[3]])
    x1, y1, z1, w1 = qc
    x2, y2, z2, w2 = q_target
    q_e = np.array(
        [
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        ]
    )
    if q_e[3] < 0:
        q_e = -q_e
    return 2 * np.arccos(np.clip(q_e[3], -1.0, 1.0))


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    return data


# -- Structural checks --


def test_results_file_exists():
    assert os.path.exists(RESULTS_PATH), "results.json was not created"


def test_all_scenarios_present(results):
    for name in EXPECTED_SCENARIOS:
        assert name in results, f"Missing scenario result: {name}"


def test_result_fields(results):
    required = [
        "final_position",
        "final_velocity",
        "final_quaternion",
        "final_omega",
        "step_1_force",
        "step_1_torque",
    ]
    for name in EXPECTED_SCENARIOS:
        for field in required:
            assert field in results[name], f"{name} missing field '{field}'"


# -- Single-step analytical checks --


def test_translation_step_force_x(results):
    """Pure translation: first-step body force should be ~5.75 N in X."""
    force = np.array(results["translation_step"]["step_1_force"])
    assert abs(force[0] - 5.75) < 0.1, f"force_x={force[0]}, expected ~5.75"


def test_translation_step_force_yz(results):
    """Pure X translation: Y and Z force components should be zero."""
    force = np.array(results["translation_step"]["step_1_force"])
    assert abs(force[1]) < 0.01, f"force_y={force[1]}, expected 0"
    assert abs(force[2]) < 0.01, f"force_z={force[2]}, expected 0"


def test_translation_step_torque_zero(results):
    """Pure translation with identity quaternion: torque should be near zero."""
    torque = np.array(results["translation_step"]["step_1_torque"])
    assert np.linalg.norm(torque) < 0.01, f"torque={torque}, expected ~0"


def test_attitude_step_force_zero(results):
    """Pure attitude error at origin: force should be zero."""
    force = np.array(results["attitude_step"]["step_1_force"])
    assert np.linalg.norm(force) < 0.01, f"force={force}, expected 0"


def test_attitude_step_torque_z(results):
    """45-deg Z-axis attitude error: torque_z should be ~0.124 Nm."""
    torque = np.array(results["attitude_step"]["step_1_torque"])
    assert abs(torque[2] - 0.1242) < 0.01, f"torque_z={torque[2]}, expected ~0.1242"


def test_attitude_step_torque_xy(results):
    """45-deg Z-axis rotation: X and Y torque should be zero."""
    torque = np.array(results["attitude_step"]["step_1_torque"])
    assert abs(torque[0]) < 0.005, f"torque_x={torque[0]}, expected 0"
    assert abs(torque[1]) < 0.005, f"torque_y={torque[1]}, expected 0"


# -- Convergence checks --


def test_convergence_translation_position(results):
    """After 1500 steps (24s), position error < 0.02 m."""
    pos = np.array(results["convergence_translation"]["final_position"])
    err = np.linalg.norm(pos - np.array([1.0, 0.0, 0.0]))
    assert err < 0.02, f"Position error {err:.4f} m exceeds 0.02 m"


def test_convergence_translation_velocity(results):
    """After 1500 steps, velocity magnitude < 0.01 m/s."""
    vel = np.array(results["convergence_translation"]["final_velocity"])
    assert np.linalg.norm(vel) < 0.01, f"Speed {np.linalg.norm(vel):.4f} m/s exceeds 0.01"


def test_convergence_attitude_quaternion(results):
    """After 1500 steps, attitude error < 0.05 rad (~2.9 deg)."""
    q = results["convergence_attitude"]["final_quaternion"]
    q_target = [0.0, 0.0, 0.3826834323650898, 0.9238795325112867]
    err = _quat_error_angle(q, q_target)
    assert err < 0.05, f"Attitude error {np.degrees(err):.2f} deg exceeds 2.9 deg"


def test_convergence_attitude_omega(results):
    """After 1500 steps, angular velocity < 0.01 rad/s."""
    omega = np.array(results["convergence_attitude"]["final_omega"])
    assert np.linalg.norm(omega) < 0.01, f"Angular vel {np.linalg.norm(omega):.4f} rad/s exceeds 0.01"


def test_convergence_combined_position(results):
    """Combined scenario: position converges within 0.02 m."""
    pos = np.array(results["convergence_combined"]["final_position"])
    target = np.array([0.5, 0.3, -0.2])
    err = np.linalg.norm(pos - target)
    assert err < 0.02, f"Position error {err:.4f} m exceeds 0.02 m"


def test_convergence_combined_attitude(results):
    """Combined scenario: attitude converges within 0.05 rad."""
    q = results["convergence_combined"]["final_quaternion"]
    q_target = [0.0, 0.0, 0.5, 0.8660254037844387]
    err = _quat_error_angle(q, q_target)
    assert err < 0.05, f"Attitude error {np.degrees(err):.2f} deg exceeds threshold"


def test_convergence_combined_velocity(results):
    """Combined scenario: velocity settled."""
    vel = np.array(results["convergence_combined"]["final_velocity"])
    assert np.linalg.norm(vel) < 0.01, f"Velocity not settled: {vel}"


def test_convergence_combined_omega(results):
    """Combined scenario: angular velocity settled."""
    omega = np.array(results["convergence_combined"]["final_omega"])
    assert np.linalg.norm(omega) < 0.01, f"Angular velocity not settled: {omega}"


# -- Combined first-step physical consistency --


def test_combined_step_force_direction(results):
    """First-step force direction should align with position error (identity quat)."""
    force = np.array(results["convergence_combined"]["step_1_force"])
    target_dir = np.array([0.5, 0.3, -0.2])
    target_dir = target_dir / np.linalg.norm(target_dir)
    force_dir = force / np.linalg.norm(force)
    dot = np.dot(force_dir, target_dir)
    assert dot > 0.95, f"Force-target dot product {dot:.4f} < 0.95"


def test_combined_step_torque_z(results):
    """60-deg Z rotation: torque_z should be ~0.162 Nm."""
    torque = np.array(results["convergence_combined"]["step_1_torque"])
    assert abs(torque[2] - 0.1623) < 0.015, f"torque_z={torque[2]}, expected ~0.1623"


# -- Idle mode checks --


def test_idle_mode_zero_force(results):
    """Idle mode (confidence=0): force must be zero."""
    force = np.array(results["idle_mode"]["step_1_force"])
    assert np.linalg.norm(force) < 1e-10, f"Force in idle mode: {force}"


def test_idle_mode_zero_torque(results):
    """Idle mode (confidence=0): torque must be zero."""
    torque = np.array(results["idle_mode"]["step_1_torque"])
    assert np.linalg.norm(torque) < 1e-10, f"Torque in idle mode: {torque}"


def test_idle_mode_no_motion(results):
    """Idle mode: robot should not move from origin."""
    pos = np.array(results["idle_mode"]["final_position"])
    assert np.linalg.norm(pos) < 1e-10, f"Motion in idle mode: pos={pos}"
