
import csv
import json
import os
import subprocess
import numpy as np
import pytest
import sys

sys.path.insert(0, "/app")

from cpi_preintegration import (
    skew_x,
    quat_2_rot,
    rot_2_quat,
    quat_multiply,
    exp_so3,
    log_so3,
    CpiV1,
    CpiV2,
)


# ============================================================
# Quaternion and SO(3) utility tests
# ============================================================

class TestQuaternionOps:
    def test_skew_antisymmetric(self):
        w = np.array([0.3, -0.7, 1.2])
        S = skew_x(w)
        np.testing.assert_allclose(S + S.T, np.zeros((3, 3)), atol=1e-15)

    def test_skew_cross_product(self):
        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        np.testing.assert_allclose(skew_x(a) @ b, np.cross(a, b), atol=1e-14)

    def test_quat_rot_roundtrip(self):
        axis = np.array([1.0, 2.0, 3.0])
        axis /= np.linalg.norm(axis)
        R = exp_so3(axis * 0.7)
        q = rot_2_quat(R)
        R_rec = quat_2_rot(q)
        np.testing.assert_allclose(R_rec, R, atol=1e-13)

    def test_quat_rot_roundtrip_large_angle(self):
        R = exp_so3(np.array([2.5, -1.3, 0.8]))
        q = rot_2_quat(R)
        R_rec = quat_2_rot(q)
        np.testing.assert_allclose(R_rec, R, atol=1e-12)

    def test_quat_multiply_composition(self):
        w1 = np.array([0.3, -0.2, 0.5])
        w2 = np.array([0.1, 0.4, -0.3])
        R1, R2 = exp_so3(w1), exp_so3(w2)
        q1, q2 = rot_2_quat(R1), rot_2_quat(R2)
        q12 = quat_multiply(q1, q2)
        R12 = quat_2_rot(q12)
        np.testing.assert_allclose(R12, R1 @ R2, atol=1e-13)

    def test_quat_scalar_positive(self):
        R = exp_so3(np.array([3.0, 0.1, 0.1]))
        q = rot_2_quat(R)
        assert q[3] >= 0

    def test_quat_unit_norm(self):
        R = exp_so3(np.array([0.5, -1.2, 0.7]))
        q = rot_2_quat(R)
        np.testing.assert_allclose(np.linalg.norm(q), 1.0, atol=1e-15)


class TestSO3:
    def test_exp_log_roundtrip(self):
        w = np.array([0.5, -0.3, 0.8])
        R = exp_so3(w)
        w_rec = log_so3(R)
        np.testing.assert_allclose(w_rec, w, atol=1e-12)

    def test_exp_log_roundtrip_small(self):
        w = np.array([1e-8, -2e-9, 5e-9])
        R = exp_so3(w)
        w_rec = log_so3(R)
        np.testing.assert_allclose(w_rec, w, atol=1e-15)

    def test_exp_log_roundtrip_near_pi(self):
        w = np.array([3.1, 0.05, 0.03])
        R = exp_so3(w)
        w_rec = log_so3(R)
        np.testing.assert_allclose(exp_so3(w_rec), R, atol=1e-10)

    def test_exp_identity(self):
        np.testing.assert_allclose(exp_so3(np.zeros(3)), np.eye(3), atol=1e-15)

    def test_exp_is_rotation(self):
        w = np.array([1.2, -0.7, 0.4])
        R = exp_so3(w)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-13)
        np.testing.assert_allclose(np.linalg.det(R), 1.0, atol=1e-13)


# ============================================================
# CPI V1 mean propagation tests
# ============================================================

class TestCpiV1Mean:
    def test_single_step_rotation(self):
        dt = 0.01
        w_true = np.array([0.15, -0.08, 0.22])
        b_w = np.array([0.01, -0.005, 0.008])
        w_m = w_true + b_w
        a_m = np.array([0.5, -0.3, 9.81])
        b_a = np.zeros(3)

        cpi = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a)
        cpi.feed_imu(0.0, dt, w_m, a_m)

        R_expected = exp_so3(-w_true * dt)
        np.testing.assert_allclose(cpi.R_k2tau, R_expected, atol=1e-14)

    def test_multi_step_rotation(self):
        n_steps, dt = 20, 0.005
        w_true = np.array([0.15, -0.08, 0.22])
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = w_true + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        R_expected = np.eye(3)
        R_step = exp_so3(-w_true * dt)
        for _ in range(n_steps):
            R_expected = R_step @ R_expected
        np.testing.assert_allclose(cpi.R_k2tau, R_expected, atol=1e-12)

    def test_zero_angular_velocity(self):
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = b_w.copy()
        a_m = np.array([0.5, -0.3, 9.81]) + b_a
        dt = 0.01

        cpi = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a)
        for i in range(10):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        np.testing.assert_allclose(cpi.R_k2tau, np.eye(3), atol=1e-14)

    def test_dt_accumulation(self):
        n_steps, dt = 15, 0.007
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        np.testing.assert_allclose(cpi.DT, n_steps * dt, atol=1e-14)

    def test_quaternion_matches_rotation(self):
        n_steps, dt = 10, 0.005
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.2, -0.1, 0.15]) + b_w
        a_m = np.array([0.3, -0.5, 9.7]) + b_a

        cpi = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        R_from_q = quat_2_rot(cpi.q_k2tau)
        np.testing.assert_allclose(R_from_q, cpi.R_k2tau, atol=1e-13)


