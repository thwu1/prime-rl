"""
rotation_analysis.py — SO(3) analysis operations for rotation calibration.

Complete implementation of geodesic_distance, slerp, and karcher_mean.
"""


import sys
import torch
import math

sys.path.insert(0, "/app")
from rotation_lib import (
    quaternion_to_matrix,
    matrix_to_quaternion,
    axis_angle_to_matrix,
    matrix_to_axis_angle,
    standardize_quaternion,
)


def geodesic_distance(R1: torch.Tensor, R2: torch.Tensor) -> torch.Tensor:
    """
    Compute geodesic distance on SO(3) between pairs of rotation matrices.

    d(R1, R2) = arccos(clamp((trace(R1 @ R2^T) - 1) / 2, -1, 1))
    """
    R_rel = torch.matmul(R1, R2.transpose(-1, -2))
    trace = torch.diagonal(R_rel, dim1=-2, dim2=-1).sum(-1)
    cos_angle = (trace - 1.0) / 2.0
    cos_angle = torch.clamp(cos_angle, -1.0, 1.0)
    return torch.acos(cos_angle)


def slerp(q1: torch.Tensor, q2: torch.Tensor, t: float) -> torch.Tensor:
    """
    Spherical linear interpolation between unit quaternions.

    Handles antipodal quaternions and near-degenerate angles.
    """
    # Ensure shortest path: negate q2 if dot product is negative
    dot = (q1 * q2).sum(dim=-1, keepdim=True)
    q2_adj = torch.where(dot < 0, -q2, q2)
    dot = dot.abs().clamp(0.0, 1.0)

    omega = torch.acos(dot)
    sin_omega = torch.sin(omega)

    # Detect near-zero angle for lerp fallback
    small = sin_omega.abs() < 1e-6

    s1 = torch.sin((1.0 - t) * omega) / sin_omega
    s2 = torch.sin(t * omega) / sin_omega

    s1 = torch.where(small, torch.full_like(s1, 1.0 - t), s1)
    s2 = torch.where(small, torch.full_like(s2, t), s2)

    result = s1 * q1 + s2 * q2_adj
    return result / result.norm(dim=-1, keepdim=True)


def karcher_mean(
    quaternions: torch.Tensor,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> torch.Tensor:
    """
    Compute the Karcher (Frechet) mean on SO(3) via iterative
    tangent-space averaging.
    """
    N = quaternions.shape[0]
    mu_q = quaternions[0].clone()

    for _ in range(max_iter):
        mu_R = quaternion_to_matrix(mu_q.unsqueeze(0))[0]

        # Map each input to tangent space at current mean
        tangent_vectors = []
        for i in range(N):
            Ri = quaternion_to_matrix(quaternions[i].unsqueeze(0))[0]
            delta_R = Ri @ mu_R.T
            aa = matrix_to_axis_angle(delta_R.unsqueeze(0))[0]
            tangent_vectors.append(aa)

        tv = torch.stack(tangent_vectors)
        v_mean = tv.mean(dim=0)

        step_size = v_mean.norm().item()
        if step_size < tol:
            break

        # Exp map: update mean
        delta_R = axis_angle_to_matrix(v_mean.unsqueeze(0))[0]
        mu_R_new = delta_R @ mu_R
        mu_q = matrix_to_quaternion(mu_R_new.unsqueeze(0))[0]
        mu_q = standardize_quaternion(mu_q.unsqueeze(0))[0]

    return mu_q
