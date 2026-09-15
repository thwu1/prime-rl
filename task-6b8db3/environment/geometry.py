"""
3D Rotation Representation Conversion Library
==============================================

This library provides functions for converting between different rotation
representations (quaternion, rotation matrix, axis-angle, Euler angles, 6D),
computing SO(3) geodesic distances, and batched Chamfer distance for point clouds.

Conventions:
- Quaternions use real-first (w, x, y, z) format, standardized to w >= 0.
- Rotation matrices R are 3x3 orthogonal with det(R) = +1.
- Axis-angle vectors encode both the rotation axis (direction) and angle (magnitude).
- Euler angles use intrinsic rotation convention.
- 6D representation follows Zhou et al. (CVPR 2019) using Gram-Schmidt orthogonalization.

"""

import math
import torch
import torch.nn.functional as F


# ============================================================
# Helper utilities
# ============================================================

def _copysign(a, b):
    """Return a with the sign of b."""
    signs_differ = (a < 0) != (b < 0)
    return torch.where(signs_differ, -a, a)


def _sqrt_positive_part(x):
    """Return sqrt(max(0, x)) with zero subgradient where x is 0."""
    positive_mask = x > 0
    safe_x = torch.where(positive_mask, x, 1.0)
    return torch.where(positive_mask, torch.sqrt(safe_x), 0.0)


def standardize_quaternion(quaternions):
    """Ensure quaternion real part is non-negative (canonical form)."""
    return torch.where(quaternions[..., 0:1] < 0, -quaternions, quaternions)


def _hat(v):
    """Compute the skew-symmetric (hat) matrix of a batch of 3D vectors.

    Args:
        v: tensor of shape (..., 3)

    Returns:
        Skew-symmetric matrices of shape (..., 3, 3) where
        [v]_x = [[0, -vz, vy], [vz, 0, -vx], [-vy, vx, 0]]
    """
    x, y, z = v.unbind(-1)
    zero = torch.zeros_like(x)
    rows = torch.stack([
        zero, -z, y,
        z, zero, -x,
        -y, x, zero
    ], dim=-1)
    return rows.reshape(v.shape[:-1] + (3, 3))


# ============================================================
# Quaternion <-> Rotation Matrix
# ============================================================

def quaternion_to_matrix(quaternions):
    """Convert quaternions to rotation matrices.

    Args:
        quaternions: tensor of shape (..., 4), real part first (w, x, y, z).

    Returns:
        Rotation matrices of shape (..., 3, 3).

    For unit quaternion q = (w, x, y, z), the rotation matrix is constructed
    using the standard formula involving cross-product and diagonal terms
    derived from the quaternion components.
    """
    r, i, j, k = torch.unbind(quaternions, -1)
    two_s = 2.0 / (quaternions * quaternions).sum(-1)

    o = torch.stack(
        (
            1 - two_s * (j * j + k * k),
            two_s * (i * j - k * r),
            two_s * (i * k + j * r),
            two_s * (i * j + k * r),
            1 - two_s * (i * i + k * k),
            two_s * (j * k - i * r),
            two_s * (i * k + j * r),
            two_s * (j * k + i * r),
            1 - two_s * (i * i + j * j),
        ),
        -1,
    )
    return o.reshape(quaternions.shape[:-1] + (3, 3))