# ============================================================
# V1 Bias Jacobian finite-difference verification
# ============================================================

def _generate_imu_data(n_steps=15, dt=0.005):
    """Generate fixed, deterministic IMU data with sinusoidal variation."""
    b_w_true = np.array([0.01, -0.005, 0.008])
    b_a_true = np.array([0.05, -0.03, 0.02])
    w_base = np.array([0.15, -0.08, 0.22])
    a_base = np.array([0.5, -0.3, 9.75])

    imu_data = []
    for i in range(n_steps):
        phase = i * 0.3
        w_m = w_base + b_w_true + 0.02 * np.array(
            [np.sin(phase), np.cos(phase), np.sin(2 * phase)]
        )
        a_m = a_base + b_a_true + 0.05 * np.array(
            [np.cos(phase), np.sin(phase), np.cos(2 * phase)]
        )
        imu_data.append((i * dt, (i + 1) * dt, w_m.copy(), a_m.copy()))
    return imu_data, b_w_true, b_a_true


def _run_cpi_with_data(imu_data, b_w_lin, b_a_lin,
                       sigma_w=0.003, sigma_wb=0.0001,
                       sigma_a=0.01, sigma_ab=0.001):
    cpi = CpiV1(sigma_w, sigma_wb, sigma_a, sigma_ab)
    cpi.set_linearization_points(b_w_lin, b_a_lin)
    for t0, t1, w_m, a_m in imu_data:
        cpi.feed_imu(t0, t1, w_m, a_m)
    return cpi


def _run_cpiv2_with_data(imu_data, b_w_lin, b_a_lin, q_k_lin, grav,
                         sigma_w=0.003, sigma_wb=0.0001,
                         sigma_a=0.01, sigma_ab=0.001):
    cpi = CpiV2(sigma_w, sigma_wb, sigma_a, sigma_ab)
    cpi.set_linearization_points(b_w_lin, b_a_lin, q_k_lin, grav)
    for t0, t1, w_m, a_m in imu_data:
        cpi.feed_imu(t0, t1, w_m, a_m)
    return cpi


class TestCpiV1BiasJacobians:
    """Verify analytical bias Jacobians against central finite differences."""

    def test_J_q_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)
        J_q_an = cpi_nom.J_q.copy()

        J_q_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3)
            d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w + d, b_a)
            cm = _run_cpi_with_data(imu_data, b_w - d, b_a)
            J_q_fd[:, i] = log_so3(cp.R_k2tau @ cm.R_k2tau.T) / (2 * eps)

        np.testing.assert_allclose(J_q_fd, J_q_an, atol=1e-5)

    def test_J_a_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)

        J_a_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3)
            d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w + d, b_a)
            cm = _run_cpi_with_data(imu_data, b_w - d, b_a)
            J_a_fd[:, i] = (cp.alpha_tau - cm.alpha_tau) / (2 * eps)

        np.testing.assert_allclose(J_a_fd, cpi_nom.J_a, atol=1e-5)

    def test_J_b_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)

        J_b_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3)
            d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w + d, b_a)
            cm = _run_cpi_with_data(imu_data, b_w - d, b_a)
            J_b_fd[:, i] = (cp.beta_tau - cm.beta_tau) / (2 * eps)

        np.testing.assert_allclose(J_b_fd, cpi_nom.J_b, atol=1e-5)

    def test_H_a_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)

        H_a_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3)
            d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w, b_a + d)
            cm = _run_cpi_with_data(imu_data, b_w, b_a - d)
            H_a_fd[:, i] = (cp.alpha_tau - cm.alpha_tau) / (2 * eps)

        np.testing.assert_allclose(H_a_fd, cpi_nom.H_a, atol=1e-8)

    def test_H_b_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)

        H_b_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3)
            d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w, b_a + d)
            cm = _run_cpi_with_data(imu_data, b_w, b_a - d)
            H_b_fd[:, i] = (cp.beta_tau - cm.beta_tau) / (2 * eps)

        np.testing.assert_allclose(H_b_fd, cpi_nom.H_b, atol=1e-8)

    def test_jacobians_nonzero(self):
        imu_data, b_w, b_a = _generate_imu_data()
        cpi = _run_cpi_with_data(imu_data, b_w, b_a)
        assert np.linalg.norm(cpi.J_q) > 1e-6
        assert np.linalg.norm(cpi.J_a) > 1e-10
        assert np.linalg.norm(cpi.J_b) > 1e-8
        assert np.linalg.norm(cpi.H_a) > 1e-8
        assert np.linalg.norm(cpi.H_b) > 1e-6


