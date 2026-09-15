"""Tests for quadrotor simulator debugging and system identification.

Verifies that the recovered physical parameters are accurate, physically
consistent, and that a trajectory simulation with those parameters reproduces
the recorded flight data.
"""

import json
import os

import numpy as np
import pytest

# Ground truth parameter values
TRUE_MASS = 0.027
TRUE_KF = 3.16e-10
TRUE_KT = 7.94e-12

RESULTS_PATH = "/app/results/params.json"
DATA_PATH = "/app/data/flight_data.npz"
KNOWN_PATH = "/app/data/known_params.json"


@pytest.fixture
def recovered_params():
    """Load the agent's recovered parameters."""
    assert os.path.exists(RESULTS_PATH), f"Results file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        params = json.load(f)
    return params


@pytest.fixture
def flight_data():
    """Load the recorded flight data."""
    return np.load(DATA_PATH)


@pytest.fixture
def known_params():
    """Load the known physical parameters."""
    with open(KNOWN_PATH) as f:
        return json.load(f)


class TestParamsFileStructure:
    def test_params_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "params.json not found at /app/results/params.json"

    def test_params_has_required_keys(self, recovered_params):
        for key in ["mass", "kf", "kt"]:
            assert key in recovered_params, f"Missing required key: '{key}'"

    def test_params_are_positive_finite(self, recovered_params):
        for key in ["mass", "kf", "kt"]:
            val = recovered_params[key]
            assert isinstance(val, (int, float)), f"'{key}' must be numeric, got {type(val)}"
            assert np.isfinite(val), f"'{key}' must be finite, got {val}"
            assert val > 0, f"'{key}' must be positive, got {val}"


class TestParameterAccuracy:
    def test_mass_accuracy(self, recovered_params):
        mass = recovered_params["mass"]
        rel_error = abs(mass - TRUE_MASS) / TRUE_MASS
        assert rel_error < 0.05, (
            f"mass = {mass:.6f}, true = {TRUE_MASS:.6f}, "
            f"relative error = {rel_error*100:.2f}% (limit: 5%)"
        )

    def test_kf_accuracy(self, recovered_params):
        kf = recovered_params["kf"]
        rel_error = abs(kf - TRUE_KF) / TRUE_KF
        assert rel_error < 0.08, (
            f"kf = {kf:.4e}, true = {TRUE_KF:.4e}, "
            f"relative error = {rel_error*100:.2f}% (limit: 8%)"
        )

    def test_kt_accuracy(self, recovered_params):
        kt = recovered_params["kt"]
        rel_error = abs(kt - TRUE_KT) / TRUE_KT
        assert rel_error < 0.15, (
            f"kt = {kt:.4e}, true = {TRUE_KT:.4e}, "
            f"relative error = {rel_error*100:.2f}% (limit: 15%)"
        )


class TestPhysicalConsistency:
    def test_hover_rpm_realistic(self, recovered_params):
        """Hover RPM must be in a reasonable range for a micro quadrotor."""
        mass = recovered_params["mass"]
        kf = recovered_params["kf"]
        rpm_hover = np.sqrt(mass * 9.81 / (4 * kf))
        assert 5000 < rpm_hover < 30000, (
            f"Computed hover RPM = {rpm_hover:.0f} is outside realistic range [5000, 30000]"
        )

    def test_kt_kf_ratio(self, recovered_params):
        """The torque-to-thrust ratio kt/kf should be small and positive."""
        ratio = recovered_params["kt"] / recovered_params["kf"]
        assert 0.005 < ratio < 0.1, (
            f"kt/kf ratio = {ratio:.4f} is outside expected range [0.005, 0.1]"
        )


class TestTrajectoryConsistency:
    """Simulate 100 steps with recovered params and compare against recorded data."""

    @staticmethod
    def _quat_multiply(q1, q2):
        x1, y1, z1, w1 = q1
        x2, y2, z2, w2 = q2
        return np.array([
            w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2,
            w1*z2 + x1*y2 - y1*x2 + z1*w2,
            w1*w2 - x1*x2 - y1*y2 - z1*z2,
        ])

    @staticmethod
    def _quat_to_rotmat(q):
        x, y, z, w = q
        return np.array([
            [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
            [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
            [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
        ])

    def test_trajectory_match(self, recovered_params, flight_data, known_params):
        mass = recovered_params["mass"]
        kf = recovered_params["kf"]
        kt = recovered_params["kt"]
        L = known_params["arm_length"]
        Ixx = known_params["Ixx"]
        Iyy = known_params["Iyy"]
        Izz = known_params["Izz"]
        g = known_params["g"]
        dt = float(flight_data["timestamps"][1] - flight_data["timestamps"][0])

        positions = flight_data["positions"]
        velocities = flight_data["velocities"]
        quaternions = flight_data["quaternions"]
        angular_velocities = flight_data["angular_velocities"]
        motor_rpms = flight_data["motor_rpms"]

        pos = positions[0].copy()
        vel = velocities[0].copy()
        quat = quaternions[0].copy()
        omega = angular_velocities[0].copy()

        n_check = 100
        pos_errors = []

        for t in range(n_check):
            rpms = motor_rpms[t]
            rpm_sq = rpms ** 2
            f = kf * rpm_sq

            F_total = np.sum(f)
            tau_x = L * (f[3] - f[1])
            tau_y = L * (f[0] - f[2])
            tau_z = kt * (-rpm_sq[0] + rpm_sq[1] - rpm_sq[2] + rpm_sq[3])

            R = self._quat_to_rotmat(quat)
            acc = R @ np.array([0.0, 0.0, F_total]) / mass + np.array([0.0, 0.0, -g])

            J_diag = np.array([Ixx, Iyy, Izz])
            J_inv_diag = 1.0 / J_diag
            tau = np.array([tau_x, tau_y, tau_z])
            J_omega = J_diag * omega
            ang_acc = J_inv_diag * (tau - np.cross(omega, J_omega))

            omega_q = np.array([omega[0], omega[1], omega[2], 0.0])
            q_dot = 0.5 * self._quat_multiply(quat, omega_q)

            pos = pos + vel * dt
            vel = vel + acc * dt
            omega = omega + ang_acc * dt
            quat = quat + q_dot * dt
            quat = quat / np.linalg.norm(quat)

            pos_errors.append(np.linalg.norm(pos - positions[t + 1]))

        mean_err = np.mean(pos_errors)
        max_err = np.max(pos_errors)

        assert mean_err < 0.02, (
            f"Mean position error over {n_check} steps = {mean_err:.4e} m (limit: 0.02 m)"
        )
        assert max_err < 0.10, (
            f"Max position error over {n_check} steps = {max_err:.4e} m (limit: 0.10 m)"
        )
