"""
Rotation Conversion Library

Provides conversions between rotation representations:
- Quaternion (w, x, y, z) with real part first
- Rotation matrix (3x3 orthogonal, det=1)
- Axis-angle (3D vector, magnitude = rotation angle in radians)
- Euler angles (3 angles with convention string, e.g., "XYZ")
- 6D rotation (first two rows of rotation matrix, following Zhou et al.)

Also includes:
- Geodesic (angular) distance between rotations
- Spherical linear interpolation (SLERP)
- Random rotation generation
"""

import numpy as np


# ============================================================
# Helper functions
# ============================================================

def _index_from_letter(letter):
    """Convert axis letter to index: X->0, Y->1, Z->2."""
    if letter == "X":
        return 0
    elif letter == "Y":
        return 1
    elif letter == "Z":
        return 2
    raise ValueError(f"Invalid axis letter: {letter}")


def _single_axis_rotation(axis, angle):
    """Return 3x3 rotation matrix for rotation about a single coordinate axis."""
    c = np.cos(angle)
    s = np.sin(angle)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    elif axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)
    elif axis == "Z":
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    raise ValueError(f"Invalid axis: {axis}")


def _angle_from_tan(axis, other_axis, data, horizontal, tait_bryan):
    """
    Extract the first or third Euler angle from the two members of
    the matrix which are positive constant times its sine and cosine.
    """
    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return np.arctan2(data[i1], data[i2])
    if tait_bryan:
        return np.arctan2(-data[i2], data[i1])
    return np.arctan2(data[i2], -data[i1])


# ============================================================
# Core conversion functions
# ============================================================

def standardize_quaternion(q):
    """
    Ensure quaternion has non-negative real (w) component.
    Since q and -q represent the same rotation, we standardize
    to the hemisphere where w >= 0.
    """
    q = np.asarray(q, dtype=float).copy()
    if q[0] < 0:
        q = -q
    return q


def quaternion_to_matrix(q):
    """
    Convert unit quaternion to 3x3 rotation matrix.

    Parameters
    ----------
    q : array_like, shape (4,)
        Quaternion (w, x, y, z) with real part first.
        Will be normalized to unit length.

    Returns
    -------
    R : ndarray, shape (3, 3)
        Rotation matrix.
    """
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    w, x, y, z = q

    R = np.array([
        [1 - 2*(y*y + z*z),  2*(x*y - z*w),      2*(x*z - y*w)],
        [2*(x*y + z*w),      1 - 2*(x*x + z*z),   2*(y*z - x*w)],
        [2*(x*z - y*w),      2*(y*z + x*w),        1 - 2*(x*x + y*y)]
    ])
    return R


def matrix_to_quaternion(R):
    """
    Convert 3x3 rotation matrix to unit quaternion.

    Uses a numerically stable extraction method based on the matrix trace
    and diagonal elements.

    Parameters
    ----------
    R : array_like, shape (3, 3)
        Rotation matrix.

    Returns
    -------
    q : ndarray, shape (4,)
        Unit quaternion (w, x, y, z) with w >= 0.
    """
    R = np.asarray(R, dtype=float)
    m00, m01, m02 = R[0, 0], R[0, 1], R[0, 2]
    m10, m11, m12 = R[1, 0], R[1, 1], R[1, 2]
    m20, m21, m22 = R[2, 0], R[2, 1], R[2, 2]

    trace = m00 + m11 + m22

    if trace > 0:
        s = 2.0 * np.sqrt(1.0 + trace)
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    else:
        # For negative trace, use the largest diagonal element
        # to avoid numerical instability
        val = max(0.0, 1.0 + m00 - m11 - m22)
        s = 2.0 * np.sqrt(val)
        if s > 1e-8:
            w = (m21 - m12) / s
            x = 0.25 * s
            y = (m01 + m10) / s
            z = (m02 + m20) / s
        else:
            w, x, y, z = 1.0, 0.0, 0.0, 0.0

    q = np.array([w, x, y, z])
    q = q / np.linalg.norm(q)
    return standardize_quaternion(q)


def axis_angle_to_quaternion(axis_angle):
    """
    Convert axis-angle representation to unit quaternion.

    Parameters
    ----------
    axis_angle : array_like, shape (3,)
        Rotation vector where direction is the axis and magnitude
        is the angle in radians.

    Returns
    -------
    q : ndarray, shape (4,)
        Unit quaternion (w, x, y, z).
    """
    axis_angle = np.asarray(axis_angle, dtype=float)
    angle = np.linalg.norm(axis_angle)
    if angle < 1e-10:
        return np.array([1.0, 0.0, 0.0, 0.0])
    half_angle = angle / 2.0
    axis = axis_angle / angle
    w = np.cos(half_angle)
    xyz = np.sin(half_angle) * axis
    return np.array([w, xyz[0], xyz[1], xyz[2]])


def quaternion_to_axis_angle(q):
    """
    Convert unit quaternion to axis-angle representation.

    Parameters
    ----------
    q : array_like, shape (4,)
        Quaternion (w, x, y, z) with real part first.

    Returns
    -------
    axis_angle : ndarray, shape (3,)
        Rotation vector.
    """
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    q = standardize_quaternion(q)
    w = q[0]
    xyz = q[1:]
    sin_half = np.linalg.norm(xyz)
    if sin_half < 1e-10:
        return np.zeros(3)
    half_angle = np.arctan2(sin_half, w)
    angle = 2.0 * half_angle
    axis = xyz / sin_half
    return angle * axis


