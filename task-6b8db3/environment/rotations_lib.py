"""
Rotation Conversion Library
============================

Functions for converting between rotation representations:
quaternion (real-first), rotation matrix (3x3), axis-angle, Euler angles.
Also provides SO(3) geodesic distance.

Based on PyTorch3D rotation_conversions.

"""

import math
import torch
import torch.nn.functional as F


def _copysign(a, b):
    signs_differ = (a < 0) != (b < 0)
    return torch.where(signs_differ, -a, a)


def _sqrt_positive_part(x):
    positive_mask = x > 0
    safe_x = torch.where(positive_mask, x, 1.0)
    return torch.where(positive_mask, torch.sqrt(safe_x), 0.0)


def standardize_quaternion(quaternions):
    """Ensure quaternion real part is non-negative."""
    return torch.where(quaternions[..., 0:1] < 0, -quaternions, quaternions)


def _hat(v):
    """Skew-symmetric (hat) matrix of a batch of 3D vectors."""
    x, y, z = v.unbind(-1)
    zero = torch.zeros_like(x)
    rows = torch.stack([
        zero, -z, y,
        z, zero, -x,
        -y, x, zero
    ], dim=-1)
    return rows.reshape(v.shape[:-1] + (3, 3))


# ---- Quaternion <-> Matrix ----

def quaternion_to_matrix(quaternions):
    """Convert quaternions (w,x,y,z) of shape (...,4) to rotation matrices (...,3,3)."""
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
            two_s * (i * k - j * r),
            two_s * (j * k + i * r),
            1 - two_s * (i * i + j * j),
        ),
        -1,
    )
    return o.reshape(quaternions.shape[:-1] + (3, 3))


def matrix_to_quaternion(matrix):
    """Convert rotation matrices (...,3,3) to quaternions (w,x,y,z) (...,4)."""
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
            torch.stack([torch.square(q_abs[..., 0]), m21 - m12, m02 - m20, m10 - m01], dim=-1),
            torch.stack([m21 - m12, torch.square(q_abs[..., 1]), m10 + m01, m02 + m20], dim=-1),
            torch.stack([m02 - m20, m10 + m01, torch.square(q_abs[..., 2]), m12 + m21], dim=-1),
            torch.stack([m10 - m01, m20 + m02, m21 + m12, torch.square(q_abs[..., 3])], dim=-1),
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


# ---- Axis-Angle <-> Quaternion ----

def axis_angle_to_quaternion(axis_angle):
    """Convert axis-angle (...,3) to quaternion (...,4)."""
    angles = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)
    half_angles = angles * 0.5
    sin_half_angles_over_angles = 0.5 * torch.sinc(half_angles / math.pi)
    return torch.cat(
        [torch.cos(half_angles), axis_angle * sin_half_angles_over_angles], dim=-1
    )


def quaternion_to_axis_angle(quaternions):
    """Convert quaternion (...,4) to axis-angle (...,3)."""
    norms = torch.norm(quaternions[..., 1:], p=2, dim=-1, keepdim=True)
    half_angles = torch.atan2(norms, quaternions[..., :1])
    sin_half_angles_over_angles = 0.5 * torch.sinc(half_angles / math.pi)
    return quaternions[..., 1:] / sin_half_angles_over_angles


# ---- Axis-Angle <-> Matrix (Rodrigues) ----

def axis_angle_to_matrix(axis_angle):
    """Convert axis-angle (...,3) to rotation matrix (...,3,3) via Rodrigues' formula.
    Uses sinc for numerical stability at theta=0."""
    theta = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)
    K = _hat(axis_angle)
    K2 = K @ K
    theta_unsq = theta.unsqueeze(-1)
    sinc_theta = torch.sinc(theta_unsq / math.pi)
    half_theta = theta_unsq / 2
    sinc_half = torch.sinc(half_theta / math.pi)
    cos_factor = sinc_half * sinc_half / 2
    I = torch.eye(3, device=axis_angle.device, dtype=axis_angle.dtype)
    R = I + sinc_theta * K + cos_factor * K2
    return R


def matrix_to_axis_angle(matrix):
    """Convert rotation matrix (...,3,3) to axis-angle (...,3)."""
    return quaternion_to_axis_angle(matrix_to_quaternion(matrix))


# ---- Euler Angles <-> Matrix ----

def _axis_angle_rotation(axis, angle):
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
    """Convert Euler angles (...,3) to rotation matrix (...,3,3).
    For 'XYZ': R = Rx @ Ry @ Rz (first letter = outermost rotation)."""
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
    return torch.matmul(torch.matmul(matrices[0], matrices[1]), matrices[2])


def _index_from_letter(letter):
    if letter == "X":
        return 0
    if letter == "Y":
        return 1
    if letter == "Z":
        return 2
    raise ValueError("letter must be either X, Y or Z.")


def _angle_from_tan(axis, other_axis, data, horizontal, tait_bryan):
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
    """Convert rotation matrix (...,3,3) to Euler angles (...,3)."""
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
        _angle_from_tan(convention[0], convention[1], matrix[..., i2], False, tait_bryan),
        central_angle,
        _angle_from_tan(convention[2], convention[1], matrix[..., i0, :], True, tait_bryan),
    )
    return torch.stack(o, -1)


# ---- SO(3) Geodesic Distance ----

def so3_relative_angle(R1, R2):
    """Geodesic angle between rotation matrices (N,3,3) -> (N,)."""
    R12 = torch.bmm(R1, R2.permute(0, 2, 1))
    rot_trace = R12[:, 0, 0] + R12[:, 1, 1] + R12[:, 2, 2]
    phi_cos = (rot_trace - 1.0) * 0.5
    phi_cos = torch.clamp(phi_cos, -1.0, 1.0)
    return torch.acos(phi_cos)


# ---- SVD projection to SO(3) ----

def project_to_so3(M):
    """Project a batch of 3x3 matrices to SO(3) via SVD.
    Args: M of shape (..., 3, 3)
    Returns: closest rotation matrix in Frobenius norm."""
    U, S, Vh = torch.linalg.svd(M)
    det = torch.det(U @ Vh)
    # Correct for reflections
    diag = torch.ones_like(S)
    diag[..., -1] = torch.sign(det)
    return U @ torch.diag_embed(diag) @ Vh