class TestCpiV1BiasJacobiansAlt:
    def _generate_alt_data(self):
        b_w = np.array([0.005, 0.01, -0.003])
        b_a = np.array([-0.02, 0.04, 0.01])
        w_base = np.array([0.3, 0.1, -0.15])
        a_base = np.array([-0.2, 0.8, 9.6])
        n_steps, dt = 25, 0.004

        imu_data = []
        for i in range(n_steps):
            ph = i * 0.25
            w_m = w_base + b_w + 0.03 * np.array(
                [np.cos(ph), np.sin(2*ph), np.cos(3*ph)]
            )
            a_m = a_base + b_a + 0.08 * np.array(
                [np.sin(ph), np.cos(ph), np.sin(2*ph)]
            )
            imu_data.append((i*dt, (i+1)*dt, w_m.copy(), a_m.copy()))
        return imu_data, b_w, b_a

    def test_J_q_alt(self):
        imu_data, b_w, b_a = self._generate_alt_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)
        J_q_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3); d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w + d, b_a)
            cm = _run_cpi_with_data(imu_data, b_w - d, b_a)
            J_q_fd[:, i] = log_so3(cp.R_k2tau @ cm.R_k2tau.T) / (2*eps)
        np.testing.assert_allclose(J_q_fd, cpi_nom.J_q, atol=1e-5)

    def test_H_a_alt(self):
        imu_data, b_w, b_a = self._generate_alt_data()
        eps = 1e-7
        cpi_nom = _run_cpi_with_data(imu_data, b_w, b_a)
        H_a_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3); d[i] = eps
            cp = _run_cpi_with_data(imu_data, b_w, b_a + d)
            cm = _run_cpi_with_data(imu_data, b_w, b_a - d)
            H_a_fd[:, i] = (cp.alpha_tau - cm.alpha_tau) / (2*eps)
        np.testing.assert_allclose(H_a_fd, cpi_nom.H_a, atol=1e-8)


# ============================================================
# V1 Covariance tests
# ============================================================

class TestCpiV1Covariance:
    def _run_cpi(self, n_steps=20, dt=0.005,
                 sigma_w=0.003, sigma_wb=0.0001,
                 sigma_a=0.01, sigma_ab=0.001):
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi = CpiV1(sigma_w, sigma_wb, sigma_a, sigma_ab)
        cpi.set_linearization_points(b_w, b_a)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)
        return cpi

    def test_symmetric(self):
        cpi = self._run_cpi()
        np.testing.assert_allclose(cpi.P_meas, cpi.P_meas.T, atol=1e-15)

    def test_positive_semidefinite(self):
        cpi = self._run_cpi()
        eigvals = np.linalg.eigvalsh(cpi.P_meas)
        assert np.all(eigvals >= -1e-15), f"Negative eigenvalue: {eigvals.min()}"

    def test_nonzero_diag(self):
        cpi = self._run_cpi()
        assert np.all(np.diag(cpi.P_meas)[:3] > 0)
        assert np.all(np.diag(cpi.P_meas)[6:9] > 0)

    def test_grows_with_time(self):
        cpi5 = self._run_cpi(n_steps=5)
        cpi20 = self._run_cpi(n_steps=20)
        assert np.trace(cpi20.P_meas) > np.trace(cpi5.P_meas)

    def test_scales_with_noise(self):
        cpi_low = self._run_cpi(
            n_steps=10, sigma_w=0.001, sigma_wb=0.0001,
            sigma_a=0.005, sigma_ab=0.0005
        )
        cpi_high = self._run_cpi(
            n_steps=10, sigma_w=0.01, sigma_wb=0.001,
            sigma_a=0.05, sigma_ab=0.005
        )
        assert np.trace(cpi_high.P_meas) > np.trace(cpi_low.P_meas)