def matrix_to_quaternion(matrix):
    """Convert rotation matrices to quaternions (real-first, standardized).

    Args:
        matrix: Rotation matrices of shape (..., 3, 3).

    Returns:
        Quaternions (w, x, y, z) of shape (..., 4) with w >= 0.

    Uses the Shepperd method for numerical stability, selecting the
    best-conditioned quaternion component as the pivot.
    """
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")

    batch_dim = matrix.shape[:-2]
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = torch.unbind(
        matrix.reshape(batch_dim + (9,)), dim=-1
    )

    q_abs = _sqrt_positive_part(
        torch.stack(
            [
                1.0 + m00 + m11 + m22,
                1.0 + m00 - m11 - m22,
                1.0 - m00 + m11 - m22,
                1.0 - m00 - m11 + m22,
            ],
            dim=-1,
        )
    )

    quat_by_rijk = torch.stack(
        [
            torch.stack(
                [torch.square(q_abs[..., 0]), m21 - m12, m02 - m20, m10 - m01],
                dim=-1,
            ),
            torch.stack(
                [m21 - m12, torch.square(q_abs[..., 1]), m10 + m01, m02 + m20],
                dim=-1,
            ),
            torch.stack(
                [m02 - m20, m10 + m01, torch.square(q_abs[..., 2]), m12 + m21],
                dim=-1,
            ),
            torch.stack(
                [m10 - m01, m20 + m02, m21 + m12, torch.square(q_abs[..., 3])],
                dim=-1,
            ),
        ],
        dim=-2,
    )

    flr = torch.tensor(0.1).to(dtype=q_abs.dtype, device=q_abs.device)
    quat_candidates = quat_by_rijk / (2.0 * q_abs[..., None].max(flr))

    indices = q_abs.argmax(dim=-1, keepdim=True)
    expand_dims = list(batch_dim) + [1, 4]
    gather_indices = indices.unsqueeze(-1).expand(expand_dims)
    out = torch.gather(quat_candidates, -2, gather_indices).squeeze(-2)
    return standardize_quaternion(out)


# ============================================================
# Axis-Angle <-> Quaternion
# ============================================================

def axis_angle_to_quaternion(axis_angle):
    """Convert axis-angle representation to quaternion.

    Args:
        axis_angle: tensor of shape (..., 3), rotation axis * angle.

    Returns:
        Quaternions (w, x, y, z) of shape (..., 4).
    """
    angles = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)
    half_angles = angles * 0.5
    sin_half_angles_over_angles = 0.5 * torch.sinc(half_angles / math.pi)
    return torch.cat(
        [torch.cos(half_angles), axis_angle * sin_half_angles_over_angles], dim=-1
    )


def quaternion_to_axis_angle(quaternions):
    """Convert quaternion to axis-angle representation.

    Args:
        quaternions: tensor of shape (..., 4), real part first.

    Returns:
        Axis-angle vectors of shape (..., 3).
    """
    norms = torch.norm(quaternions[..., 1:], p=2, dim=-1, keepdim=True)
    half_angles = torch.atan2(norms, quaternions[..., :1])
    sin_half_angles_over_angles = 0.5 * torch.sinc(half_angles / math.pi)
    return quaternions[..., 1:] / sin_half_angles_over_angles


# ============================================================
# Axis-Angle <-> Rotation Matrix (Rodrigues' formula)
# ============================================================

def axis_angle_to_matrix(axis_angle):
    """Convert axis-angle vectors to rotation matrices via Rodrigues' formula.

    R = I + sin(theta)/theta * K + (1 - cos(theta))/theta^2 * K^2

    where theta = ||axis_angle||, K = [axis_angle]_x (skew-symmetric matrix).
    The formula must handle theta = 0 (identity rotation) without producing NaN.

    Args:
        axis_angle: tensor of shape (..., 3).

    Returns:
        Rotation matrices of shape (..., 3, 3).
    """
    theta = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)  # (..., 1)
    K = _hat(axis_angle)  # (..., 3, 3)
    K2 = K @ K  # (..., 3, 3)
    theta_unsq = theta.unsqueeze(-1)  # (..., 1, 1) for broadcasting with 3x3
    theta_sq = theta_unsq * theta_unsq  # (..., 1, 1)
    I = torch.eye(3, device=axis_angle.device, dtype=axis_angle.dtype)
    R = I + (torch.sin(theta_unsq) / theta_unsq) * K + ((1 - torch.cos(theta_unsq)) / theta_sq) * K2
    return R


def matrix_to_axis_angle(matrix):
    """Convert rotation matrices to axis-angle vectors.

    Args:
        matrix: Rotation matrices of shape (..., 3, 3).

    Returns:
        Axis-angle vectors of shape (..., 3).
    """
    return quaternion_to_axis_angle(matrix_to_quaternion(matrix))


