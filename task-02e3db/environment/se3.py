"""SE(3) Lie group utilities for pose graph optimization.

Conventions:
- Pose = (R, t) where R is 3x3 rotation, t is 3-vector.
- R transforms world to camera: p_cam = R @ p_world + t
- Tangent vector delta = [rho(3); omega(3)]
- Right-perturbation: T' = T * exp(delta)
"""
import numpy as np


def skew(v):
    """3-vector -> 3x3 skew-symmetric matrix."""
    return np.array([[0, -v[2], v[1]],
                     [v[2], 0, -v[0]],
                     [-v[1], v[0], 0]], dtype=np.float64)


def rodrigues(omega):
    """SO(3) exponential map: axis-angle 3-vector -> rotation matrix."""
    theta = np.linalg.norm(omega)
    if theta < 1e-12:
        return np.eye(3) + skew(omega)
    K = skew(omega / theta)
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def so3_log(R):
    """SO(3) logarithm map: rotation matrix -> axis-angle 3-vector."""
    cos_angle = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_angle)
    if theta < 1e-10:
        return np.array([R[2, 1] - R[1, 2],
                         R[0, 2] - R[2, 0],
                         R[1, 0] - R[0, 1]]) / 2.0
    if abs(theta - np.pi) < 1e-6:
        d = np.diag(R)
        k = np.argmax(d)
        v = np.zeros(3)
        v[k] = np.sqrt((d[k] + 1.0) / 2.0)
        for j in range(3):
            if j != k:
                v[j] = R[k, j] / (2.0 * v[k])
        return v * theta
    K = (R - R.T) / (2.0 * np.sin(theta))
    return np.array([K[2, 1], K[0, 2], K[1, 0]]) * theta


def left_jacobian_so3(omega):
    """Left Jacobian V of SO(3) for SE(3) exponential map."""
    theta = np.linalg.norm(omega)
    if theta < 1e-12:
        return np.eye(3) + 0.5 * skew(omega)
    K = skew(omega)
    return (np.eye(3)
            + (1.0 - np.cos(theta)) / theta**2 * K
            + (theta - np.sin(theta)) / theta**3 * (K @ K))


def left_jacobian_so3_inv(omega):
    """Inverse of left Jacobian V^{-1} of SO(3)."""
    theta = np.linalg.norm(omega)
    if theta < 1e-12:
        return np.eye(3) - 0.5 * skew(omega)
    K = skew(omega)
    st = np.sin(theta)
    if abs(st) < 1e-10:
        coeff = 1.0 / theta**2
    else:
        coeff = 1.0 / theta**2 - (1.0 + np.cos(theta)) / (2.0 * theta * st)
    return np.eye(3) - 0.5 * K + coeff * (K @ K)


def se3_exp(delta):
    """SE(3) exponential map: 6-vector [rho(3); omega(3)] -> (R, t)."""
    rho, omega = delta[:3], delta[3:]
    R = rodrigues(omega)
    V = left_jacobian_so3(omega)
    return R, V @ rho


def se3_log(R, t):
    """SE(3) logarithm map: (R, t) -> 6-vector [rho(3); omega(3)]."""
    omega = so3_log(R)
    V_inv = left_jacobian_so3_inv(omega)
    rho = V_inv @ t
    return np.concatenate([rho, omega])


def se3_retract(R, t, delta):
    """Right-perturbation retract: (R, t) * exp(delta) -> (R', t')."""
    dR, dt = se3_exp(delta)
    return R @ dR, R @ dt + t


def se3_inverse(R, t):
    """Inverse of SE(3) element: (R^T, -R^T @ t)."""
    R_inv = R.T
    return R_inv, -R_inv @ t


def se3_compose(Ra, ta, Rb, tb):
    """Compose SE(3) elements: T_a * T_b -> (Ra @ Rb, Ra @ tb + ta)."""
    return Ra @ Rb, Ra @ tb + ta