# ============================================================
# V1 IMU averaging tests
# ============================================================

class TestCpiV1ImuAvg:
    def test_averaging_changes_result(self):
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w0 = np.array([0.15, -0.08, 0.22]) + b_w
        a0 = np.array([0.5, -0.3, 9.75]) + b_a
        w1 = np.array([0.18, -0.06, 0.19]) + b_w
        a1 = np.array([0.6, -0.25, 9.70]) + b_a
        dt = 0.01

        cpi_no = CpiV1(0.003, 0.0001, 0.01, 0.001, imu_avg=False)
        cpi_no.set_linearization_points(b_w, b_a)
        cpi_no.feed_imu(0, dt, w0, a0, w1, a1)

        cpi_yes = CpiV1(0.003, 0.0001, 0.01, 0.001, imu_avg=True)
        cpi_yes.set_linearization_points(b_w, b_a)
        cpi_yes.feed_imu(0, dt, w0, a0, w1, a1)

        assert not np.allclose(cpi_no.R_k2tau, cpi_yes.R_k2tau, atol=1e-10)

    def test_identical_endpoints(self):
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a
        dt = 0.01

        cpi_no = CpiV1(0.003, 0.0001, 0.01, 0.001, imu_avg=False)
        cpi_no.set_linearization_points(b_w, b_a)
        cpi_no.feed_imu(0, dt, w_m, a_m, w_m, a_m)

        cpi_yes = CpiV1(0.003, 0.0001, 0.01, 0.001, imu_avg=True)
        cpi_yes.set_linearization_points(b_w, b_a)
        cpi_yes.feed_imu(0, dt, w_m, a_m, w_m, a_m)

        np.testing.assert_allclose(cpi_no.R_k2tau, cpi_yes.R_k2tau, atol=1e-14)
        np.testing.assert_allclose(cpi_no.alpha_tau, cpi_yes.alpha_tau, atol=1e-14)


# ============================================================
# CPI V2 mean propagation tests
# ============================================================

class TestCpiV2Mean:
    def test_zero_gravity_matches_v1_mean(self):
        """V2 with grav=0 produces same mean propagation as V1."""
        n_steps, dt = 20, 0.005
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi_v1 = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi_v1.set_linearization_points(b_w, b_a)

        q_id = np.array([0., 0., 0., 1.])
        grav_zero = np.zeros(3)
        cpi_v2 = CpiV2(0.003, 0.0001, 0.01, 0.001)
        cpi_v2.set_linearization_points(b_w, b_a, q_id, grav_zero)

        for i in range(n_steps):
            cpi_v1.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)
            cpi_v2.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        np.testing.assert_allclose(cpi_v2.alpha_tau, cpi_v1.alpha_tau, atol=1e-12)
        np.testing.assert_allclose(cpi_v2.beta_tau, cpi_v1.beta_tau, atol=1e-12)
        np.testing.assert_allclose(cpi_v2.R_k2tau, cpi_v1.R_k2tau, atol=1e-14)
        np.testing.assert_allclose(cpi_v2.DT, cpi_v1.DT, atol=1e-15)

    def test_gravity_changes_acceleration(self):
        """V2 with non-zero gravity differs from V1."""
        n_steps, dt = 10, 0.005
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi_v1 = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi_v1.set_linearization_points(b_w, b_a)

        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])
        cpi_v2 = CpiV2(0.003, 0.0001, 0.01, 0.001)
        cpi_v2.set_linearization_points(b_w, b_a, q_id, grav)

        for i in range(n_steps):
            cpi_v1.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)
            cpi_v2.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        # Rotation should still match (gravity doesn't affect rotation)
        np.testing.assert_allclose(cpi_v2.R_k2tau, cpi_v1.R_k2tau, atol=1e-14)
        # But alpha/beta should differ (gravity compensation)
        assert not np.allclose(cpi_v2.alpha_tau, cpi_v1.alpha_tau, atol=1e-3)
        assert not np.allclose(cpi_v2.beta_tau, cpi_v1.beta_tau, atol=1e-3)

    def test_dt_accumulation(self):
        n_steps, dt = 15, 0.007
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi = CpiV2(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a, q_id, grav)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        np.testing.assert_allclose(cpi.DT, n_steps * dt, atol=1e-14)

    def test_quaternion_matches_rotation(self):
        n_steps, dt = 10, 0.005
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])
        w_m = np.array([0.2, -0.1, 0.15]) + b_w
        a_m = np.array([0.3, -0.5, 9.7]) + b_a

        cpi = CpiV2(0.003, 0.0001, 0.01, 0.001)
        cpi.set_linearization_points(b_w, b_a, q_id, grav)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        R_from_q = quat_2_rot(cpi.q_k2tau)
        np.testing.assert_allclose(R_from_q, cpi.R_k2tau, atol=1e-13)