# ============================================================
# Euler Angles <-> Rotation Matrix
# ============================================================

def _axis_angle_rotation(axis, angle):
    """Return rotation matrices for rotations about a single axis.

    Args:
        axis: "X", "Y", or "Z".
        angle: tensor of Euler angles in radians.

    Returns:
        Rotation matrices of shape (..., 3, 3).
    """
    cos = torch.cos(angle)
    sin = torch.sin(angle)
    one = torch.ones_like(angle)
    zero = torch.zeros_like(angle)

    if axis == "X":
        R_flat = (one, zero, zero, zero, cos, -sin, zero, sin, cos)
    elif axis == "Y":
        R_flat = (cos, zero, sin, zero, one, zero, -sin, zero, cos)
    elif axis == "Z":
        R_flat = (cos, -sin, zero, sin, cos, zero, zero, zero, one)
    else:
        raise ValueError("letter must be either X, Y or Z.")

    return torch.stack(R_flat, -1).reshape(angle.shape + (3, 3))


def euler_angles_to_matrix(euler_angles, convention):
    """Convert Euler angles to rotation matrices using intrinsic rotation convention.

    For convention "XYZ", the rotation is applied as R = R_X @ R_Y @ R_Z,
    meaning the first letter corresponds to the outermost (first applied) rotation.

    Args:
        euler_angles: tensor of shape (..., 3) in radians.
        convention: 3-letter string from {X, Y, Z}, e.g. "XYZ", "ZYX".

    Returns:
        Rotation matrices of shape (..., 3, 3).
    """
    if euler_angles.dim() == 0 or euler_angles.shape[-1] != 3:
        raise ValueError("Invalid input euler angles.")
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    for letter in convention:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")
    matrices = [
        _axis_angle_rotation(c, e)
        for c, e in zip(convention, torch.unbind(euler_angles, -1))
    ]
    return torch.matmul(torch.matmul(matrices[2], matrices[1]), matrices[0])


def _index_from_letter(letter):
    if letter == "X":
        return 0
    if letter == "Y":
        return 1
    if letter == "Z":
        return 2
    raise ValueError("letter must be either X, Y or Z.")


def _angle_from_tan(axis, other_axis, data, horizontal, tait_bryan):
    """Extract Euler angle from matrix elements using atan2."""
    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return torch.atan2(data[..., i1], data[..., i2])
    if tait_bryan:
        return torch.atan2(-data[..., i2], data[..., i1])
    return torch.atan2(data[..., i2], -data[..., i1])


def matrix_to_euler_angles(matrix, convention):
    """Convert rotation matrices to Euler angles.

    Args:
        matrix: Rotation matrices of shape (..., 3, 3).
        convention: 3-letter string, e.g. "XYZ".

    Returns:
        Euler angles in radians of shape (..., 3).
    """
    if len(convention) != 3:
        raise ValueError("Convention must have 3 letters.")
    if convention[1] in (convention[0], convention[2]):
        raise ValueError(f"Invalid convention {convention}.")
    for letter in convention:
        if letter not in ("X", "Y", "Z"):
            raise ValueError(f"Invalid letter {letter} in convention string.")
    if matrix.size(-1) != 3 or matrix.size(-2) != 3:
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")
    i0 = _index_from_letter(convention[0])
    i2 = _index_from_letter(convention[2])
    tait_bryan = i0 != i2
    if tait_bryan:
        central_angle = torch.asin(
            torch.clamp(matrix[..., i0, i2], -1.0, 1.0)
            * (-1.0 if i0 - i2 in [-1, 2] else 1.0)
        )
    else:
        central_angle = torch.acos(
            torch.clamp(matrix[..., i0, i0], -1.0, 1.0)
        )

    o = (
        _angle_from_tan(
            convention[0], convention[1], matrix[..., i2], False, tait_bryan
        ),
        central_angle,
        _angle_from_tan(
            convention[2], convention[1], matrix[..., i0, :], True, tait_bryan
        ),
    )
    return torch.stack(o, -1)


