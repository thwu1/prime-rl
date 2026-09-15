
"""
IMU Continuous Preintegration Models 1 and 2
using JPL quaternion convention.

Model 1: piecewise constant measurement assumption (CpiV1)
Model 2: piecewise constant local acceleration assumption (CpiV2)

Reference: Eckenhoff, Geneva, Huang. "Continuous Preintegration Theory for
Graph-based Visual-Inertial Navigation." IJRR 2019.
"""

import numpy as np


def skew_x(w):
    """Skew-symmetric matrix from 3-vector."""
    w = np.asarray(w, dtype=float)
    return np.array([
        [0.0, -w[2], w[1]],
        [w[2], 0.0, -w[0]],
        [-w[1], w[0], 0.0],
    ])


def quat_2_rot(q):
    """Convert JPL quaternion [qx,qy,qz,q4] to 3x3 rotation matrix."""
    q = np.asarray(q, dtype=float)
    qv = q[:3]
    q4 = q[3]
    qx = skew_x(qv)
    return (2.0 * q4 * q4 - 1.0) * np.eye(3) - 2.0 * q4 * qx + 2.0 * np.outer(qv, qv)


def rot_2_quat(R):
    """Convert 3x3 rotation matrix to JPL quaternion [qx,qy,qz,q4]."""
    R = np.asarray(R, dtype=float)
    q = np.zeros(4)
    T = R[0, 0] + R[1, 1] + R[2, 2]

    if R[0, 0] >= T and R[0, 0] >= R[1, 1] and R[0, 0] >= R[2, 2]:
        q[0] = np.sqrt((1.0 + 2.0 * R[0, 0] - T) / 4.0)
        q[1] = (R[0, 1] + R[1, 0]) / (4.0 * q[0])
        q[2] = (R[0, 2] + R[2, 0]) / (4.0 * q[0])
        q[3] = (R[1, 2] - R[2, 1]) / (4.0 * q[0])
    elif R[1, 1] >= T and R[1, 1] >= R[0, 0] and R[1, 1] >= R[2, 2]:
        q[1] = np.sqrt((1.0 + 2.0 * R[1, 1] - T) / 4.0)
        q[0] = (R[0, 1] + R[1, 0]) / (4.0 * q[1])
        q[2] = (R[1, 2] + R[2, 1]) / (4.0 * q[1])
        q[3] = (R[2, 0] - R[0, 2]) / (4.0 * q[1])
    elif R[2, 2] >= T and R[2, 2] >= R[0, 0] and R[2, 2] >= R[1, 1]:
        q[2] = np.sqrt((1.0 + 2.0 * R[2, 2] - T) / 4.0)
        q[0] = (R[0, 2] + R[2, 0]) / (4.0 * q[2])
        q[1] = (R[1, 2] + R[2, 1]) / (4.0 * q[2])
        q[3] = (R[0, 1] - R[1, 0]) / (4.0 * q[2])
    else:
        q[3] = np.sqrt((1.0 + T) / 4.0)
        q[0] = (R[1, 2] - R[2, 1]) / (4.0 * q[3])
        q[1] = (R[2, 0] - R[0, 2]) / (4.0 * q[3])
        q[2] = (R[0, 1] - R[1, 0]) / (4.0 * q[3])

    if q[3] < 0:
        q = -q
    return q / np.linalg.norm(q)


def quat_multiply(q, p):
    """Multiply two JPL quaternions: q otimes p."""
    q = np.asarray(q, dtype=float)
    p = np.asarray(p, dtype=float)
    Qm = np.zeros((4, 4))
    Qm[:3, :3] = q[3] * np.eye(3) - skew_x(q[:3])
    Qm[:3, 3] = q[:3]
    Qm[3, :3] = -q[:3]
    Qm[3, 3] = q[3]
    qt = Qm @ p
    if qt[3] < 0:
        qt = -qt
    return qt / np.linalg.norm(qt)


def exp_so3(w):
    """SO(3) exponential map (Rodrigues formula)."""
    w = np.asarray(w, dtype=float)
    theta = np.linalg.norm(w)
    wx = skew_x(w)
    if theta < 1e-7:
        A, B = 1.0, 0.5
    else:
        A = np.sin(theta) / theta
        B = (1.0 - np.cos(theta)) / (theta * theta)
    if theta == 0.0:
        return np.eye(3)
    return np.eye(3) + A * wx + B * (wx @ wx)


