
import pytest
import numpy as np
import sys
import os

sys.path.insert(0, '/app')

from youbot_controller import (
    next_state,
    compute_end_effector_config,
    mobile_manipulator_jacobian,
    feedback_control,
    compute_controls,
)


class TestOdometryForward:
    """u=(10,10,10,10) for 1s: chassis translates +0.475m in x_b."""

    def test_forward_x(self):
        config = np.zeros(12)
        ctrl = np.array([10, 10, 10, 10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        assert abs(config[1] - 0.475) < 0.002, f"x={config[1]}"

    def test_forward_y_zero(self):
        config = np.zeros(12)
        ctrl = np.array([10, 10, 10, 10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        assert abs(config[2]) < 0.002, f"y={config[2]}"

    def test_forward_phi_zero(self):
        config = np.zeros(12)
        ctrl = np.array([10, 10, 10, 10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        assert abs(config[0]) < 0.002, f"phi={config[0]}"


class TestOdometrySideways:
    """u=(-10,10,-10,10) for 1s: chassis slides +0.475m in y_b."""

    def test_sideways_y(self):
        config = np.zeros(12)
        ctrl = np.array([-10, 10, -10, 10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        assert abs(config[2] - 0.475) < 0.002, f"y={config[2]}"

    def test_sideways_x_zero(self):
        config = np.zeros(12)
        ctrl = np.array([-10, 10, -10, 10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        assert abs(config[1]) < 0.002, f"x={config[1]}"


class TestOdometryRotation:
    """u=(-10,10,10,-10) for 1s: chassis rotates CCW."""

    def test_rotation_phi(self):
        config = np.zeros(12)
        ctrl = np.array([-10, 10, 10, -10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        expected_phi = 0.0475 * 10.0 / 0.385
        assert abs(config[0] - expected_phi) < 0.01, f"phi={config[0]}"

    def test_rotation_xy_zero(self):
        config = np.zeros(12)
        ctrl = np.array([-10, 10, 10, -10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 100.0)
        assert abs(config[1]) < 0.01, f"x={config[1]}"
        assert abs(config[2]) < 0.01, f"y={config[2]}"


class TestSpeedLimit:
    """Speed limit of 5 should halve the forward distance (0.2375m)."""

    def test_speed_limit_halves_distance(self):
        config = np.zeros(12)
        ctrl = np.array([10, 10, 10, 10, 0, 0, 0, 0, 0], dtype=float)
        for _ in range(100):
            config = next_state(config, ctrl, 0.01, 5.0)
        assert abs(config[1] - 0.2375) < 0.002, f"x={config[1]}"


class TestEndEffectorConfig:
    """Verify T_se at config (0,0,0, 0,0,0.2,-1.6,0, 0,0,0,0)."""

    def test_ee_config(self):
        config = np.array([0, 0, 0, 0, 0, 0.2, -1.6, 0, 0, 0, 0, 0])
        T_se = compute_end_effector_config(config)
        X_expected = np.array([
            [0.170, 0, 0.985, 0.387],
            [0, 1, 0, 0],
            [-0.985, 0, 0.170, 0.570],
            [0, 0, 0, 1],
        ])
        np.testing.assert_allclose(T_se, X_expected, atol=0.002)


class TestJacobian:
    """Verify 6x9 Jacobian at the reference configuration."""

    def test_shape(self):
        config = np.array([0, 0, 0, 0, 0, 0.2, -1.6, 0, 0, 0, 0, 0])
        Je = mobile_manipulator_jacobian(config)
        assert Je.shape == (6, 9), f"shape={Je.shape}"

    def test_values(self):
        config = np.array([0, 0, 0, 0, 0, 0.2, -1.6, 0, 0, 0, 0, 0])
        Je = mobile_manipulator_jacobian(config)
        Je_expected = np.array([
            [ 0.030, -0.030, -0.030,  0.030, -0.985,  0,      0,      0,     0],
            [ 0,      0,      0,      0,      0,     -1,     -1,     -1,     0],
            [-0.005,  0.005,  0.005, -0.005,  0.170,  0,      0,      0,     1],
            [ 0.002,  0.002,  0.002,  0.002,  0,     -0.240, -0.214, -0.218, 0],
            [-0.024,  0.024,  0,      0,      0.221,  0,      0,      0,     0],
            [ 0.012,  0.012,  0.012,  0.012,  0,     -0.288, -0.135,  0,     0],
        ])
        np.testing.assert_allclose(Je, Je_expected, atol=0.005)


class TestFeedbackControl:
    """Verify control law outputs at the reference test point."""

    X = np.array([
        [0.170, 0, 0.985, 0.387],
        [0, 1, 0, 0],
        [-0.985, 0, 0.170, 0.570],
        [0, 0, 0, 1],
    ])
    Xd = np.array([
        [0, 0, 1, 0.5],
        [0, 1, 0, 0],
        [-1, 0, 0, 0.5],
        [0, 0, 0, 1],
    ])
    Xd_next = np.array([
        [0, 0, 1, 0.6],
        [0, 1, 0, 0],
        [-1, 0, 0, 0.3],
        [0, 0, 0, 1],
    ])

    def test_feedforward_only_twist(self):
        """With Kp=Ki=0, V should equal [Ad_{X^{-1}Xd}] Vd."""
        V, _, _ = feedback_control(
            self.X, self.Xd, self.Xd_next,
            np.zeros((6, 6)), np.zeros((6, 6)), np.zeros(6), 0.01,
        )
        V_exp = np.array([0, 0, 0, 21.409, 0, 6.455])
        np.testing.assert_allclose(V, V_exp, atol=0.02)

    def test_feedforward_only_error(self):
        _, Xerr, _ = feedback_control(
            self.X, self.Xd, self.Xd_next,
            np.zeros((6, 6)), np.zeros((6, 6)), np.zeros(6), 0.01,
        )
        Xerr_exp = np.array([0, 0.171, 0, 0.080, 0, 0.107])
        np.testing.assert_allclose(Xerr, Xerr_exp, atol=0.005)

    def test_proportional_gain(self):
        """With Kp=I, V = [Ad]Vd + Xerr."""
        V, _, _ = feedback_control(
            self.X, self.Xd, self.Xd_next,
            np.eye(6), np.zeros((6, 6)), np.zeros(6), 0.01,
        )
        V_exp = np.array([0, 0.171, 0, 21.488, 0, 6.562])
        np.testing.assert_allclose(V, V_exp, atol=0.02)


class TestComputeControls:
    """Verify pseudoinverse control mapping at the reference point."""

    def test_controls(self):
        config = np.array([0, 0, 0, 0, 0, 0.2, -1.6, 0, 0, 0, 0, 0])
        V = np.array([0, 0, 0, 21.409, 0, 6.455])
        ctrl = compute_controls(V, config)
        ctrl_exp = np.array([157.2, 157.2, 157.2, 157.2,
                             0, -652.9, 1398.6, -745.7, 0])
        np.testing.assert_allclose(ctrl, ctrl_exp, atol=2.0)


class TestConvergence:
    """Run the full controller loop and check error convergence."""

    def test_convergence_to_target(self):
        config = np.array([0, 0, 0, 0, 0, 0.2, -1.6, 0, 0, 0, 0, 0])

        Xd = np.array([
            [0, 0, 1, 0.5],
            [0, 1, 0, 0],
            [-1, 0, 0, 0.5],
            [0, 0, 0, 1],
        ])
        Xd_next = Xd.copy()

        Kp = 1.5 * np.eye(6)
        Ki = 0.2 * np.eye(6)
        dt = 0.01
        speed_limit = 30.0
        error_integral = np.zeros(6)

        for _ in range(500):
            X = compute_end_effector_config(config)
            V, Xerr, error_integral = feedback_control(
                X, Xd, Xd_next, Kp, Ki, error_integral, dt,
            )
            ctrl = compute_controls(V, config)
            config = next_state(config, ctrl, dt, speed_limit)

        X_final = compute_end_effector_config(config)
        _, Xerr_final, _ = feedback_control(
            X_final, Xd, Xd_next,
            np.zeros((6, 6)), np.zeros((6, 6)), np.zeros(6), dt,
        )

        pos_err = np.linalg.norm(Xerr_final[3:6])
        rot_err = np.linalg.norm(Xerr_final[0:3])
        assert pos_err < 0.02, f"position error {pos_err:.4f} > 0.02"
        assert rot_err < 0.05, f"rotation error {rot_err:.4f} > 0.05"


class TestErrorDataCSV:
    """Verify error_data.csv exists with correct format and convergence."""

    def test_file_exists(self):
        assert os.path.isfile('/app/error_data.csv'), "error_data.csv not found"

    def test_header_and_row_count(self):
        with open('/app/error_data.csv') as f:
            lines = f.readlines()
        header = lines[0].strip()
        assert header == 'step,wx,wy,wz,vx,vy,vz', f"Bad header: {header}"
        assert len(lines) == 501, f"Expected 501 lines (header + 500), got {len(lines)}"

    def test_data_converges(self):
        data = np.genfromtxt('/app/error_data.csv', delimiter=',', skip_header=1)
        final_err = np.linalg.norm(data[-1, 1:])
        assert final_err < 0.05, f"Final error {final_err:.4f} >= 0.05"

    def test_initial_error_nonzero(self):
        data = np.genfromtxt('/app/error_data.csv', delimiter=',', skip_header=1)
        initial_err = np.linalg.norm(data[0, 1:])
        assert initial_err > 0.05, f"Initial error {initial_err:.4f} suspiciously small"


class TestErrorPlot:
    """Verify error_plot.png exists and is a valid PNG."""

    def test_file_exists(self):
        assert os.path.isfile('/app/error_plot.png'), "error_plot.png not found"

    def test_is_valid_png(self):
        with open('/app/error_plot.png', 'rb') as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG', "File is not a valid PNG"

    def test_file_not_trivial(self):
        size = os.path.getsize('/app/error_plot.png')
        assert size > 1000, f"PNG too small ({size} bytes)"
