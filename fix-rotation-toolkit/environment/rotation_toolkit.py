"""
3D Rotation Toolkit
===================
A library for working with 3D rotation representations, including:
- Quaternion <-> Rotation Matrix conversions
- Axis-Angle <-> Rotation Matrix conversions
- 6D rotation representation (Zhou et al. 2019)
- Geodesic distance on SO(3)
- SLERP interpolation between rotations
- Karcher (geodesic) mean of rotations
- Projection to nearest rotation matrix via SVD

All functions operate on numpy arrays.
Quaternion convention: (w, x, y, z) with w as the scalar/real part.
"""

import numpy as np


def quaternion_to_matrix(q):
    """Convert unit quaternion(s) to rotation matrix/matrices.

    Quaternion format: (w, x, y, z) with w being the scalar part.
    Input quaternions are normalized internally.

    Args:
        q: array of shape (4,) for single quaternion or (N, 4) for batch

    Returns:
        Rotation matrix of shape (3, 3) or (N, 3, 3)
    """
    q = np.asarray(q, dtype=np.float64)
    single = q.ndim == 1
    if single:
        q = q[None, :]

    q = q / np.linalg.norm(q, axis=-1, keepdims=True)

    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]

    N = q.shape[0]
    R = np.zeros((N, 3, 3), dtype=np.float64)

    R[:, 0, 0] = 1 - 2 * (y * y + z * z)
    R[:, 0, 1] = 2 * (x * y - z * w)
    R[:, 0, 2] = 2 * (x * z + y * w)
    R[:, 1, 0] = 2 * (x * y + z * w)
    R[:, 1, 1] = 1 - 2 * (x * x + z * z)
    R[:, 1, 2] = 2 * (y * z + x * w)
    R[:, 2, 0] = 2 * (x * z - y * w)
    R[:, 2, 1] = 2 * (y * z + x * w)
    R[:, 2, 2] = 1 - 2 * (x * x + y * y)

    if single:
        return R[0]
    return R


def matrix_to_quaternion(M):
    """Convert rotation matrix to unit quaternion (w, x, y, z).

    Uses Shepperd's method for numerical stability.
    Returns quaternion with w >= 0 (canonical form).

    Args:
        M: rotation matrix of shape (3, 3) or (N, 3, 3)

    Returns:
        Quaternion of shape (4,) or (N, 4) with w >= 0
    """
    M = np.asarray(M, dtype=np.float64)
    single = M.ndim == 2
    if single:
        M = M[None, :, :]

    N = M.shape[0]
    q = np.zeros((N, 4), dtype=np.float64)

    for i in range(N):
        m = M[i]
        trace = m[0, 0] + m[1, 1] + m[2, 2]

        if trace > 0:
            s = 0.5 / np.sqrt(trace + 1.0)
            q[i, 0] = 0.25 / s
            q[i, 1] = (m[2, 1] - m[1, 2]) * s
            q[i, 2] = (m[0, 2] - m[2, 0]) * s
            q[i, 3] = (m[1, 0] - m[0, 1]) * s
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
            q[i, 0] = (m[2, 1] - m[1, 2]) / s
            q[i, 1] = 0.25 * s
            q[i, 2] = (m[0, 1] + m[1, 0]) / s
            q[i, 3] = (m[0, 2] + m[2, 0]) / s
        elif m[1, 1] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
            q[i, 0] = (m[0, 2] - m[2, 0]) / s
            q[i, 1] = (m[0, 1] + m[1, 0]) / s
            q[i, 2] = 0.25 * s
            q[i, 3] = (m[1, 2] + m[2, 1]) / s
        else:
            s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
            q[i, 0] = (m[1, 0] - m[0, 1]) / s
            q[i, 1] = (m[0, 2] + m[2, 0]) / s
            q[i, 2] = (m[1, 2] + m[2, 1]) / s
            q[i, 3] = 0.25 * s

        # Standardize to w >= 0
        if q[i, 0] < 0:
            q[i] = -q[i]

    if single:
        return q[0]
    return q


def axis_angle_to_matrix(aa):
    """Convert axis-angle representation to rotation matrix.

    Uses the Rodrigues rotation formula.

    Args:
        aa: axis-angle vector of shape (3,) or (N, 3).
            Direction is the rotation axis, magnitude is the angle in radians.

    Returns:
        Rotation matrix of shape (3, 3) or (N, 3, 3)
    """
    aa = np.asarray(aa, dtype=np.float64)
    single = aa.ndim == 1
    if single:
        aa = aa[None, :]

    N = aa.shape[0]
    angles = np.linalg.norm(aa, axis=-1, keepdims=True)  # (N, 1)

    # Compute unit axes
    axes = aa / angles

    # Build skew-symmetric matrices for unit axes
    K = np.zeros((N, 3, 3), dtype=np.float64)
    K[:, 0, 1] = -axes[:, 2]
    K[:, 0, 2] = axes[:, 1]
    K[:, 1, 0] = axes[:, 2]
    K[:, 1, 2] = -axes[:, 0]
    K[:, 2, 0] = -axes[:, 1]
    K[:, 2, 1] = axes[:, 0]

    # Rodrigues formula: R = I + sin(theta)*K + (1-cos(theta))*K^2
    angles_3d = angles[:, :, None]  # (N, 1, 1)
    I = np.eye(3)[None, :, :]  # (1, 3, 3)

    R = I + np.sin(angles_3d) * K + (1 - np.cos(angles_3d)) * (K @ K)

    if single:
        return R[0]
    return R


