"""
rotation_lib.py - Self-contained 3D rotation conversion library.

Supports conversions between:
- Rotation matrices (3x3 orthogonal, det=+1)
- Unit quaternions (w, x, y, z) with real part first
- Euler angles (intrinsic, any 3-letter convention from {X,Y,Z})
- Axis-angle vectors (direction = axis, magnitude = angle in radians)
- 6D rotation representation (Zhou et al., CVPR 2019)

All functions support batched inputs with arbitrary leading dimensions.
Uses PyTorch for tensor operations (CPU only).
"""


import torch
import torch.nn.functional as F
from typing import Optional


def _copysign(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    """Return a tensor where each element has abs value from a, sign from b."""
    signs_differ = (a < 0) != (b < 0)
    return torch.where(signs_differ, -a, a)


def _sqrt_positive_part(x: torch.Tensor) -> torch.Tensor:
    """Returns sqrt(max(0, x)) with zero subgradient where x is 0."""
    positive_mask = x > 0
    safe_x = torch.where(positive_mask, x, 1.0)
    return torch.where(positive_mask, torch.sqrt(safe_x), 0.0)


def standardize_quaternion(quaternions: torch.Tensor) -> torch.Tensor:
    """
    Convert a unit quaternion to standard form: non-negative real part.

    Args:
        quaternions: shape (..., 4), real part first.
    Returns:
        Standardized quaternions, shape (..., 4).
    """
    return torch.where(quaternions[..., 0:1] < 0, -quaternions, quaternions)


def quaternion_to_matrix(quaternions: torch.Tensor) -> torch.Tensor:
    """
    Convert quaternions to rotation matrices.

    Args:
        quaternions: shape (..., 4), real part first (w, x, y, z).
    Returns:
        Rotation matrices, shape (..., 3, 3).
    """
    r, i, j, k = torch.unbind(quaternions, -1)
    two_s = torch.div(2.0, (quaternions * quaternions).sum(-1))

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


def matrix_to_quaternion(matrix: torch.Tensor) -> torch.Tensor:
    """
    Convert rotation matrices to quaternions using the Shepperd method.

    Selects the numerically best-conditioned quaternion component to avoid
    division by near-zero values.

    Args:
        matrix: shape (..., 3, 3).
    Returns:
        Quaternions, shape (..., 4), real part first.
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

    # Select the best-conditioned quaternion branch
    indices = q_abs.argmin(dim=-1, keepdim=True)
    expand_dims = list(batch_dim) + [1, 4]
    gather_indices = indices.unsqueeze(-1).expand(expand_dims)
    out = torch.gather(quat_candidates, -2, gather_indices).squeeze(-2)
    return standardize_quaternion(out)


def _axis_angle_rotation(axis: str, angle: torch.Tensor) -> torch.Tensor:
    """Return rotation matrices for rotation about a single axis."""
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


def euler_angles_to_matrix(
    euler_angles: torch.Tensor, convention: str
) -> torch.Tensor:
    """
    Convert Euler angles to rotation matrices (intrinsic rotations).

    The convention string specifies the axes of rotation. For "XYZ":
    the resulting rotation applies X first, then Y, then Z.

    Args:
        euler_angles: shape (..., 3), angles in radians.
        convention: 3-letter string from {X, Y, Z}, e.g. "XYZ", "ZYX".
    Returns:
        Rotation matrices, shape (..., 3, 3).
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


def _index_from_letter(letter: str) -> int:
    if letter == "X":
        return 0
    if letter == "Y":
        return 1
    if letter == "Z":
        return 2
    raise ValueError("letter must be either X, Y or Z.")


def _angle_from_tan(
    axis: str,
    other_axis: str,
    data,
    horizontal: bool,
    tait_bryan: bool,
) -> torch.Tensor:
    """
    Extract the first or third Euler angle from rotation matrix elements
    that are proportional to its sine and cosine.
    """
    i1, i2 = {"X": (2, 1), "Y": (0, 2), "Z": (1, 0)}[axis]
    if horizontal:
        i2, i1 = i1, i2
    even = (axis + other_axis) in ["XY", "YZ", "ZX"]
    if horizontal == even:
        return torch.atan2(data[..., i1], data[..., i2])
    if tait_bryan:
        return torch.atan2(-data[..., i2], data[..., i1])
    return torch.atan2(data[..., i2], -data[..., i1])


def matrix_to_euler_angles(
    matrix: torch.Tensor, convention: str
) -> torch.Tensor:
    """
    Convert rotation matrices to Euler angles in radians.

    Args:
        matrix: shape (..., 3, 3).
        convention: 3-letter convention string.
    Returns:
        Euler angles in radians, shape (..., 3).
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
        central_angle = torch.acos(torch.clamp(matrix[..., i0, i0], -1.0, 1.0))

    o = (
        _angle_from_tan(
            convention[0],
            convention[1],
            matrix[..., i2],
            False,
            tait_bryan,
        ),
        central_angle,
        _angle_from_tan(
            convention[2],
            convention[1],
            matrix[..., i0, :],
            True,
            tait_bryan,
        ),
    )
    return torch.stack(o, -1)


def axis_angle_to_quaternion(axis_angle: torch.Tensor) -> torch.Tensor:
    """
    Convert axis-angle to quaternions.

    Args:
        axis_angle: shape (..., 3), magnitude is the rotation angle.
    Returns:
        Quaternions, shape (..., 4), real part first.
    """
    angles = torch.norm(axis_angle, p=2, dim=-1, keepdim=True)
    sin_half_angles_over_angles = 0.5 * torch.sinc(angles * 0.5 / torch.pi)
    return torch.cat(
        [torch.cos(angles * 0.5), axis_angle * sin_half_angles_over_angles],
        dim=-1,
    )


def quaternion_to_axis_angle(quaternions: torch.Tensor) -> torch.Tensor:
    """
    Convert quaternions to axis-angle.

    Args:
        quaternions: shape (..., 4), real part first.
    Returns:
        Axis-angle, shape (..., 3).
    """
    norms = torch.norm(quaternions[..., 1:], p=2, dim=-1, keepdim=True)
    half_angles = torch.atan2(norms, quaternions[..., :1])
    sin_half_angles_over_angles = 0.5 * torch.sinc(half_angles / torch.pi)
    return quaternions[..., 1:] / sin_half_angles_over_angles


def axis_angle_to_matrix(axis_angle: torch.Tensor) -> torch.Tensor:
    """
    Convert axis-angle to rotation matrices using the Rodrigues formula.

    R = I + sinc(theta/pi) * K + ((1 - cos(theta)) / theta^2) * K^2

    where K is the (unnormalized) skew-symmetric matrix of the input vector
    and theta is the rotation angle (L2 norm of the input).

    Args:
        axis_angle: shape (..., 3).
    Returns:
        Rotation matrices, shape (..., 3, 3).
    """
    shape = axis_angle.shape
    device, dtype = axis_angle.device, axis_angle.dtype

    angles = torch.norm(axis_angle, p=2, dim=-1, keepdim=True).unsqueeze(-1)

    rx, ry, rz = (
        axis_angle[..., 0],
        axis_angle[..., 1],
        axis_angle[..., 2],
    )
    zeros = torch.zeros(shape[:-1], dtype=dtype, device=device)
    cross_product_matrix = torch.stack(
        [zeros, -rz, ry, rz, zeros, -rx, -ry, rx, zeros], dim=-1
    ).view(shape + (3,))
    cross_product_matrix_sqrd = cross_product_matrix @ cross_product_matrix

    identity = torch.eye(3, dtype=dtype, device=device)
    angles_sqrd = angles * angles
    angles_sqrd = torch.where(angles_sqrd == 0, 1, angles_sqrd)
    return (
        identity.expand(cross_product_matrix.shape)
        + torch.sinc(angles / torch.pi) * cross_product_matrix
        + ((1 - torch.cos(angles)) / angles_sqrd) * cross_product_matrix_sqrd
    )


def matrix_to_axis_angle(matrix: torch.Tensor) -> torch.Tensor:
    """
    Convert rotation matrices to axis-angle.

    Args:
        matrix: shape (..., 3, 3).
    Returns:
        Axis-angle, shape (..., 3).
    """
    return quaternion_to_axis_angle(matrix_to_quaternion(matrix))


def rotation_6d_to_matrix(d6: torch.Tensor) -> torch.Tensor:
    """
    Convert 6D rotation representation to rotation matrices.

    Uses Gram-Schmidt orthogonalization per Zhou et al. (CVPR 2019):
    "On the Continuity of Rotation Representations in Neural Networks."

    Args:
        d6: shape (*, 6).
    Returns:
        Rotation matrices, shape (*, 3, 3).
    """
    a1, a2 = d6[..., :3], d6[..., 3:]
    b1 = F.normalize(a1, dim=-1)
    b2 = a2 - (b1 * a2).sum(-1, keepdim=True) * b1
    b2 = F.normalize(b2, dim=-1)
    b3 = torch.cross(b2, b1, dim=-1)
    return torch.stack((b1, b2, b3), dim=-2)


def matrix_to_rotation_6d(matrix: torch.Tensor) -> torch.Tensor:
    """
    Convert rotation matrices to 6D rotation representation.

    Args:
        matrix: shape (*, 3, 3).
    Returns:
        6D representation, shape (*, 6).
    """
    batch_dim = matrix.size()[:-2]
    return matrix[..., :2, :].clone().reshape(batch_dim + (6,))


def random_quaternions(
    n: int,
    dtype: Optional[torch.dtype] = None,
    device: Optional[torch.device] = None,
) -> torch.Tensor:
    """Generate n random unit quaternions (standard form: w >= 0)."""
    if isinstance(device, str):
        device = torch.device(device)
    o = torch.randn((n, 4), dtype=dtype, device=device)
    s = (o * o).sum(1)
    o = o / _copysign(torch.sqrt(s), o[:, 0])[:, None]
    return o


def random_rotation_matrices(
    n: int,
    dtype: Optional[torch.dtype] = None,
    device: Optional[torch.device] = None,
) -> torch.Tensor:
    """Generate n random rotation matrices."""
    quaternions = random_quaternions(n, dtype=dtype, device=device)
    return quaternion_to_matrix(quaternions)


def quaternion_raw_multiply(
    a: torch.Tensor, b: torch.Tensor
) -> torch.Tensor:
    """Multiply two quaternions without standardization."""
    aw, ax, ay, az = torch.unbind(a, -1)
    bw, bx, by, bz = torch.unbind(b, -1)
    ow = aw * bw - ax * bx - ay * by - az * bz
    ox = aw * bx + ax * bw + ay * bz - az * by
    oy = aw * by - ax * bz + ay * bw + az * bx
    oz = aw * bz + ax * by - ay * bx + az * bw
    return torch.stack((ow, ox, oy, oz), -1)


def quaternion_multiply(
    a: torch.Tensor, b: torch.Tensor
) -> torch.Tensor:
    """Multiply two rotation quaternions (result has w >= 0)."""
    ab = quaternion_raw_multiply(a, b)
    return standardize_quaternion(ab)


def quaternion_invert(quaternion: torch.Tensor) -> torch.Tensor:
    """Get the conjugate/inverse of unit quaternions."""
    scaling = torch.tensor([1, -1, -1, -1], device=quaternion.device)
    return quaternion * scaling


def quaternion_apply(
    quaternion: torch.Tensor, point: torch.Tensor
) -> torch.Tensor:
    """Apply quaternion rotation to 3D points."""
    if point.size(-1) != 3:
        raise ValueError(f"Points are not in 3D, {point.shape}.")
    real_parts = point.new_zeros(point.shape[:-1] + (1,))
    point_as_quaternion = torch.cat((real_parts, point), -1)
    out = quaternion_raw_multiply(
        quaternion_raw_multiply(quaternion, point_as_quaternion),
        quaternion_invert(quaternion),
    )
    return out[..., 1:]
