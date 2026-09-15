"""Rotation and pose utility functions for trajectory evaluation."""

import numpy as np


def rotation_matrix_from_axis_angle(axis, angle):
    """Create rotation matrix from axis-angle representation (Rodrigues)."""
    axis = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def rotmat_to_quaternion(R):
    """Convert 3x3 rotation matrix to quaternion [qx, qy, qz, qw]."""
    tr = np.trace(R)
    if tr > 0:
        s = 0.5 / np.sqrt(tr + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    return np.array([x, y, z, w])


def validate_rotation_matrix(R, tol=1e-6):
    """Check if R is a valid SO(3) rotation matrix."""
    if not np.allclose(R @ R.T, np.eye(3), atol=tol):
        return False
    if not np.isclose(np.linalg.det(R), 1.0, atol=tol):
        return False
    return True


def invert_se3(R, t):
    """Invert an SE(3) transformation (R, t)."""
    R_inv = R.T
    t_inv = -R_inv @ t
    return R_inv, t_inv


def compose_se3(R1, t1, R2, t2):
    """Compose two SE(3) transformations: T1 * T2."""
    R = R1 @ R2
    t = R1 @ t2 + t1
    return R, t
