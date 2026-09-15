"""Rotation Conversion Library - Implementation Beta

Conversions between quaternion (w,x,y,z), rotation matrix (3x3),
axis-angle (3D vector), Euler angles, and 6D representations.
Includes geodesic distance and SLERP utilities.
"""

import numpy as np


def _index_from_letter(letter):
    if letter == "X": return 0
    if letter == "Y": return 1
    if letter == "Z": return 2
    raise ValueError(f"Invalid axis: {letter}")


def _single_axis_rotation(axis, angle):
    c, s = np.cos(angle), np.sin(angle)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)
    if axis == "Z":
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)
    raise ValueError(f"Invalid axis: {axis}")


def _angle_from_tan(axis, other_axis, data, horizontal, tait_bryan):
    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return np.arctan2(data[i1], data[i2])
    if tait_bryan:
        return np.arctan2(-data[i2], data[i1])
    return np.arctan2(data[i2], -data[i1])


def standardize_quaternion(q):
    q = np.asarray(q, dtype=float).copy()
    if q[0] < 0:
        q = -q
    return q


def quaternion_to_matrix(q):
    """Convert unit quaternion (w,x,y,z) to 3x3 rotation matrix."""
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w),     2*(x*z - y*w)],
        [2*(x*y + z*w),     1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w),     2*(y*z + x*w),      1 - 2*(x*x + y*y)]
    ])


def matrix_to_quaternion(R):
    """Convert 3x3 rotation matrix to unit quaternion (w,x,y,z).
    Uses the Shepperd method with full diagonal element selection."""
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
    elif m00 > m11 and m00 > m22:
        s = 2.0 * np.sqrt(1.0 + m00 - m11 - m22)
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * np.sqrt(1.0 + m11 - m00 - m22)
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = 2.0 * np.sqrt(1.0 + m22 - m00 - m11)
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    q = np.array([w, x, y, z])
    q = q / np.linalg.norm(q)
    return standardize_quaternion(q)


def axis_angle_to_quaternion(axis_angle):
    """Convert axis-angle (3D vector) to unit quaternion."""
    axis_angle = np.asarray(axis_angle, dtype=float)
    angle = np.linalg.norm(axis_angle)
    if angle < 1e-10:
        return np.array([1.0, 0.0, 0.0, 0.0])
    half = angle / 2.0
    axis = axis_angle / angle
    return np.array([np.cos(half), *(np.sin(half) * axis)])


def quaternion_to_axis_angle(q):
    """Convert unit quaternion to axis-angle representation."""
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    q = standardize_quaternion(q)
    w, xyz = q[0], q[1:]
    sin_half = np.linalg.norm(xyz)
    if sin_half < 1e-10:
        return np.zeros(3)
    angle = 2.0 * np.arctan2(sin_half, w)
    return angle * (xyz / sin_half)


def axis_angle_to_matrix(axis_angle):
    """Convert axis-angle to rotation matrix via Rodrigues formula."""
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
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def matrix_to_axis_angle(R):
    """Convert rotation matrix to axis-angle via quaternion intermediate."""
    return quaternion_to_axis_angle(matrix_to_quaternion(R))


def euler_angles_to_matrix(angles, convention):
    """Convert Euler angles to rotation matrix."""
    angles = np.asarray(angles, dtype=float)
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    matrices = [_single_axis_rotation(c, a) for c, a in zip(convention, angles)]
    return matrices[0] @ matrices[1] @ matrices[2]


def matrix_to_euler_angles(R, convention):
    """Convert rotation matrix to Euler angles."""
    R = np.asarray(R, dtype=float)
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
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
        _angle_from_tan(convention[0], convention[1], R[:, i2], False, tait_bryan),
        central_angle,
        _angle_from_tan(convention[2], convention[1], R[i0, :], True, tait_bryan),
    )
    return np.array(o)


def rotation_6d_to_matrix(d6):
    """Convert 6D rotation representation to matrix (Gram-Schmidt)."""
    d6 = np.asarray(d6, dtype=float)
    a1, a2 = d6[:3], d6[3:]
    b1 = a1 / np.linalg.norm(a1)
    b2 = a2 - np.dot(b1, a2) * b1
    b2 = b2 / np.linalg.norm(b2)
    return np.stack([b1, b2, np.cross(b1, b2)], axis=0)


def matrix_to_rotation_6d(R):
    """Convert rotation matrix to 6D representation."""
    return np.asarray(R, dtype=float)[:2, :].flatten().copy()


def geodesic_distance(R1, R2):
    """Compute geodesic (angular) distance between two rotation matrices."""
    R1 = np.asarray(R1, dtype=float)
    R2 = np.asarray(R2, dtype=float)
    R_rel = R1 @ R2.T
    cos_angle = np.clip((np.trace(R_rel) - 1) / 2.0, -1.0, 1.0)
    return float(np.arccos(cos_angle))


def slerp(q0, q1, t):
    """Spherical linear interpolation between quaternions."""
    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)
    dot = np.dot(q0, q1)
    if dot < 0:
        q1 = -q1
        dot = -dot
    dot = np.clip(dot, -1.0, 1.0)
    theta = np.arccos(dot)
    if abs(theta) < 1e-10:
        return q0.copy()
    sin_theta = np.sin(theta)
    w0 = np.sin((1.0 - t) * theta) / sin_theta
    w1 = np.sin(t * theta) / sin_theta
    result = w0 * q0 + w1 * q1
    return result / np.linalg.norm(result)


def random_rotation_matrix():
    """Generate a uniformly random rotation matrix."""
    H = np.random.randn(3, 3)
    Q, R = np.linalg.qr(H)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    if np.linalg.det(Q) < 0:
        Q[:, 0] *= -1
    return Q
