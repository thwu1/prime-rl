"""
Quaternion and rotation matrix conversion utilities for 3D vision pipelines.

Convention: Quaternions are stored in XYZW order (scalar-last), i.e., [i, j, k, r]
where i, j, k are the imaginary components and r is the real/scalar component.
This is consistent with the convention used in PyTorch3D and VGGT.
"""

# Copyright (c) Meta Platforms, Inc. and affiliates.
# Adapted from PyTorch3D rotation utilities for NumPy.

import numpy as np


def quat_to_mat(quaternions):
    """
    Convert unit quaternions to rotation matrices.

    Args:
        quaternions: (..., 4) array of unit quaternions in XYZW order (scalar-last).

    Returns:
        (..., 3, 3) array of rotation matrices.
    """
    quaternions = np.asarray(quaternions, dtype=np.float64)
    norms = np.linalg.norm(quaternions, axis=-1, keepdims=True)
    quaternions = quaternions / np.clip(norms, 1e-12, None)

    i = quaternions[..., 0]
    j = quaternions[..., 1]
    k = quaternions[..., 2]
    r = quaternions[..., 3]

    mat = np.stack([
        1 - 2 * (j * j + k * k), 2 * (i * j - k * r), 2 * (i * k + j * r),
        2 * (i * j + k * r), 1 - 2 * (i * i + k * k), 2 * (j * k - i * r),
        2 * (i * k - j * r), 2 * (j * k + i * r), 1 - 2 * (i * i + j * j),
    ], axis=-1)

    return mat.reshape(quaternions.shape[:-1] + (3, 3))


def mat_to_quat(matrix):
    """
    Convert rotation matrices to unit quaternions using Shepperd's method.

    The method selects the quaternion component with the largest magnitude
    as the pivot to avoid numerical instability near singularities.

    Args:
        matrix: (..., 3, 3) array of rotation matrices.

    Returns:
        (..., 4) array of unit quaternions in XYZW order (scalar-last).
        The returned quaternion is standardized so that the scalar part is non-negative.
    """
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape[-2:] != (3, 3):
        raise ValueError(f"Invalid rotation matrix shape {matrix.shape}.")

    batch_shape = matrix.shape[:-2]
    flat = matrix.reshape(-1, 3, 3)
    n = flat.shape[0]
    result = np.zeros((n, 4), dtype=np.float64)

    for idx in range(n):
        m = flat[idx]
        trace = m[0, 0] + m[1, 1] + m[2, 2]

        if trace > 0:
            s = 0.5 / np.sqrt(trace + 1.0)
            r = 0.25 / s
            i = (m[2, 1] - m[1, 2]) * s
            j = (m[0, 2] - m[2, 0]) * s
            k = (m[1, 0] - m[0, 1]) * s
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
            r = (m[2, 1] - m[1, 2]) / s
            i = 0.25 * s
            j = (m[0, 1] + m[1, 0]) / s
            k = (m[0, 2] + m[2, 0]) / s
        elif m[1, 1] > m[2, 2]:
            s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
            r = (m[0, 2] - m[2, 0]) / s
            i = (m[0, 1] + m[1, 0]) / s
            j = 0.25 * s
            k = (m[1, 2] + m[2, 1]) / s
        else:
            s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
            r = (m[1, 0] - m[0, 1]) / s
            i = (m[0, 2] + m[2, 0]) / s
            j = (m[1, 2] + m[2, 1]) / s
            k = 0.25 * s

        # Store in XYZW order: [i, j, k, r]
        result[idx] = [r, i, j, k]

    # Standardize: ensure the real/scalar part (last element) is non-negative
    mask = result[:, 3:4] < 0
    result = np.where(mask, -result, result)

    return result.reshape(batch_shape + (4,))


def standardize_quaternion(quaternions):
    """
    Standardize quaternions so that the real/scalar part (last element) is non-negative.

    Args:
        quaternions: (..., 4) array of quaternions in XYZW order.

    Returns:
        (..., 4) array of standardized quaternions.
    """
    quaternions = np.asarray(quaternions, dtype=np.float64)
    mask = quaternions[..., 3:4] < 0
    return np.where(mask, -quaternions, quaternions)
