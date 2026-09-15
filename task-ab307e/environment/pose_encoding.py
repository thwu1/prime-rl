"""
Camera pose encoding/decoding for compact representation.

Encodes camera parameters (extrinsic + intrinsic) into a 9-dimensional vector:
  [0:3]  -- translation T (3D)
  [3:7]  -- rotation quaternion in XYZW order, scalar-last (4D)
  [7:9]  -- field of view [fov_h, fov_w] in radians (2D)

The field of view is related to focal length by:
  fov_h = 2 * arctan(H / (2 * fy))   (vertical FoV from vertical focal length)
  fov_w = 2 * arctan(W / (2 * fx))   (horizontal FoV from horizontal focal length)

This encoding is used in VGGT (Visual Geometry Grounded Transformer) for
predicting camera parameters from visual features.
"""

# Adapted from VGGT pose encoding (facebookresearch/vggt)

import numpy as np
from rotation_utils import mat_to_quat, quat_to_mat


def extri_intri_to_pose_encoding(extrinsics, intrinsics, image_size_hw):
    """
    Encode camera extrinsics and intrinsics into a compact 9D pose vector.

    Args:
        extrinsics: (S, 3, 4) array of camera extrinsic matrices (cam-from-world).
        intrinsics: (S, 3, 3) array of camera intrinsic matrices.
        image_size_hw: tuple (H, W) of image dimensions in pixels.

    Returns:
        (S, 9) array of pose encodings [T(3), quat(4), fov(2)].
    """
    R = extrinsics[:, :3, :3]   # (S, 3, 3)
    T = extrinsics[:, :3, 3]    # (S, 3)

    # Convert rotation matrices to quaternions
    quat = mat_to_quat(R)       # (S, 4) in XYZW order

    H, W = image_size_hw

    # Compute field of view from focal lengths
    fov_h = 2 * np.arctan((H / 2) / intrinsics[:, 0, 0])
    fov_w = 2 * np.arctan((W / 2) / intrinsics[:, 1, 1])

    pose_encoding = np.concatenate([
        T, quat, fov_h[:, np.newaxis], fov_w[:, np.newaxis]
    ], axis=-1).astype(np.float64)

    return pose_encoding


def pose_encoding_to_extri_intri(pose_encoding, image_size_hw):
    """
    Decode a 9D pose vector back to camera extrinsics and intrinsics.

    Args:
        pose_encoding: (S, 9) array of pose encodings.
        image_size_hw: tuple (H, W) of image dimensions in pixels.

    Returns:
        extrinsics: (S, 3, 4) array of camera extrinsic matrices.
        intrinsics: (S, 3, 3) array of camera intrinsic matrices with
                    principal point at (W/2, H/2).
    """
    T = pose_encoding[:, :3]
    quat = pose_encoding[:, 3:7]
    fov_h = pose_encoding[:, 7]
    fov_w = pose_encoding[:, 8]

    # Convert quaternions back to rotation matrices
    R = quat_to_mat(quat)       # (S, 3, 3)
    extrinsics = np.concatenate([R, T[:, :, np.newaxis]], axis=-1)  # (S, 3, 4)

    # Reconstruct intrinsics from field of view
    H, W = image_size_hw
    fy = (H / 2.0) / np.tan(fov_h / 2.0)
    fx = (W / 2.0) / np.tan(fov_w / 2.0)

    S = pose_encoding.shape[0]
    intrinsics = np.zeros((S, 3, 3), dtype=np.float64)
    intrinsics[:, 0, 0] = fx
    intrinsics[:, 1, 1] = fy
    intrinsics[:, 0, 2] = W / 2
    intrinsics[:, 1, 2] = H / 2
    intrinsics[:, 2, 2] = 1.0

    return extrinsics, intrinsics