# ============================================================
# V2 Covariance tests
# ============================================================

class TestCpiV2Covariance:
    def _run_v2(self, n_steps=20, dt=0.005,
                sigma_w=0.003, sigma_wb=0.0001,
                sigma_a=0.01, sigma_ab=0.001,
                grav=None):
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        q_id = np.array([0., 0., 0., 1.])
        if grav is None:
            grav = np.array([0., 0., 9.81])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi = CpiV2(sigma_w, sigma_wb, sigma_a, sigma_ab)
        cpi.set_linearization_points(b_w, b_a, q_id, grav)
        for i in range(n_steps):
            cpi.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)
        return cpi

    def test_symmetric(self):
        cpi = self._run_v2()
        np.testing.assert_allclose(cpi.P_meas, cpi.P_meas.T, atol=1e-14)

    def test_positive_semidefinite(self):
        cpi = self._run_v2()
        eigvals = np.linalg.eigvalsh(cpi.P_meas)
        assert np.all(eigvals >= -1e-14), f"Negative eigenvalue: {eigvals.min()}"

    def test_grows_with_time(self):
        cpi5 = self._run_v2(n_steps=5)
        cpi20 = self._run_v2(n_steps=20)
        assert np.trace(cpi20.P_meas) > np.trace(cpi5.P_meas)

    def test_p_big_shape(self):
        cpi = self._run_v2()
        assert cpi.P_big.shape == (21, 21)

    def test_zero_gravity_covariance_matches_v1(self):
        """V2 with grav=0 produces same P_meas as V1."""
        n_steps, dt = 20, 0.005
        b_w = np.array([0.01, -0.005, 0.008])
        b_a = np.array([0.05, -0.03, 0.02])
        w_m = np.array([0.15, -0.08, 0.22]) + b_w
        a_m = np.array([0.5, -0.3, 9.75]) + b_a

        cpi_v1 = CpiV1(0.003, 0.0001, 0.01, 0.001)
        cpi_v1.set_linearization_points(b_w, b_a)

        q_id = np.array([0., 0., 0., 1.])
        grav_zero = np.zeros(3)
        cpi_v2 = CpiV2(0.003, 0.0001, 0.01, 0.001)
        cpi_v2.set_linearization_points(b_w, b_a, q_id, grav_zero)

        for i in range(n_steps):
            cpi_v1.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)
            cpi_v2.feed_imu(i * dt, (i + 1) * dt, w_m, a_m)

        np.testing.assert_allclose(cpi_v2.P_meas, cpi_v1.P_meas, atol=1e-14)


# ============================================================
# V2 Bias Jacobian tests
# ============================================================

