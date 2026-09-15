"""
Verification tests for the 6-DOF robot arm kinematic calibration and analysis.
Uses independent reference FK implementations for both the nominal and true
(perturbed) kinematic models.
"""

import json
import math
import os
import numpy as np
import pytest


# ================================================================
# Rotation / transformation helpers
# ================================================================

def _rx(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(theta):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rpy_matrix(roll, pitch, yaw):
    return _rz(yaw) @ _ry(pitch) @ _rx(roll)


def _axis_rotation(axis, theta):
    ax = np.array(axis, dtype=float)
    n = np.linalg.norm(ax)
    if n < 1e-10:
        return np.eye(3)
    ax = ax / n
    c, s = np.cos(theta), np.sin(theta)
    t = 1.0 - c
    x, y, z = ax
    return np.array([
        [t * x * x + c, t * x * y - z * s, t * x * z + y * s],
        [t * x * y + z * s, t * y * y + c, t * y * z - x * s],
        [t * x * z - y * s, t * y * z + x * s, t * z * z + c],
    ])


# ================================================================
# Hardcoded kinematic chains
# ================================================================

# Nominal chain (matches robot.urdf exactly)
_CHAIN_NOMINAL = [
    {"xyz": [0, 0, 0.185], "rpy": [0, 0, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0.038, 0, 0], "rpy": [0, 1.5707963268, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [-0.378, 0, 0], "rpy": [0, 0, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [-0.327, 0, 0.1075], "rpy": [0, 1.5707963268, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0, -0.0922, 0], "rpy": [0, -1.5707963268, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0, 0.0922, 0], "rpy": [0, 0, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0, 0, 0.0825], "rpy": [0, 0, -0.7853981634],
     "axis": None, "type": "fixed"},
]

# True perturbed chain (the "physical robot" that generated calibration data)
_CHAIN_TRUE = [
    {"xyz": [0, 0, 0.185], "rpy": [0, 0, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0.041, 0.003, 0.001], "rpy": [0, 1.5707963268, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [-0.378, 0, 0], "rpy": [0, 0, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [-0.324, -0.002, 0.109], "rpy": [0, 1.5707963268, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0, -0.0922, 0], "rpy": [0.005, -1.5707963268, -0.003],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0, 0.0922, 0], "rpy": [0, 0, 0],
     "axis": [0, 0, 1], "type": "revolute"},
    {"xyz": [0, 0, 0.0825], "rpy": [0, 0, -0.7853981634],
     "axis": None, "type": "fixed"},
]

_JOINT_LIMITS = [
    (-2.967, 2.967), (-2.094, 2.094), (-2.618, 2.618),
    (-3.14159, 3.14159), (-2.094, 2.094), (-3.14159, 3.14159),
]

_VALIDATION_CONFIGS = [
    [0.3, -0.5, 0.7, 1.0, -0.3, 0.2],
    [-0.8, 0.4, -0.2, -0.5, 0.8, -0.4],
    [1.2, -0.7, 0.5, 0.3, -0.9, 1.1],
    [-0.5, 1.0, -1.0, 0.8, 0.5, -0.6],
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
]


# ================================================================
# Reference FK and Jacobian
# ================================================================

def ref_fk(chain, joint_angles):
    """Reference FK: compose transformations from a given chain."""
    T = np.eye(4)
    q_idx = 0
    for j in chain:
        R = _rpy_matrix(*j["rpy"])
        T_o = np.eye(4)
        T_o[:3, :3] = R
        T_o[:3, 3] = j["xyz"]
        T = T @ T_o
        if j["type"] == "revolute":
            R_j = _axis_rotation(j["axis"], joint_angles[q_idx])
            T_j = np.eye(4)
            T_j[:3, :3] = R_j
            T = T @ T_j
            q_idx += 1
    return T


def ref_jacobian(chain, joint_angles, delta=1e-7):
    """Reference numerical Jacobian via finite differences."""
    T0 = ref_fk(chain, joint_angles)
    p0 = T0[:3, 3].copy()
    R0 = T0[:3, :3].copy()
    n = len(joint_angles)
    J = np.zeros((6, n))
    for i in range(n):
        q_p = np.array(joint_angles, dtype=float)
        q_p[i] += delta
        T_p = ref_fk(chain, q_p)
        J[:3, i] = (T_p[:3, 3] - p0) / delta
        dR = T_p[:3, :3] @ R0.T
        J[3, i] = (dR[2, 1] - dR[1, 2]) / (2.0 * delta)
        J[4, i] = (dR[0, 2] - dR[2, 0]) / (2.0 * delta)
        J[5, i] = (dR[1, 0] - dR[0, 1]) / (2.0 * delta)
    return J


# ================================================================
# Fixture
# ================================================================

@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ================================================================
# Nominal Forward Kinematics Tests
# ================================================================

class TestNominalFK:

    def test_zero_config_position(self, results):
        fk = results["nominal_fk"]["zero_config"]
        T = ref_fk(_CHAIN_NOMINAL, [0, 0, 0, 0, 0, 0])
        np.testing.assert_allclose(fk["position"], T[:3, 3], atol=1e-4,
                                   err_msg="Nominal FK position at zero config mismatch")

    def test_zero_config_orientation(self, results):
        fk = results["nominal_fk"]["zero_config"]
        T = ref_fk(_CHAIN_NOMINAL, [0, 0, 0, 0, 0, 0])
        np.testing.assert_allclose(fk["orientation"], T[:3, :3], atol=1e-4,
                                   err_msg="Nominal FK orientation at zero config mismatch")

    def test_config_1_position(self, results):
        q = [0.5, -0.3, 0.8, 1.2, -0.5, 0.3]
        fk = results["nominal_fk"]["test_config_1"]
        T = ref_fk(_CHAIN_NOMINAL, q)
        np.testing.assert_allclose(fk["position"], T[:3, 3], atol=1e-4)

    def test_config_1_orientation(self, results):
        q = [0.5, -0.3, 0.8, 1.2, -0.5, 0.3]
        fk = results["nominal_fk"]["test_config_1"]
        T = ref_fk(_CHAIN_NOMINAL, q)
        np.testing.assert_allclose(fk["orientation"], T[:3, :3], atol=1e-4)

    def test_config_2_position(self, results):
        q = [-1.0, 0.5, -0.4, 0.0, 1.0, -0.7]
        fk = results["nominal_fk"]["test_config_2"]
        T = ref_fk(_CHAIN_NOMINAL, q)
        np.testing.assert_allclose(fk["position"], T[:3, 3], atol=1e-4)

    def test_config_2_orientation(self, results):
        q = [-1.0, 0.5, -0.4, 0.0, 1.0, -0.7]
        fk = results["nominal_fk"]["test_config_2"]
        T = ref_fk(_CHAIN_NOMINAL, q)
        np.testing.assert_allclose(fk["orientation"], T[:3, :3], atol=1e-4)


# ================================================================
# Calibration Tests
# ================================================================

class TestCalibration:

    def test_stats_present(self, results):
        stats = results["calibration_stats"]
        assert "calibration_rmse" in stats
        assert "validation_rmse" in stats
        assert "nominal_validation_rmse" in stats

    def test_validation_rmse_improvement(self, results):
        """Calibrated model must reduce validation RMSE by >= 60% vs nominal."""
        stats = results["calibration_stats"]
        # Compute nominal validation RMSE independently
        nom_errors = []
        for q in _VALIDATION_CONFIGS:
            T_nom = ref_fk(_CHAIN_NOMINAL, q)
            T_true = ref_fk(_CHAIN_TRUE, q)
            err = np.linalg.norm(T_nom[:3, 3] - T_true[:3, 3])
            nom_errors.append(err)
        nom_rmse = float(np.sqrt(np.mean(np.array(nom_errors) ** 2)))
        # Agent's calibrated validation RMSE must be < 40% of nominal
        cal_rmse = stats["validation_rmse"]
        assert cal_rmse < 0.4 * nom_rmse, (
            f"Calibrated validation RMSE {cal_rmse:.6f} not < 40% of "
            f"nominal RMSE {nom_rmse:.6f} (threshold {0.4 * nom_rmse:.6f})"
        )

    def test_calibrated_fk_count(self, results):
        assert len(results["calibrated_fk"]) == 5, "Expected 5 calibrated FK entries"

    def test_calibrated_fk_accuracy(self, results):
        """Each calibrated FK prediction must be within 4mm of the true position."""
        for i, entry in enumerate(results["calibrated_fk"]):
            q = _VALIDATION_CONFIGS[i]
            T_true = ref_fk(_CHAIN_TRUE, q)
            true_pos = T_true[:3, 3]
            pred_pos = np.array(entry["predicted_position"])
            err = np.linalg.norm(pred_pos - true_pos)
            assert err < 0.004, (
                f"Calibrated FK at validation config {i} has error {err:.6f} m "
                f"> 4mm from true position"
            )

    def test_calibration_rmse_reasonable(self, results):
        """Calibration RMSE should be small (< 5mm)."""
        assert results["calibration_stats"]["calibration_rmse"] < 0.005


# ================================================================
# Inverse Kinematics Tests
# ================================================================

class TestInverseKinematics:

    def test_solution_count(self, results):
        assert len(results["ik_solutions"]) == 3, "Expected 3 IK solutions"

    def test_position_accuracy(self, results):
        """IK solutions verified against the true perturbed model."""
        for sol in results["ik_solutions"]:
            q = sol["joint_angles"]
            T = ref_fk(_CHAIN_TRUE, q)
            target = np.array(sol["target_position"])
            err = np.linalg.norm(T[:3, 3] - target)
            assert err < 0.015, (
                f"IK position error {err:.6f} m > 15mm for {sol['name']} "
                f"(verified against true model)"
            )

    def test_joint_limits(self, results):
        for sol in results["ik_solutions"]:
            for i, (q, (lo, hi)) in enumerate(
                zip(sol["joint_angles"], _JOINT_LIMITS)
            ):
                assert lo - 0.01 <= q <= hi + 0.01, (
                    f"{sol['name']}: joint_{i+1} = {q:.4f} "
                    f"outside [{lo}, {hi}]"
                )


# ================================================================
# Oriented IK Tests
# ================================================================

class TestOrientedIK:

    def test_position(self, results):
        sol = results["ik_with_orientation"]
        q = sol["joint_angles"]
        T = ref_fk(_CHAIN_TRUE, q)
        target = np.array(sol["target_position"])
        err = np.linalg.norm(T[:3, 3] - target)
        assert err < 0.03, (
            f"Oriented IK position error {err:.6f} m > 30mm "
            f"(verified against true model)"
        )

    def test_z_axis(self, results):
        sol = results["ik_with_orientation"]
        q = sol["joint_angles"]
        T = ref_fk(_CHAIN_TRUE, q)
        z_axis = T[:3, 2]
        target_z = np.array(sol["target_orientation_z"])
        err = np.linalg.norm(z_axis - target_z)
        assert err < 0.2, (
            f"Oriented IK Z-axis error {err:.6f} > 0.2 "
            f"(verified against true model)"
        )

    def test_joint_limits(self, results):
        sol = results["ik_with_orientation"]
        for i, (q, (lo, hi)) in enumerate(
            zip(sol["joint_angles"], _JOINT_LIMITS)
        ):
            assert lo - 0.01 <= q <= hi + 0.01


# ================================================================
# Jacobian Tests
# ================================================================

class TestJacobian:

    def test_shape(self, results):
        J = np.array(results["jacobian"]["jacobian"])
        assert J.shape == (6, 6), f"Jacobian shape {J.shape} != (6, 6)"

    def test_values(self, results):
        jd = results["jacobian"]
        q = jd["config"]
        J_s = np.array(jd["jacobian"])
        J_r = ref_jacobian(_CHAIN_TRUE, q)
        np.testing.assert_allclose(J_s, J_r, atol=0.05,
                                   err_msg="Jacobian values mismatch vs true model")

    def test_rank(self, results):
        jd = results["jacobian"]
        q = jd["config"]
        J_r = ref_jacobian(_CHAIN_TRUE, q)
        expected = int(np.linalg.matrix_rank(J_r))
        assert jd["rank"] == expected, (
            f"Jacobian rank {jd['rank']} != expected {expected}"
        )

    def test_manipulability(self, results):
        jd = results["jacobian"]
        q = jd["config"]
        J = ref_jacobian(_CHAIN_TRUE, q)
        expected = float(np.sqrt(max(0, np.linalg.det(J @ J.T))))
        np.testing.assert_allclose(jd["manipulability"], expected,
                                   rtol=0.15, atol=1e-5)

    def test_singular_values(self, results):
        jd = results["jacobian"]
        q = jd["config"]
        J = ref_jacobian(_CHAIN_TRUE, q)
        expected_sv = sorted(np.linalg.svd(J, compute_uv=False), reverse=True)
        actual_sv = sorted(jd["singular_values"], reverse=True)
        np.testing.assert_allclose(actual_sv, expected_sv, atol=0.05)


# ================================================================
# Workspace Tests
# ================================================================

class TestWorkspace:

    def test_volume_range(self, results):
        vol = results["workspace_volume"]
        assert 0.1 < vol < 10.0, (
            f"Workspace volume {vol:.4f} m^3 outside [0.1, 10.0]"
        )