def matrix_to_axis_angle(M):
    """Convert rotation matrix to axis-angle representation.

    Handles edge cases near identity and 180-degree rotations.

    Args:
        M: rotation matrix of shape (3, 3)

    Returns:
        Axis-angle vector of shape (3,). Direction is the rotation axis,
        magnitude is the angle in radians.
    """
    M = np.asarray(M, dtype=np.float64)

    trace = M[0, 0] + M[1, 1] + M[2, 2]
    cos_angle = np.clip((trace - 1) / 2, -1.0, 1.0)
    angle = np.arccos(cos_angle)

    if angle < 1e-10:
        return np.zeros(3, dtype=np.float64)

    if np.abs(angle - np.pi) < 1e-6:
        # Near 180 degrees: extract axis from R + I
        RpI = M + np.eye(3)
        col_norms = np.linalg.norm(RpI, axis=0)
        best_col = np.argmax(col_norms)
        axis = RpI[:, best_col]
        axis = axis / np.linalg.norm(axis)
        return angle * axis

    # General case: extract axis from skew-symmetric part
    axis = np.array([
        M[2, 1] - M[1, 2],
        M[0, 2] - M[2, 0],
        M[1, 0] - M[0, 1]
    ])
    axis = axis / (2 * np.sin(angle))
    return angle * axis


def geodesic_distance(R1, R2):
    """Compute the geodesic distance between two rotation matrices on SO(3).

    The geodesic distance equals the angle of the relative rotation.
    Formula: d(R1, R2) = arccos( (trace(R1^T R2) - 1) / 2 )

    Args:
        R1: rotation matrix of shape (3, 3)
        R2: rotation matrix of shape (3, 3)

    Returns:
        Geodesic distance in radians (scalar in [0, pi])
    """
    R1 = np.asarray(R1, dtype=np.float64)
    R2 = np.asarray(R2, dtype=np.float64)
    R_rel = R1 @ R2
    cos_angle = np.clip((np.trace(R_rel) - 1) / 2, -1.0, 1.0)
    return np.arccos(cos_angle)


def matrix_to_rotation_6d(M):
    """Convert rotation matrix to 6D rotation representation.

    Following Zhou et al. (2019) "On the Continuity of Rotation
    Representations in Neural Networks", takes the first two rows.

    Args:
        M: rotation matrix of shape (3, 3)

    Returns:
        6D representation of shape (6,)
    """
    M = np.asarray(M, dtype=np.float64)
    return M[:2, :].flatten()


def rotation_6d_to_matrix(d6):
    """Convert 6D rotation representation to rotation matrix.

    Uses Gram-Schmidt orthogonalization following Zhou et al. (2019).
    The 6D vector consists of two 3D vectors [a1 | a2] which are
    orthogonalized to form the first two rows of a rotation matrix.

    Args:
        d6: 6D representation of shape (6,)

    Returns:
        Rotation matrix of shape (3, 3)
    """
    raise NotImplementedError("rotation_6d_to_matrix is not yet implemented")


def slerp_rotations(R1, R2, t):
    """Spherical linear interpolation (SLERP) between two rotation matrices.

    Interpolates along the geodesic on SO(3) at constant angular velocity.
    At t=0 returns R1, at t=1 returns R2.

    Args:
        R1: start rotation matrix of shape (3, 3)
        R2: end rotation matrix of shape (3, 3)
        t: interpolation parameter in [0, 1]

    Returns:
        Interpolated rotation matrix of shape (3, 3)
    """
    raise NotImplementedError("slerp_rotations is not yet implemented")


def karcher_mean(rotations, weights=None, max_iter=100, tol=1e-10):
    """Compute the Karcher (Frechet/geodesic) mean of rotation matrices.

    The Karcher mean minimizes the sum of squared geodesic distances to the
    input rotations. Uses an iterative algorithm on the SO(3) manifold via
    the exponential and logarithmic maps.

    Args:
        rotations: array of shape (N, 3, 3)
        weights: optional array of shape (N,). Uniform weights if None.
        max_iter: maximum number of iterations
        tol: convergence tolerance on the tangent vector norm

    Returns:
        Mean rotation matrix of shape (3, 3)
    """
    raise NotImplementedError("karcher_mean is not yet implemented")


def project_to_so3(M):
    """Project a general 3x3 matrix to the nearest rotation matrix in SO(3).

    Uses SVD-based projection (Procrustes problem). Returns the rotation
    matrix R that minimizes the Frobenius norm ||R - M||_F subject to
    R^T R = I and det(R) = 1.

    Args:
        M: arbitrary 3x3 matrix

    Returns:
        Nearest rotation matrix of shape (3, 3) with det = +1
    """
    raise NotImplementedError("project_to_so3 is not yet implemented")
