#!/usr/bin/env python3
"""
Lie group-based differential IK with collision avoidance.

Implements SO(3)/SE(3) operations from their mathematical definitions
and a QP-based IK solver using MuJoCo for kinematics and collision queries.
"""

import numpy as np
import mujoco
from scipy.optimize import minimize as _scipy_minimize

_EPS = 1e-10


# =====================================================================
# SO(3)
# =====================================================================

def so3_skew(v):
    """3-D vector -> 3x3 skew-symmetric matrix."""
    return np.array(
        [[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]],
        dtype=np.float64,
    )


def so3_exp(omega):
    """SO(3) exponential map (Rodrigues)."""
    theta = np.linalg.norm(omega)
    if theta < _EPS:
        return np.eye(3, dtype=np.float64) + so3_skew(omega)
    K = so3_skew(omega / theta)
    return (
        np.eye(3, dtype=np.float64)
        + np.sin(theta) * K
        + (1.0 - np.cos(theta)) * (K @ K)
    )


def so3_log(R):
    """SO(3) logarithmic map."""
    cos_angle = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_angle)
    if theta < _EPS:
        return np.array(
            [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]
        ) / 2.0
    if abs(theta - np.pi) < 1e-6:
        S = R + np.eye(3)
        col = int(np.argmax(np.sum(S * S, axis=0)))
        v = S[:, col].copy()
        v /= np.linalg.norm(v)
        return theta * v
    return (
        theta
        / (2.0 * np.sin(theta))
        * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    )


def so3_left_jacobian(omega):
    """Left Jacobian of SO(3)."""
    theta = np.linalg.norm(omega)
    K = so3_skew(omega)
    t2 = theta * theta
    if theta < _EPS:
        return np.eye(3, dtype=np.float64) + 0.5 * K
    alpha = (1.0 - np.cos(theta)) / t2
    beta = (theta - np.sin(theta)) / (t2 * theta)
    return np.eye(3, dtype=np.float64) + alpha * K + beta * (K @ K)


def so3_left_jacobian_inv(omega):
    """Inverse of the SO(3) left Jacobian."""
    theta = np.linalg.norm(omega)
    K = so3_skew(omega)
    t2 = theta * theta
    if theta < _EPS:
        return np.eye(3, dtype=np.float64) - 0.5 * K
    beta = (1.0 / t2) * (
        1.0 - (theta * np.sin(theta)) / (2.0 * (1.0 - np.cos(theta)))
    )
    return np.eye(3, dtype=np.float64) - 0.5 * K + beta * (K @ K)


# =====================================================================
# SE(3)
# =====================================================================

def se3_exp(twist):
    """SE(3) exponential map."""
    v = twist[:3]
    omega = twist[3:]
    theta = np.linalg.norm(omega)
    R = so3_exp(omega)
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    if theta < _EPS:
        K = so3_skew(omega)
        V = np.eye(3, dtype=np.float64) + 0.5 * K
        T[:3, 3] = V @ v
    else:
        K = so3_skew(omega)
        t2 = theta * theta
        V = (
            np.eye(3, dtype=np.float64)
            + ((1.0 - np.cos(theta)) / t2) * K
            + ((theta - np.sin(theta)) / (t2 * theta)) * (K @ K)
        )
        T[:3, 3] = V @ v
    return T


def se3_log(T):
    """SE(3) logarithmic map."""
    R = T[:3, :3]
    t = T[:3, 3]
    omega = so3_log(R)
    theta = np.linalg.norm(omega)
    K = so3_skew(omega)
    K2 = K @ K
    t2 = theta * theta
    if theta < _EPS:
        V_inv = np.eye(3, dtype=np.float64) - 0.5 * K + (1.0 / 12.0) * K2
    else:
        ht = theta / 2.0
        V_inv = (
            np.eye(3, dtype=np.float64)
            - 0.5 * K
            + (1.0 - 0.5 * theta * np.cos(ht) / np.sin(ht)) / t2 * K2
        )
    twist = np.zeros(6, dtype=np.float64)
    twist[:3] = V_inv @ t
    twist[3:] = omega
    return twist


def se3_adjoint(T):
    """SE(3) adjoint representation (6x6)."""
    R = T[:3, :3]
    t = T[:3, 3]
    Ad = np.zeros((6, 6), dtype=np.float64)
    Ad[:3, :3] = R
    Ad[:3, 3:] = so3_skew(t) @ R
    Ad[3:, 3:] = R
    return Ad


def _se3_Q(twist):
    """Q-matrix for SE(3) left Jacobian (Eq. 180)."""
    v = twist[:3]
    omega = twist[3:]
    theta = np.linalg.norm(omega)
    t2 = theta * theta
    A = 0.5
    if t2 < _EPS:
        B = 1.0 / 6.0 + t2 / 120.0
        C = -1.0 / 24.0 + t2 / 720.0
        D = -1.0 / 60.0
    else:
        t4 = t2 * t2
        st = np.sin(theta)
        ct = np.cos(theta)
        B = (theta - st) / (t2 * theta)
        C = (1.0 - 0.5 * t2 - ct) / t4
        D = (2.0 * theta - 3.0 * st + theta * ct) / (2.0 * t4 * theta)
    V = so3_skew(v)
    W = so3_skew(omega)
    VW = V @ W
    WV = VW.T
    WVW = WV @ W
    VWW = VW @ W
    return (
        A * V
        + B * (WV + VW + WVW)
        - C * (VWW - VWW.T - 3.0 * WVW)
        + D * (WVW @ W + W @ WVW)
    )