def log_so3(R):
    """SO(3) logarithm map."""
    R = np.asarray(R, dtype=float)
    tr = np.trace(R)

    if tr + 1.0 < 1e-10:
        if abs(R[2, 2] + 1.0) > 1e-5:
            omega = (np.pi / np.sqrt(2.0 + 2.0 * R[2, 2])) * np.array(
                [R[0, 2], R[1, 2], 1.0 + R[2, 2]]
            )
        elif abs(R[1, 1] + 1.0) > 1e-5:
            omega = (np.pi / np.sqrt(2.0 + 2.0 * R[1, 1])) * np.array(
                [R[0, 1], 1.0 + R[1, 1], R[2, 1]]
            )
        else:
            omega = (np.pi / np.sqrt(2.0 + 2.0 * R[0, 0])) * np.array(
                [1.0 + R[0, 0], R[1, 0], R[2, 0]]
            )
    else:
        tr_3 = tr - 3.0
        if tr_3 < -1e-7:
            theta = np.arccos(np.clip((tr - 1.0) / 2.0, -1.0, 1.0))
            magnitude = theta / (2.0 * np.sin(theta))
        else:
            magnitude = 0.5 - tr_3 / 12.0
        omega = magnitude * np.array(
            [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]
        )
    return omega


class CpiV1:
    """
    Model 1 continuous preintegration (piecewise constant measurement assumption).
    """

    def __init__(self, sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg=False):
        self.imu_avg = imu_avg

        # Continuous-time noise covariance (12x12)
        self.Q_c = np.zeros((12, 12))
        self.Q_c[0:3, 0:3] = sigma_w ** 2 * np.eye(3)
        self.Q_c[3:6, 3:6] = sigma_wb ** 2 * np.eye(3)
        self.Q_c[6:9, 6:9] = sigma_a ** 2 * np.eye(3)
        self.Q_c[9:12, 9:12] = sigma_ab ** 2 * np.eye(3)

        # Unit vectors and their skew-symmetrics
        self.e_1 = np.array([1.0, 0.0, 0.0])
        self.e_2 = np.array([0.0, 1.0, 0.0])
        self.e_3 = np.array([0.0, 0.0, 1.0])
        self.e_1x = skew_x(self.e_1)
        self.e_2x = skew_x(self.e_2)
        self.e_3x = skew_x(self.e_3)

        # Measurement means
        self.DT = 0.0
        self.alpha_tau = np.zeros(3)
        self.beta_tau = np.zeros(3)
        self.R_k2tau = np.eye(3)
        self.q_k2tau = np.array([0.0, 0.0, 0.0, 1.0])

        # Bias Jacobians
        self.J_q = np.zeros((3, 3))
        self.J_a = np.zeros((3, 3))
        self.J_b = np.zeros((3, 3))
        self.H_a = np.zeros((3, 3))
        self.H_b = np.zeros((3, 3))

        # Measurement covariance
        self.P_meas = np.zeros((15, 15))

        # Linearization points
        self.b_w_lin = np.zeros(3)
        self.b_a_lin = np.zeros(3)

    def set_linearization_points(self, b_w_lin, b_a_lin):
        self.b_w_lin = np.asarray(b_w_lin, dtype=float).copy()
        self.b_a_lin = np.asarray(b_a_lin, dtype=float).copy()

    def feed_imu(self, t_0, t_1, w_m_0, a_m_0, w_m_1=None, a_m_1=None):
        w_m_0 = np.asarray(w_m_0, dtype=float)
        a_m_0 = np.asarray(a_m_0, dtype=float)
        w_m_1 = np.zeros(3) if w_m_1 is None else np.asarray(w_m_1, dtype=float)
        a_m_1 = np.zeros(3) if a_m_1 is None else np.asarray(a_m_1, dtype=float)

        dt = t_1 - t_0
        self.DT += dt
        if dt == 0.0:
            return

        # Bias-corrected measurements
        w_hat = w_m_0 - self.b_w_lin
        a_hat = a_m_0 - self.b_a_lin

        if self.imu_avg:
            w_hat = 0.5 * (w_hat + (w_m_1 - self.b_w_lin))
            a_hat = 0.5 * (a_hat + (a_m_1 - self.b_a_lin))

        w_hatdt = w_hat * dt
        w1, w2, w3 = w_hat[0], w_hat[1], w_hat[2]
        mag_w = np.linalg.norm(w_hat)
        w_dt = mag_w * dt
        small_w = mag_w < 0.008726646

        dt2 = dt * dt
        cos_wt = np.cos(w_dt)
        sin_wt = np.sin(w_dt)

        wx = skew_x(w_hat)
        ax = skew_x(a_hat)
        wtx = skew_x(w_hatdt)
        wx2 = wx @ wx
        I3 = np.eye(3)

        # MEASUREMENT MEANS
        if small_w:
            R_tau2tau1 = I3 - dt * wx + (dt2 / 2.0) * wx2
        else:
            R_tau2tau1 = (
                I3
                - (sin_wt / mag_w) * wx
                + ((1.0 - cos_wt) / (mag_w ** 2)) * wx2
            )

        R_k2tau1 = R_tau2tau1 @ self.R_k2tau
        R_tau12k = R_k2tau1.T

        if small_w:
            f1 = -(dt ** 3) / 3.0
            f2 = (dt ** 4) / 8.0
            f3 = -dt2 / 2.0
            f4 = (dt ** 3) / 6.0
        else:
            f1 = (w_dt * cos_wt - sin_wt) / (mag_w ** 3)
            f2 = (w_dt ** 2 - 2.0 * cos_wt - 2.0 * w_dt * sin_wt + 2.0) / (
                2.0 * mag_w ** 4
            )
            f3 = -(1.0 - cos_wt) / (mag_w ** 2)
            f4 = (w_dt - sin_wt) / (mag_w ** 3)

        alpha_arg = (dt2 / 2.0) * I3 + f1 * wx + f2 * wx2
        beta_arg = dt * I3 + f3 * wx + f4 * wx2

        H_al = R_tau12k @ alpha_arg
        H_be = R_tau12k @ beta_arg

        self.alpha_tau += self.beta_tau * dt + H_al @ a_hat
        self.beta_tau += H_be @ a_hat

        # BIAS JACOBIANS (ANALYTICAL)

        # Right Jacobian Jr(w_hat * dt)
        if small_w:
            Jr = I3 - 0.5 * wtx + (1.0 / 6.0) * (wtx @ wtx)
        else:
            Jr = (
                I3
                - ((1.0 - cos_wt) / (w_dt ** 2)) * wtx
                + ((w_dt - sin_wt) / (w_dt ** 3)) * (wtx @ wtx)
            )

        # Update orientation Jacobian w.r.t. gyro bias
        self.J_q = R_tau2tau1 @ self.J_q + Jr * dt

        # Update accel bias Jacobians
        self.H_a -= H_al
        self.H_a += dt * self.H_b  # uses old H_b
        self.H_b -= H_be

        # Derivatives of R_tau12k w.r.t. b_w components (uses updated J_q)
        dR_bw = [
            -R_tau12k @ skew_x(self.J_q @ self.e_1),
            -R_tau12k @ skew_x(self.J_q @ self.e_2),
            -R_tau12k @ skew_x(self.J_q @ self.e_3),
        ]

        # Derivatives of f-functions w.r.t. b_w components
        if small_w:
            df1_dw = w_hat * (-(dt ** 5) / 15.0)
            df2_dw = w_hat * ((dt ** 6) / 72.0)
            df3_dw = w_hat * (-(dt ** 4) / 12.0)
            df4_dw = w_hat * ((dt ** 5) / 60.0)
        else:
            df1_dw = w_hat * (
                (w_dt ** 2 * sin_wt - 3.0 * sin_wt + 3.0 * w_dt * cos_wt)
                / (mag_w ** 5)
            )
            df2_dw = w_hat * (
                (
                    w_dt ** 2
                    - 4.0 * cos_wt
                    - 4.0 * w_dt * sin_wt
                    + w_dt ** 2 * cos_wt
                    + 4.0
                )
                / (mag_w ** 6)
            )
            df3_dw = w_hat * (
                (2.0 * (cos_wt - 1.0) + w_dt * sin_wt) / (mag_w ** 4)
            )
            df4_dw = w_hat * (
                (2.0 * w_dt + w_dt * cos_wt - 3.0 * sin_wt) / (mag_w ** 5)
            )

        exs = [self.e_1x, self.e_2x, self.e_3x]

        # Update gyro bias Jacobians for alpha and beta
        self.J_a += self.J_b * dt  # uses old J_b

        for i in range(3):
            self.J_a[:, i] += (
                dR_bw[i] @ alpha_arg
                + R_tau12k
                @ (
                    df1_dw[i] * wx
                    - f1 * exs[i]
                    + df2_dw[i] * wx2
                    - f2 * (exs[i] @ wx + wx @ exs[i])
                )
            ) @ a_hat

            self.J_b[:, i] += (
                dR_bw[i] @ beta_arg
                + R_tau12k
                @ (
                    df3_dw[i] * wx
                    - f3 * exs[i]
                    + df4_dw[i] * wx2
                    - f4 * (exs[i] @ wx + wx @ exs[i])
                )
            ) @ a_hat

        # MEASUREMENT COVARIANCE (RK4)

        # Mid-point rotation
        if small_w:
            half = 0.5 * dt
            R_mid_loc = I3 - half * wx + (half ** 2 / 2.0) * wx2
        else:
            R_mid_loc = (
                I3
                - (np.sin(mag_w * 0.5 * dt) / mag_w) * wx
                + ((1.0 - np.cos(mag_w * 0.5 * dt)) / (mag_w ** 2)) * wx2
            )
        R_mid = R_mid_loc @ self.R_k2tau

        # --- k1 ---
        F1 = np.zeros((15, 15))
        F1[0:3, 0:3] = -wx
        F1[0:3, 3:6] = -I3
        F1[6:9, 0:3] = -self.R_k2tau.T @ ax
        F1[6:9, 9:12] = -self.R_k2tau.T
        F1[12:15, 6:9] = I3

        G1 = np.zeros((15, 12))
        G1[0:3, 0:3] = -I3
        G1[3:6, 3:6] = I3
        G1[6:9, 6:9] = -self.R_k2tau.T
        G1[9:12, 9:12] = I3

        Pd1 = F1 @ self.P_meas + self.P_meas @ F1.T + G1 @ self.Q_c @ G1.T

        # --- k2 ---
        F2 = np.zeros((15, 15))
        F2[0:3, 0:3] = -wx
        F2[0:3, 3:6] = -I3
        F2[6:9, 0:3] = -R_mid.T @ ax
        F2[6:9, 9:12] = -R_mid.T
        F2[12:15, 6:9] = I3

        G2 = np.zeros((15, 12))
        G2[0:3, 0:3] = -I3
        G2[3:6, 3:6] = I3
        G2[6:9, 6:9] = -R_mid.T
        G2[9:12, 9:12] = I3

        P_k2 = self.P_meas + Pd1 * dt / 2.0
        Pd2 = F2 @ P_k2 + P_k2 @ F2.T + G2 @ self.Q_c @ G2.T

        # --- k3 (same F, G as k2) ---
        P_k3 = self.P_meas + Pd2 * dt / 2.0
        Pd3 = F2 @ P_k3 + P_k3 @ F2.T + G2 @ self.Q_c @ G2.T

        # --- k4 ---
        F4 = np.zeros((15, 15))
        F4[0:3, 0:3] = -wx
        F4[0:3, 3:6] = -I3
        F4[6:9, 0:3] = -R_k2tau1.T @ ax
        F4[6:9, 9:12] = -R_k2tau1.T
        F4[12:15, 6:9] = I3

        G4 = np.zeros((15, 12))
        G4[0:3, 0:3] = -I3
        G4[3:6, 3:6] = I3
        G4[6:9, 6:9] = -R_k2tau1.T
        G4[9:12, 9:12] = I3

        P_k4 = self.P_meas + Pd3 * dt
        Pd4 = F4 @ P_k4 + P_k4 @ F4.T + G4 @ self.Q_c @ G4.T

        # Combine RK4
        self.P_meas += (dt / 6.0) * (Pd1 + 2.0 * Pd2 + 2.0 * Pd3 + Pd4)
        self.P_meas = 0.5 * (self.P_meas + self.P_meas.T)

        # Update rotation state (must wait until after covariance uses old R_k2tau)
        self.R_k2tau = R_k2tau1
        self.q_k2tau = rot_2_quat(self.R_k2tau)