def axis_angle_to_matrix(axis_angle):
    """
    Convert axis-angle representation to rotation matrix using
    the Rodrigues rotation formula.

    Parameters
    ----------
    axis_angle : array_like, shape (3,)
        Rotation vector where direction is the axis and magnitude
        is the angle in radians.

    Returns
    -------
    R : ndarray, shape (3, 3)
        Rotation matrix.
    """
    axis_angle = np.asarray(axis_angle, dtype=float)
    angle = np.linalg.norm(axis_angle)
    if angle < 1e-10:
        return np.eye(3)

    axis = axis_angle / angle
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])

    # Rodrigues formula: R = I + sin(theta)*K + (1 - cos(theta))*K^2
    R = np.eye(3) + np.sin(angle) * K + (1 + np.cos(angle)) * (K @ K)
    return R


def matrix_to_axis_angle(R):
    """
    Convert rotation matrix to axis-angle representation.

    Goes through quaternion as intermediate representation.

    Parameters
    ----------
    R : array_like, shape (3, 3)
        Rotation matrix.

    Returns
    -------
    axis_angle : ndarray, shape (3,)
        Rotation vector.
    """
    q = matrix_to_quaternion(R)
    return quaternion_to_axis_angle(q)


def euler_angles_to_matrix(angles, convention):
    """
    Convert Euler angles to rotation matrix.

    Parameters
    ----------
    angles : array_like, shape (3,)
        Three rotation angles in radians.
    convention : str
        Three-letter string specifying the axis order (e.g., "XYZ", "ZYX").

    Returns
    -------
    R : ndarray, shape (3, 3)
        Rotation matrix.
    """
    angles = np.asarray(angles, dtype=float)
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    for letter in convention:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")

    matrices = [_single_axis_rotation(c, a)
                for c, a in zip(convention, angles)]
    return matrices[0] @ matrices[1] @ matrices[2]


def matrix_to_euler_angles(R, convention):
    """
    Convert rotation matrix to Euler angles.

    Parameters
    ----------
    R : array_like, shape (3, 3)
        Rotation matrix.
    convention : str
        Three-letter string specifying the axis order (e.g., "XYZ", "ZYX").

    Returns
    -------
    angles : ndarray, shape (3,)
        Euler angles in radians.
    """
    R = np.asarray(R, dtype=float)
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    for letter in convention:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")

    i0 = _index_from_letter(convention[0])
    i2 = _index_from_letter(convention[2])
    tait_bryan = i0 != i2

    if tait_bryan:
        central_angle = np.arcsin(
            np.clip(R[i0, i2], -1.0, 1.0)
            * (1.0 if i0 - i2 in [-1, 2] else -1.0)
        )
    else:
        central_angle = np.arccos(np.clip(R[i0, i0], -1.0, 1.0))

    o = (
        _angle_from_tan(
            convention[0], convention[1], R[:, i2], False, tait_bryan
        ),
        central_angle,
        _angle_from_tan(
            convention[2], convention[1], R[i0, :], True, tait_bryan
        ),
    )
    return np.array(o)


def rotation_6d_to_matrix(d6):
    """
    Convert 6D rotation representation to rotation matrix using
    Gram-Schmidt orthogonalization (Zhou et al., CVPR 2019).

    Parameters
    ----------
    d6 : array_like, shape (6,)
        6D rotation representation.

    Returns
    -------
    R : ndarray, shape (3, 3)
        Rotation matrix.
    """
    d6 = np.asarray(d6, dtype=float)
    a1, a2 = d6[:3], d6[3:]

    b1 = a1 / np.linalg.norm(a1)
    b2 = a2 - np.dot(b1, a2) * b1
    b2 = b2 / np.linalg.norm(b2)
    b3 = np.cross(b1, b2)

    return np.stack([b1, b2, b3], axis=0)


def matrix_to_rotation_6d(R):
    """
    Convert rotation matrix to 6D representation (first two rows flattened).

    Parameters
    ----------
    R : array_like, shape (3, 3)
        Rotation matrix.

    Returns
    -------
    d6 : ndarray, shape (6,)
        6D rotation representation.
    """
    R = np.asarray(R, dtype=float)
    return R[:2, :].flatten().copy()


# ============================================================
# Utilities
# ============================================================

def geodesic_distance(R1, R2):
    """
    Compute the geodesic (angular) distance between two rotation matrices.

    The distance equals the angle of the relative rotation R1 @ R2^T.

    Parameters
    ----------
    R1, R2 : array_like, shape (3, 3)
        Rotation matrices.

    Returns
    -------
    distance : float
        Angular distance in radians, in [0, pi].
    """
    R1 = np.asarray(R1, dtype=float)
    R2 = np.asarray(R2, dtype=float)
    R_rel = R1 @ R2.T
    cos_angle = np.clip((np.trace(R_rel) + 1) / 2.0, -1.0, 1.0)
    return float(np.arccos(cos_angle))


def slerp(q0, q1, t):
    """
    Spherical linear interpolation between two quaternions.

    Parameters
    ----------
    q0, q1 : array_like, shape (4,)
        Unit quaternions (w, x, y, z).
    t : float
        Interpolation parameter in [0, 1].

    Returns
    -------
    q : ndarray, shape (4,)
        Interpolated unit quaternion.
    """
    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)

    dot = np.clip(np.dot(q0, q1), -1.0, 1.0)

    theta = np.arccos(dot)

    if abs(theta) < 1e-10:
        return q0.copy()

    sin_theta = np.sin(theta)
    w0 = np.sin((1.0 - t) * theta) / sin_theta
    w1 = np.sin(t * theta) / sin_theta

    result = w0 * q0 + w1 * q1
    return result / np.linalg.norm(result)


def random_rotation_matrix():
    """
    Generate a uniformly random rotation matrix using QR decomposition.

    Returns
    -------
    R : ndarray, shape (3, 3)
        Random rotation matrix.
    """
    H = np.random.randn(3, 3)
    Q, R = np.linalg.qr(H)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q