class TestCpiV2Jacobians:
    """Verify V2 state-transition Jacobians against finite differences."""

    def test_J_q_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])
        eps = 1e-7

        cpi_nom = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav)
        J_q_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3); d[i] = eps
            cp = _run_cpiv2_with_data(imu_data, b_w + d, b_a, q_id, grav)
            cm = _run_cpiv2_with_data(imu_data, b_w - d, b_a, q_id, grav)
            J_q_fd[:, i] = log_so3(cp.R_k2tau @ cm.R_k2tau.T) / (2 * eps)

        np.testing.assert_allclose(J_q_fd, cpi_nom.J_q, atol=1e-4)

    def test_H_a_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])
        eps = 1e-7

        cpi_nom = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav)
        H_a_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3); d[i] = eps
            cp = _run_cpiv2_with_data(imu_data, b_w, b_a + d, q_id, grav)
            cm = _run_cpiv2_with_data(imu_data, b_w, b_a - d, q_id, grav)
            H_a_fd[:, i] = (cp.alpha_tau - cm.alpha_tau) / (2 * eps)

        np.testing.assert_allclose(H_a_fd, cpi_nom.H_a, atol=1e-4)

    def test_H_b_finite_difference(self):
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])
        eps = 1e-7

        cpi_nom = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav)
        H_b_fd = np.zeros((3, 3))
        for i in range(3):
            d = np.zeros(3); d[i] = eps
            cp = _run_cpiv2_with_data(imu_data, b_w, b_a + d, q_id, grav)
            cm = _run_cpiv2_with_data(imu_data, b_w, b_a - d, q_id, grav)
            H_b_fd[:, i] = (cp.beta_tau - cm.beta_tau) / (2 * eps)

        np.testing.assert_allclose(H_b_fd, cpi_nom.H_b, atol=1e-4)

    def test_O_a_O_b_nonzero_with_gravity(self):
        """Orientation linearization Jacobians should be nonzero when gravity is nonzero."""
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])

        cpi = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav)
        assert np.linalg.norm(cpi.O_a) > 1e-6, "O_a should be nonzero with gravity"
        assert np.linalg.norm(cpi.O_b) > 1e-6, "O_b should be nonzero with gravity"

    def test_O_a_O_b_zero_without_gravity(self):
        """Orientation linearization Jacobians should be zero when gravity is zero."""
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav_zero = np.zeros(3)

        cpi = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav_zero)
        np.testing.assert_allclose(cpi.O_a, np.zeros((3, 3)), atol=1e-15)
        np.testing.assert_allclose(cpi.O_b, np.zeros((3, 3)), atol=1e-15)

    def test_J_q_matches_v1_zero_gravity(self):
        """V2 J_q with zero gravity should match V1 analytical J_q."""
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav_zero = np.zeros(3)

        cpi_v1 = _run_cpi_with_data(imu_data, b_w, b_a)
        cpi_v2 = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav_zero)

        np.testing.assert_allclose(cpi_v2.J_q, cpi_v1.J_q, atol=1e-8)

    def test_all_jacobians_nonzero(self):
        imu_data, b_w, b_a = _generate_imu_data()
        q_id = np.array([0., 0., 0., 1.])
        grav = np.array([0., 0., 9.81])

        cpi = _run_cpiv2_with_data(imu_data, b_w, b_a, q_id, grav)
        assert np.linalg.norm(cpi.J_q) > 1e-6
        assert np.linalg.norm(cpi.H_a) > 1e-8
        assert np.linalg.norm(cpi.H_b) > 1e-6


# ============================================================
# C++ Build and Ground Truth tests
# ============================================================