# ============================================================
# 6D Rotation Representation (Zhou et al., CVPR 2019)
# ============================================================

def rotation_6d_to_matrix(d6):
    """Convert 6D rotation representation to rotation matrix.

    Uses Gram-Schmidt orthogonalization on the two input 3D vectors
    to produce three orthonormal basis vectors forming a rotation matrix.

    Args:
        d6: tensor of shape (..., 6).

    Returns:
        Rotation matrices of shape (..., 3, 3) with det = +1.
    """
    a1, a2 = d6[..., :3], d6[..., 3:]
    b1 = F.normalize(a1, dim=-1)
    b2 = a2 - (b1 * a2).sum(-1, keepdim=True) * b1
    b2 = F.normalize(b2, dim=-1)
    b3 = torch.cross(b2, b1, dim=-1)
    return torch.stack((b1, b2, b3), dim=-2)


def matrix_to_rotation_6d(matrix):
    """Convert rotation matrices to 6D representation.

    Extracts the first two rows and flattens.

    Args:
        matrix: Rotation matrices of shape (..., 3, 3).

    Returns:
        6D vectors of shape (..., 6).
    """
    batch_dim = matrix.size()[:-2]
    return matrix[..., :2, :].clone().reshape(batch_dim + (6,))


# ============================================================
# SO(3) Geodesic Distance
# ============================================================

def so3_relative_angle(R1, R2):
    """Compute geodesic angle between pairs of rotation matrices.

    angle = acos(0.5 * (trace(R1 @ R2^T) - 1))

    Args:
        R1: Rotation matrices of shape (N, 3, 3).
        R2: Rotation matrices of shape (N, 3, 3).

    Returns:
        Angles in radians of shape (N,).
    """
    R12 = torch.bmm(R1, R2.permute(0, 2, 1))
    rot_trace = R12[:, 0, 0] + R12[:, 1, 1] + R12[:, 2, 2]
    phi_cos = (rot_trace - 1.0) * 0.5
    phi_cos = torch.clamp(phi_cos, -1.0, 1.0)
    return torch.acos(phi_cos)


# ============================================================
# Chamfer Distance (batched, heterogeneous lengths)
# ============================================================

def chamfer_distance(x, y, x_lengths=None, y_lengths=None):
    """Compute mean bidirectional Chamfer distance between batched point clouds.

    For heterogeneous batches where each cloud has a different number of valid
    points, x_lengths and y_lengths specify how many points in each batch element
    are valid. Points beyond the valid length are padding and must be excluded
    from the distance computation.

    Args:
        x: tensor of shape (N, P1, D) - batch of source point clouds.
        y: tensor of shape (N, P2, D) - batch of target point clouds.
        x_lengths: optional LongTensor of shape (N,), valid points per cloud in x.
        y_lengths: optional LongTensor of shape (N,), valid points per cloud in y.

    Returns:
        Scalar mean Chamfer distance (sum of forward and backward).
    """
    N, P1, D = x.shape
    _, P2, _ = y.shape

    if x_lengths is None:
        x_lengths = torch.full((N,), P1, dtype=torch.long, device=x.device)
    if y_lengths is None:
        y_lengths = torch.full((N,), P2, dtype=torch.long, device=y.device)

    # Pairwise squared distances: (N, P1, P2)
    dists = torch.cdist(x, y, p=2).pow(2)

    # Forward: for each x point, find nearest y point
    min_x_to_y = dists.min(dim=2).values  # (N, P1)

    # Backward: for each y point, find nearest x point
    min_y_to_x = dists.min(dim=1).values  # (N, P2)

    # Average per cloud, then batch mean
    loss_x = (min_x_to_y.sum(1) / x_lengths.float().clamp(min=1)).mean()
    loss_y = (min_y_to_x.sum(1) / y_lengths.float().clamp(min=1)).mean()

    return loss_x + loss_y