class CpiV2:
    """
    Model 2 continuous preintegration (piecewise constant local acceleration assumption).

    Uses gravity compensation in the local acceleration, a 21x21 extended covariance
    with clone-and-marginalize, and propagates bias Jacobians via the discrete
    state transition matrix (RK4 numerical integration).
    """

    def __init__(self, sigma_w, sigma_wb, sigma_a, sigma_ab, imu_avg=False):
        self.imu_avg = imu_avg

        self.Q_c = np.zeros((12, 12))
        self.Q_c[0:3, 0:3] = sigma_w ** 2 * np.eye(3)
        self.Q_c[3:6, 3:6] = sigma_wb ** 2 * np.eye(3)
        self.Q_c[6:9, 6:9] = sigma_a ** 2 * np.eye(3)
        self.Q_c[9:12, 9:12] = sigma_ab ** 2 * np.eye(3)

        self.e_1 = np.array([1.0, 0.0, 0.0])
        self.e_2 = np.array([0.0, 1.0, 0.0])
        self.e_3 = np.array([0.0, 0.0, 1.0])
        self.e_1x = skew_x(self.e_1)
        self.e_2x = skew_x(self.e_2)
        self.e_3x = skew_x(self.e_3)

        # Measurement means
        self.DT = 0.0
        self.alpha_tau = np.zeros(3)
        self.beta_tau = np.zeros(3)
        self.R_k2tau = np.eye(3)
        self.q_k2tau = np.array([0.0, 0.0, 0.0, 1.0])

        # Bias Jacobians (extracted from state transition)
        self.J_q = np.zeros((3, 3))
        self.J_a = np.zeros((3, 3))
        self.J_b = np.zeros((3, 3))
        self.H_a = np.zeros((3, 3))
        self.H_b = np.zeros((3, 3))
        self.O_a = np.zeros((3, 3))
        self.O_b = np.zeros((3, 3))

        # Measurement covariance
        self.P_meas = np.zeros((15, 15))

        # Extended 21x21 covariance and state transition
        self.P_big = np.zeros((21, 21))
        self.Discrete_J_b = np.eye(21)

        # Linearization points
        self.b_w_lin = np.zeros(3)
        self.b_a_lin = np.zeros(3)
        self.q_k_lin = np.array([0.0, 0.0, 0.0, 1.0])
        self.grav = np.zeros(3)

    def set_linearization_points(self, b_w_lin, b_a_lin, q_k_lin, grav):
        self.b_w_lin = np.asarray(b_w_lin, dtype=float).copy()
        self.b_a_lin = np.asarray(b_a_lin, dtype=float).copy()
        self.q_k_lin = np.asarray(q_k_lin, dtype=float).copy()
        self.grav = np.asarray(grav, dtype=float).copy()

    def feed_imu(self, t_0, t_1, w_m_0, a_m_0, w_m_1=None, a_m_1=None):
        w_m_0 = np.asarray(w_m_0, dtype=float)
        a_m_0 = np.asarray(a_m_0, dtype=float)
        w_m_1 = np.zeros(3) if w_m_1 is None else np.asarray(w_m_1, dtype=float)
        a_m_1 = np.zeros(3) if a_m_1 is None else np.asarray(a_m_1, dtype=float)

        dt = t_1 - t_0
        self.DT += dt
        if dt == 0.0:
            return

        # Bias-corrected gyro
        w_hat = w_m_0 - self.b_w_lin

        # Gravity rotated into body frame
        R_G_to_k = quat_2_rot(self.q_k_lin)
        g_k = R_G_to_k @ self.grav

        # Local acceleration with gravity compensation
        a_hat = a_m_0 - self.b_a_lin - self.R_k2tau @ g_k

        # Average gyro if requested (before rotation update)
        if self.imu_avg:
            w_hat = 0.5 * (w_hat + (w_m_1 - self.b_w_lin))

        w_hatdt = w_hat * dt
        mag_w = np.linalg.norm(w_hat)
        w_dt = mag_w * dt
        small_w = mag_w < 0.008726646

        dt2 = dt * dt
        cos_wt = np.cos(w_dt)
        sin_wt = np.sin(w_dt)
        I3 = np.eye(3)
        wx = skew_x(w_hat)
        wtx = skew_x(w_hatdt)
        wx2 = wx @ wx

        # Relative rotation
        if small_w:
            R_tau2tau1 = I3 - dt * wx + (dt2 / 2.0) * wx2
        else:
            R_tau2tau1 = (
                I3
                - (sin_wt / mag_w) * wx
                + ((1.0 - cos_wt) / mag_w ** 2) * wx2
            )

        R_k2tau1 = R_tau2tau1 @ self.R_k2tau
        R_tau12k = R_k2tau1.T

        # Average LOCAL acceleration AFTER rotation update (Model 2 convention)
        if self.imu_avg:
            a_hat += a_m_1 - self.b_a_lin - R_k2tau1 @ g_k
            a_hat = 0.5 * a_hat

        ax = skew_x(a_hat)

        # f-coefficients (same formulas as Model 1)
        if small_w:
            f1 = -(dt ** 3) / 3.0
            f2 = (dt ** 4) / 8.0
            f3 = -dt2 / 2.0
            f4 = (dt ** 3) / 6.0
        else:
            f1 = (w_dt * cos_wt - sin_wt) / mag_w ** 3
            f2 = (w_dt ** 2 - 2.0 * cos_wt - 2.0 * w_dt * sin_wt + 2.0) / (
                2.0 * mag_w ** 4
            )
            f3 = -(1.0 - cos_wt) / mag_w ** 2
            f4 = (w_dt - sin_wt) / mag_w ** 3

        alpha_arg = (dt2 / 2.0) * I3 + f1 * wx + f2 * wx2
        beta_arg = dt * I3 + f3 * wx + f4 * wx2

        H_al = R_tau12k @ alpha_arg
        H_be = R_tau12k @ beta_arg

        # Update measurement means
        self.alpha_tau += self.beta_tau * dt + H_al @ a_hat
        self.beta_tau += H_be @ a_hat

        # ================================================================
        # MEASUREMENT COVARIANCE AND STATE TRANSITION (21x21 RK4)
        # ================================================================

        # Midpoint rotation
        dt_mid = dt / 2.0
        w_dt_mid = mag_w * dt_mid
        if small_w:
            R_mid_loc = I3 - dt_mid * wx + (dt_mid ** 2 / 2.0) * wx2
        else:
            R_mid_loc = (
                I3
                - (np.sin(w_dt_mid) / mag_w) * wx
                + ((1.0 - np.cos(w_dt_mid)) / mag_w ** 2) * wx2
            )
        R_mid = R_mid_loc @ self.R_k2tau

        # Gravity vector in body frame at time k->tau
        g_body_k2tau = self.R_k2tau @ g_k

        I21 = np.eye(21)

        # --- k1 ---
        F1 = np.zeros((21, 21))
        F1[0:3, 0:3] = -wx
        F1[0:3, 3:6] = -I3
        F1[6:9, 0:3] = -self.R_k2tau.T @ ax
        F1[6:9, 9:12] = -self.R_k2tau.T
        F1[6:9, 15:18] = -self.R_k2tau.T @ skew_x(g_body_k2tau)
        F1[6:9, 18:21] = -self.R_k2tau.T @ self.R_k2tau @ skew_x(g_k)
        F1[12:15, 6:9] = I3

        G1 = np.zeros((21, 12))
        G1[0:3, 0:3] = -I3
        G1[3:6, 3:6] = I3
        G1[6:9, 6:9] = -self.R_k2tau.T
        G1[9:12, 9:12] = I3

        Phi_dot_k1 = F1.copy()
        P_dot_k1 = F1 @ self.P_big + self.P_big @ F1.T + G1 @ self.Q_c @ G1.T

        # --- k2 ---
        F2 = np.zeros((21, 21))
        F2[0:3, 0:3] = -wx
        F2[0:3, 3:6] = -I3
        F2[6:9, 0:3] = -R_mid.T @ ax
        F2[6:9, 9:12] = -R_mid.T
        F2[6:9, 15:18] = -R_mid.T @ skew_x(g_body_k2tau)
        F2[6:9, 18:21] = -R_mid.T @ self.R_k2tau @ skew_x(g_k)
        F2[12:15, 6:9] = I3

        G2 = np.zeros((21, 12))
        G2[0:3, 0:3] = -I3
        G2[3:6, 3:6] = I3
        G2[6:9, 6:9] = -R_mid.T
        G2[9:12, 9:12] = I3

        Phi_k2 = I21 + Phi_dot_k1 * dt_mid
        P_k2 = self.P_big + P_dot_k1 * dt_mid
        Phi_dot_k2 = F2 @ Phi_k2
        P_dot_k2 = F2 @ P_k2 + P_k2 @ F2.T + G2 @ self.Q_c @ G2.T

        # --- k3 (same F,G as k2) ---
        Phi_k3 = I21 + Phi_dot_k2 * dt_mid
        P_k3 = self.P_big + P_dot_k2 * dt_mid
        Phi_dot_k3 = F2 @ Phi_k3
        P_dot_k3 = F2 @ P_k3 + P_k3 @ F2.T + G2 @ self.Q_c @ G2.T

        # --- k4 ---
        F4 = np.zeros((21, 21))
        F4[0:3, 0:3] = -wx
        F4[0:3, 3:6] = -I3
        F4[6:9, 0:3] = -R_k2tau1.T @ ax
        F4[6:9, 9:12] = -R_k2tau1.T
        F4[6:9, 15:18] = -R_k2tau1.T @ skew_x(g_body_k2tau)
        F4[6:9, 18:21] = -R_k2tau1.T @ self.R_k2tau @ skew_x(g_k)
        F4[12:15, 6:9] = I3

        G4 = np.zeros((21, 12))
        G4[0:3, 0:3] = -I3
        G4[3:6, 3:6] = I3
        G4[6:9, 6:9] = -R_k2tau1.T
        G4[9:12, 9:12] = I3

        Phi_k4 = I21 + Phi_dot_k3 * dt
        P_k4 = self.P_big + P_dot_k3 * dt
        Phi_dot_k4 = F4 @ Phi_k4
        P_dot_k4 = F4 @ P_k4 + P_k4 @ F4.T + G4 @ self.Q_c @ G4.T

        # Combine RK4
        self.P_big += (dt / 6.0) * (P_dot_k1 + 2.0 * P_dot_k2 + 2.0 * P_dot_k3 + P_dot_k4)
        self.P_big = 0.5 * (self.P_big + self.P_big.T)

        Phi = I21 + (dt / 6.0) * (
            Phi_dot_k1 + 2.0 * Phi_dot_k2 + 2.0 * Phi_dot_k3 + Phi_dot_k4
        )

        # ================================================================
        # CLONE TO NEW SAMPLE TIME AND MARGINALIZE OLD SAMPLE TIME
        # ================================================================

        B_k = np.eye(21)
        B_k[15:18, 15:18] = np.zeros((3, 3))
        B_k[15:18, 0:3] = np.eye(3)

        self.P_big = B_k @ self.P_big @ B_k.T
        self.P_big = 0.5 * (self.P_big + self.P_big.T)
        self.Discrete_J_b = B_k @ Phi @ self.Discrete_J_b

        # Extract measurement covariance (top 15x15)
        self.P_meas = self.P_big[0:15, 0:15].copy()

        # Extract Jacobians from state transition matrix
        # Note: J_q sign flip to match Model 1 convention
        self.J_q = -self.Discrete_J_b[0:3, 3:6].copy()
        self.J_a = self.Discrete_J_b[12:15, 3:6].copy()
        self.J_b = self.Discrete_J_b[6:9, 3:6].copy()
        self.H_a = self.Discrete_J_b[12:15, 9:12].copy()
        self.H_b = self.Discrete_J_b[6:9, 9:12].copy()
        self.O_a = self.Discrete_J_b[12:15, 18:21].copy()
        self.O_b = self.Discrete_J_b[6:9, 18:21].copy()

        # Update rotation state
        self.R_k2tau = R_k2tau1
        self.q_k2tau = rot_2_quat(self.R_k2tau)