class TestBuild:
    def test_binary_exists(self):
        assert os.path.exists('/app/build/generate_groundtruth'), \
            "C++ binary /app/build/generate_groundtruth not found"

    def test_binary_runs(self):
        result = subprocess.run(
            ['/app/build/generate_groundtruth'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Binary failed: {result.stderr}"

    def test_groundtruth_v1_exists(self):
        assert os.path.exists('/app/output/groundtruth_v1.json'), \
            "Ground truth V1 not found"

    def test_groundtruth_v2_exists(self):
        assert os.path.exists('/app/output/groundtruth_v2.json'), \
            "Ground truth V2 not found"

    def test_groundtruth_v1_schema(self):
        with open('/app/output/groundtruth_v1.json') as f:
            d = json.load(f)
        assert isinstance(d['DT'], (int, float))
        assert len(d['alpha_tau']) == 3
        assert len(d['beta_tau']) == 3
        assert len(d['q_k2tau']) == 4
        assert isinstance(d['P_meas_trace'], (int, float))
        assert len(d['P_meas_diag']) == 15

    def test_groundtruth_v2_schema(self):
        with open('/app/output/groundtruth_v2.json') as f:
            d = json.load(f)
        assert isinstance(d['DT'], (int, float))
        assert len(d['alpha_tau']) == 3
        assert len(d['beta_tau']) == 3
        assert len(d['q_k2tau']) == 4
        assert isinstance(d['P_meas_trace'], (int, float))
        assert len(d['P_meas_diag']) == 15

    def test_groundtruth_v1_v2_differ(self):
        """V1 and V2 ground truth should differ (V2 has gravity compensation)."""
        with open('/app/output/groundtruth_v1.json') as f:
            d1 = json.load(f)
        with open('/app/output/groundtruth_v2.json') as f:
            d2 = json.load(f)
        assert not np.allclose(d1['alpha_tau'], d2['alpha_tau'], atol=1e-3)


# ============================================================
# Cross-validation: Python vs C++ ground truth
# ============================================================

class TestCrossValidation:
    @classmethod
    def setup_class(cls):
        cls.gt_v1 = None
        cls.gt_v2 = None
        if os.path.exists('/app/output/groundtruth_v1.json'):
            with open('/app/output/groundtruth_v1.json') as f:
                cls.gt_v1 = json.load(f)
        if os.path.exists('/app/output/groundtruth_v2.json'):
            with open('/app/output/groundtruth_v2.json') as f:
                cls.gt_v2 = json.load(f)

    def _run_python_v1(self):
        with open('/app/data/sensor_config.json') as f:
            config = json.load(f)
        rows = []
        with open('/app/data/imu_sequence.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        noise = config['noise_parameters']
        cpi = CpiV1(
            noise['gyroscope_noise_density'],
            noise['gyroscope_random_walk'],
            noise['accelerometer_noise_density'],
            noise['accelerometer_random_walk'],
            imu_avg=config['options'].get('imu_averaging', False)
        )
        bias = config['bias_linearization']
        cpi.set_linearization_points(
            np.array(bias['gyroscope']),
            np.array(bias['accelerometer'])
        )
        for i in range(len(rows) - 1):
            t0 = int(rows[i]['timestamp_ns']) * 1e-9
            t1 = int(rows[i + 1]['timestamp_ns']) * 1e-9
            w0 = np.array([float(rows[i][c]) for c in ('gyro_x', 'gyro_y', 'gyro_z')])
            a0 = np.array([float(rows[i][c]) for c in ('accel_x', 'accel_y', 'accel_z')])
            cpi.feed_imu(t0, t1, w0, a0)
        return cpi

    def _run_python_v2(self):
        with open('/app/data/sensor_config.json') as f:
            config = json.load(f)
        rows = []
        with open('/app/data/imu_sequence.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        noise = config['noise_parameters']
        cpi = CpiV2(
            noise['gyroscope_noise_density'],
            noise['gyroscope_random_walk'],
            noise['accelerometer_noise_density'],
            noise['accelerometer_random_walk'],
            imu_avg=config['options'].get('imu_averaging', False)
        )
        bias = config['bias_linearization']
        orient = config['orientation_linearization']
        cpi.set_linearization_points(
            np.array(bias['gyroscope']),
            np.array(bias['accelerometer']),
            np.array(orient['q_k_lin']),
            np.array(orient['gravity'])
        )
        for i in range(len(rows) - 1):
            t0 = int(rows[i]['timestamp_ns']) * 1e-9
            t1 = int(rows[i + 1]['timestamp_ns']) * 1e-9
            w0 = np.array([float(rows[i][c]) for c in ('gyro_x', 'gyro_y', 'gyro_z')])
            a0 = np.array([float(rows[i][c]) for c in ('accel_x', 'accel_y', 'accel_z')])
            cpi.feed_imu(t0, t1, w0, a0)
        return cpi

    def test_v1_matches_groundtruth(self):
        assert self.gt_v1 is not None, "V1 ground truth not available"
        cpi = self._run_python_v1()
        np.testing.assert_allclose(cpi.DT, self.gt_v1['DT'], atol=1e-12)
        np.testing.assert_allclose(
            cpi.alpha_tau, self.gt_v1['alpha_tau'], atol=1e-10
        )
        np.testing.assert_allclose(
            cpi.beta_tau, self.gt_v1['beta_tau'], atol=1e-10
        )
        np.testing.assert_allclose(
            cpi.q_k2tau, self.gt_v1['q_k2tau'], atol=1e-12
        )
        np.testing.assert_allclose(
            np.trace(cpi.P_meas), self.gt_v1['P_meas_trace'], atol=1e-14
        )
        np.testing.assert_allclose(
            np.diag(cpi.P_meas).tolist(), self.gt_v1['P_meas_diag'], atol=1e-14
        )

    def test_v2_matches_groundtruth(self):
        assert self.gt_v2 is not None, "V2 ground truth not available"
        cpi = self._run_python_v2()
        np.testing.assert_allclose(cpi.DT, self.gt_v2['DT'], atol=1e-12)
        np.testing.assert_allclose(
            cpi.alpha_tau, self.gt_v2['alpha_tau'], atol=1e-10
        )
        np.testing.assert_allclose(
            cpi.beta_tau, self.gt_v2['beta_tau'], atol=1e-10
        )
        np.testing.assert_allclose(
            cpi.q_k2tau, self.gt_v2['q_k2tau'], atol=1e-12
        )
        np.testing.assert_allclose(
            np.trace(cpi.P_meas), self.gt_v2['P_meas_trace'], atol=1e-14
        )
        np.testing.assert_allclose(
            np.diag(cpi.P_meas).tolist(), self.gt_v2['P_meas_diag'], atol=1e-14
        )


# ============================================================
# End-to-end pipeline tests
# ============================================================

class TestPipeline:
    @classmethod
    def setup_class(cls):
        result = subprocess.run(
            ['python3', '/app/process_imu.py'],
            capture_output=True, text=True, cwd='/app',
            timeout=60
        )
        cls.run_result = result
        cls.output_v1 = None
        cls.output_v2 = None
        v1_path = '/app/output/preintegrated_v1.json'
        v2_path = '/app/output/preintegrated_v2.json'
        if os.path.exists(v1_path):
            with open(v1_path) as f:
                cls.output_v1 = json.load(f)
        if os.path.exists(v2_path):
            with open(v2_path) as f:
                cls.output_v2 = json.load(f)

    def test_script_runs_successfully(self):
        assert self.run_result.returncode == 0, \
            f"process_imu.py failed:\n{self.run_result.stderr}"

    def test_v1_output_exists(self):
        assert self.output_v1 is not None, \
            "/app/output/preintegrated_v1.json not created"

    def test_v2_output_exists(self):
        assert self.output_v2 is not None, \
            "/app/output/preintegrated_v2.json not created"

    def test_v1_schema(self):
        d = self.output_v1
        assert isinstance(d['DT'], (int, float))
        assert len(d['alpha_tau']) == 3
        assert len(d['beta_tau']) == 3
        assert len(d['q_k2tau']) == 4
        assert isinstance(d['P_meas_trace'], (int, float))
        assert len(d['P_meas_diag']) == 15

    def test_v2_schema(self):
        d = self.output_v2
        assert isinstance(d['DT'], (int, float))
        assert len(d['alpha_tau']) == 3
        assert len(d['beta_tau']) == 3
        assert len(d['q_k2tau']) == 4
        assert isinstance(d['P_meas_trace'], (int, float))
        assert len(d['P_meas_diag']) == 15

    def test_dt_matches_csv(self):
        np.testing.assert_allclose(self.output_v1['DT'], 0.195, atol=1e-10)
        np.testing.assert_allclose(self.output_v2['DT'], 0.195, atol=1e-10)

    def test_quaternion_unit_norm(self):
        q1 = np.array(self.output_v1['q_k2tau'])
        np.testing.assert_allclose(np.linalg.norm(q1), 1.0, atol=1e-12)
        q2 = np.array(self.output_v2['q_k2tau'])
        np.testing.assert_allclose(np.linalg.norm(q2), 1.0, atol=1e-12)

    def test_covariance_positive(self):
        for label, d in [("V1", self.output_v1), ("V2", self.output_v2)]:
            assert d['P_meas_trace'] > 0, f"{label} trace should be positive"
            for i, val in enumerate(d['P_meas_diag']):
                assert val >= -1e-15, f"{label} diag[{i}] negative: {val}"

    def test_v1_v2_outputs_differ(self):
        """V1 and V2 pipeline outputs should differ."""
        assert not np.allclose(
            self.output_v1['alpha_tau'], self.output_v2['alpha_tau'], atol=1e-3
        )

    def test_pipeline_v1_self_consistency(self):
        """Pipeline V1 output matches direct CpiV1 computation."""
        with open('/app/data/sensor_config.json') as f:
            config = json.load(f)
        rows = []
        with open('/app/data/imu_sequence.csv') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        noise = config['noise_parameters']
        cpi = CpiV1(
            noise['gyroscope_noise_density'],
            noise['gyroscope_random_walk'],
            noise['accelerometer_noise_density'],
            noise['accelerometer_random_walk'],
            imu_avg=config['options'].get('imu_averaging', False)
        )
        bias = config['bias_linearization']
        cpi.set_linearization_points(
            np.array(bias['gyroscope']),
            np.array(bias['accelerometer'])
        )
        for i in range(len(rows) - 1):
            t0 = int(rows[i]['timestamp_ns']) * 1e-9
            t1 = int(rows[i + 1]['timestamp_ns']) * 1e-9
            w0 = np.array([float(rows[i][c]) for c in ('gyro_x', 'gyro_y', 'gyro_z')])
            a0 = np.array([float(rows[i][c]) for c in ('accel_x', 'accel_y', 'accel_z')])
            cpi.feed_imu(t0, t1, w0, a0)

        d = self.output_v1
        np.testing.assert_allclose(d['DT'], cpi.DT, atol=1e-12)
        np.testing.assert_allclose(d['alpha_tau'], cpi.alpha_tau, atol=1e-10)
        np.testing.assert_allclose(d['beta_tau'], cpi.beta_tau, atol=1e-10)
        np.testing.assert_allclose(d['q_k2tau'], cpi.q_k2tau, atol=1e-12)