def se3_left_jacobian(twist):
    """Left Jacobian of SE(3) (6x6)."""
    omega = twist[3:]
    if np.dot(omega, omega) < _EPS:
        return np.eye(6, dtype=np.float64)
    J = np.zeros((6, 6), dtype=np.float64)
    Q = _se3_Q(twist)
    Jso3 = so3_left_jacobian(omega)
    J[:3, :3] = Jso3
    J[:3, 3:] = Q
    J[3:, 3:] = Jso3
    return J


def se3_left_jacobian_inv(twist):
    """Inverse of the SE(3) left Jacobian (6x6)."""
    omega = twist[3:]
    if np.dot(omega, omega) < _EPS:
        return np.eye(6, dtype=np.float64)
    Ji = np.zeros((6, 6), dtype=np.float64)
    Q = _se3_Q(twist)
    Jso3i = so3_left_jacobian_inv(omega)
    Ji[:3, :3] = Jso3i
    Ji[:3, 3:] = -Jso3i @ Q @ Jso3i
    Ji[3:, 3:] = Jso3i
    return Ji


# =====================================================================
# IK building blocks
# =====================================================================

def compute_frame_error(T_current, T_target):
    """Body-frame twist error: log(T_current^{-1} T_target)."""
    T_ct = np.linalg.inv(T_current) @ T_target
    return se3_log(T_ct)


def compute_body_jacobian(model, data, site_id):
    """Body-frame Jacobian for a MuJoCo site (6 x nv)."""
    jacp = np.zeros((3, model.nv))
    jacr = np.zeros((3, model.nv))
    mujoco.mj_jacSite(model, data, jacp, jacr, site_id)
    J_world = np.vstack([jacp, jacr])

    R_ws = data.site_xmat[site_id].reshape(3, 3)
    t_ws = data.site_xpos[site_id]
    R_sw = R_ws.T
    t_sw = -R_sw @ t_ws

    Ad_sw = np.zeros((6, 6), dtype=np.float64)
    Ad_sw[:3, :3] = R_sw
    Ad_sw[:3, 3:] = so3_skew(t_sw) @ R_sw
    Ad_sw[3:, 3:] = R_sw

    return Ad_sw @ J_world


def compute_collision_constraint(
    model, data, geom1_id, geom2_id, min_dist, dt, gain, detection_dist
):
    """Collision-avoidance inequality for one geom pair."""
    fromto = np.zeros(6, dtype=np.float64)
    dist = mujoco.mj_geomDistance(
        model, data, geom1_id, geom2_id, detection_dist, fromto
    )

    if dist >= detection_dist - 1e-6:
        return np.zeros(model.nv, dtype=np.float64), np.inf

    normal = fromto[3:] - fromto[:3]
    norm_val = np.linalg.norm(normal)
    if norm_val < 1e-12:
        return np.zeros(model.nv, dtype=np.float64), np.inf
    normal /= norm_val

    body1 = model.geom_bodyid[geom1_id]
    body2 = model.geom_bodyid[geom2_id]
    jac1 = np.zeros((3, model.nv))
    jac2 = np.zeros((3, model.nv))
    mujoco.mj_jac(model, data, jac2, None, fromto[3:], body2)
    mujoco.mj_jac(model, data, jac1, None, fromto[:3], body1)

    g_row = normal @ (jac2 - jac1)
    sign = -1.0 if dist >= 0 else 1.0
    g_row *= sign

    if dist > min_dist:
        h_val = gain * (dist - min_dist) / dt
    else:
        h_val = 0.0

    return g_row, h_val


# =====================================================================
# IK solver
# =====================================================================

def solve_ik_step(
    model,
    data,
    site_id,
    T_target,
    dt,
    damping,
    collision_pairs,
    min_collision_dist,
    gain,
):
    """One QP-based differential IK step with collision avoidance.

    Returns velocity v = dq / dt.
    """
    # Current EE transform
    T_cur = np.eye(4, dtype=np.float64)
    T_cur[:3, :3] = data.site_xmat[site_id].reshape(3, 3)
    T_cur[:3, 3] = data.site_xpos[site_id]

    # Error and Jacobian in body frame
    error = compute_frame_error(T_cur, T_target)
    J = compute_body_jacobian(model, data, site_id)

    nv = model.nv
    H = J.T @ J + damping * np.eye(nv, dtype=np.float64)
    c = -gain * (J.T @ error)

    # Collision constraints
    G_list = []
    h_list = []
    for g1, g2 in collision_pairs:
        g_row, h_val = compute_collision_constraint(
            model, data, g1, g2, min_collision_dist, dt, gain, 1.0
        )
        if np.isfinite(h_val):
            G_list.append(g_row)
            h_list.append(h_val)

    if not G_list:
        # Unconstrained — solve directly
        dq = np.linalg.solve(H, -c)
    else:
        G = np.array(G_list)
        h_arr = np.array(h_list)

        ineqs = []
        for i in range(G.shape[0]):
            ineqs.append(
                {
                    "type": "ineq",
                    "fun": lambda x, ii=i: h_arr[ii] - G[ii] @ x,
                    "jac": lambda x, ii=i: -G[ii],
                }
            )

        res = _scipy_minimize(
            fun=lambda x: 0.5 * x @ H @ x + c @ x,
            x0=np.zeros(nv),
            jac=lambda x: H @ x + c,
            constraints=ineqs,
            method="SLSQP",
            options={"ftol": 1e-12, "maxiter": 300},
        )
        dq = res.x

    return dq / dt
