"""
3D geometry utilities for depth unprojection, SE3 operations, and point projection.

Camera conventions (OpenCV):
- Coordinate system: x-right, y-down, z-forward
- Extrinsic matrix: 3x4 [R|t] transforming world coordinates to camera coordinates
- Intrinsic matrix: 3x3 [[fx, 0, cx], [0, fy, cy], [0, 0, 1]]
  where fx, fy are focal lengths and (cx, cy) is the principal point
"""

# Adapted from VGGT geometry utilities (facebookresearch/vggt)

import numpy as np


def depth_to_cam_coords_points(depth_map, intrinsic):
    """
    Convert a depth map to 3D points in camera coordinates.

    For each pixel (u, v) with depth d, computes:
        x_cam = (u - cx) * d / fx
        y_cam = (v - cy) * d / fy
        z_cam = d

    Args:
        depth_map: (H, W) array of depth values.
        intrinsic: (3, 3) camera intrinsic matrix.

    Returns:
        (H, W, 3) array of 3D points in camera coordinates.
    """
    H, W = depth_map.shape
    assert intrinsic.shape == (3, 3), "Intrinsic matrix must be 3x3"
    assert intrinsic[0, 1] == 0 and intrinsic[1, 0] == 0, "Intrinsic matrix must have zero skew"

    # Extract intrinsic parameters
    fu, fv = intrinsic[0, 0], intrinsic[1, 1]
    cu, cv = intrinsic[0, 2], intrinsic[1, 2]

    # Generate grid of pixel coordinates
    u, v = np.meshgrid(np.arange(W), np.arange(H))

    # Unproject to camera coordinates
    x_cam = (u - cu) * depth_map / fv
    y_cam = (v - cv) * depth_map / fu
    z_cam = depth_map

    cam_coords = np.stack((x_cam, y_cam, z_cam), axis=-1).astype(np.float64)
    return cam_coords


def closed_form_inverse_se3(se3):
    """
    Compute the inverse of SE3 transformation matrices using the closed-form formula.

    For an SE3 matrix M = [R|t], the inverse is M^{-1} = [R^T | -R^T t].
    This avoids expensive general matrix inversion.

    Args:
        se3: (N, 3, 4) or (N, 4, 4) array of SE3 matrices.

    Returns:
        (N, 4, 4) array of inverted SE3 matrices.
    """
    se3 = np.asarray(se3, dtype=np.float64)

    if se3.shape[-2:] not in [(4, 4), (3, 4)]:
        raise ValueError(f"se3 must be of shape (N,4,4) or (N,3,4), got {se3.shape}.")

    R = se3[:, :3, :3]       # (N, 3, 3)
    T = se3[:, :3, 3:]       # (N, 3, 1)

    R_transposed = np.transpose(R, (0, 2, 1))  # (N, 3, 3)
    top_right = np.matmul(R_transposed, T)      # (N, 3, 1)

    inverted = np.tile(np.eye(4), (len(R), 1, 1))
    inverted[:, :3, :3] = R_transposed
    inverted[:, :3, 3:] = top_right

    return inverted


def depth_to_world_coords_points(depth_map, extrinsic, intrinsic, eps=1e-8):
    """
    Convert a depth map to 3D world coordinates.

    Pipeline: pixel coordinates + depth -> camera coordinates -> world coordinates
    (via inverse of extrinsic matrix).

    Args:
        depth_map: (H, W) array of depth values.
        extrinsic: (3, 4) camera extrinsic matrix (cam-from-world, OpenCV convention).
        intrinsic: (3, 3) camera intrinsic matrix.
        eps: Minimum depth threshold for valid points.

    Returns:
        world_coords: (H, W, 3) array of 3D world coordinates.
        cam_coords: (H, W, 3) array of 3D camera coordinates.
        point_mask: (H, W) boolean mask of valid depth values.
    """
    if depth_map is None:
        return None, None, None

    point_mask = depth_map > eps

    # Step 1: Unproject depth to camera coordinates
    cam_coords = depth_to_cam_coords_points(depth_map, intrinsic)

    # Step 2: Transform camera coordinates to world coordinates
    cam_to_world = closed_form_inverse_se3(extrinsic[np.newaxis])[0]

    R_c2w = cam_to_world[:3, :3]
    t_c2w = cam_to_world[:3, 3]

    world_coords = np.dot(cam_coords, R_c2w.T) + t_c2w

    return world_coords, cam_coords, point_mask


def project_points_to_camera(world_points, extrinsic, intrinsic):
    """
    Project 3D world points to 2D pixel coordinates.

    Args:
        world_points: (N, 3) array of 3D world points.
        extrinsic: (3, 4) camera extrinsic matrix (cam-from-world).
        intrinsic: (3, 3) camera intrinsic matrix.

    Returns:
        pixel_coords: (N, 2) array of pixel coordinates [u, v].
        depths: (N,) array of depth values in camera coordinates.
    """
    R = extrinsic[:3, :3]
    t = extrinsic[:3, 3]
    cam_points = (R @ world_points.T).T + t  # (N, 3)

    depths = cam_points[:, 2]

    fx, fy = intrinsic[0, 0], intrinsic[1, 1]
    cx, cy = intrinsic[0, 2], intrinsic[1, 2]

    u = fx * cam_points[:, 0] / cam_points[:, 2] + cx
    v = fy * cam_points[:, 1] / cam_points[:, 2] + cy

    pixel_coords = np.stack([u, v], axis=-1)
    return pixel_coords, depths
