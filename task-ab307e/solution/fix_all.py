"""
Fix all bugs in the multi-view geometry pipeline and implement both alignment methods.

Bug 1 (rotation_utils.py): mat_to_quat stores quaternion in WXYZ order [r,i,j,k]
       instead of the documented XYZW order [i,j,k,r].

Bug 2 (geometry_utils.py): depth_to_cam_coords_points divides x by fv and y by fu
       — the focal lengths are swapped.

Bug 3 (geometry_utils.py): closed_form_inverse_se3 computes R^T @ t instead of
       -R^T @ t for the translation component.

Bug 4 (pose_encoding.py): extri_intri_to_pose_encoding uses intrinsics[:,0,0] (fx)
       for vertical FoV and intrinsics[:,1,1] (fy) for horizontal FoV — swapped.

Bug 5 (colmap_io.py): read_images_text stores the quaternion as [qw, qx, qy, qz]
       (WXYZ) without converting to the pipeline's [qx, qy, qz, qw] (XYZW) order.

Implementation 1 (alignment.py): estimate_similarity_transform is a placeholder that
       returns identity. Must implement Umeyama's SVD-based method.

Implementation 2 (alignment.py): robust_estimate_similarity_transform raises
       NotImplementedError. Must implement RANSAC-based robust alignment.
"""



def fix_rotation_utils():
    """Fix quaternion output order from [r,i,j,k] (WXYZ) to [i,j,k,r] (XYZW)."""
    with open("/app/rotation_utils.py", "r") as f:
        content = f.read()

    content = content.replace(
        "result[idx] = [r, i, j, k]",
        "result[idx] = [i, j, k, r]",
    )

    with open("/app/rotation_utils.py", "w") as f:
        f.write(content)
    print("[Fixed] rotation_utils.py: quaternion order [r,i,j,k] -> [i,j,k,r]")


def fix_geometry_utils():
    """Fix swapped focal lengths and missing negative sign in SE3 inverse."""
    with open("/app/geometry_utils.py", "r") as f:
        content = f.read()

    content = content.replace(
        "x_cam = (u - cu) * depth_map / fv",
        "x_cam = (u - cu) * depth_map / fu",
    )
    content = content.replace(
        "y_cam = (v - cv) * depth_map / fu",
        "y_cam = (v - cv) * depth_map / fv",
    )
    content = content.replace(
        "top_right = np.matmul(R_transposed, T)",
        "top_right = -np.matmul(R_transposed, T)",
    )

    with open("/app/geometry_utils.py", "w") as f:
        f.write(content)
    print("[Fixed] geometry_utils.py: focal length swap + SE3 inverse sign")


def fix_pose_encoding():
    """Fix swapped fx/fy in field-of-view computation."""
    with open("/app/pose_encoding.py", "r") as f:
        content = f.read()

    content = content.replace(
        "fov_h = 2 * np.arctan((H / 2) / intrinsics[:, 0, 0])",
        "fov_h = 2 * np.arctan((H / 2) / intrinsics[:, 1, 1])",
    )
    content = content.replace(
        "fov_w = 2 * np.arctan((W / 2) / intrinsics[:, 1, 1])",
        "fov_w = 2 * np.arctan((W / 2) / intrinsics[:, 0, 0])",
    )

    with open("/app/pose_encoding.py", "w") as f:
        f.write(content)
    print("[Fixed] pose_encoding.py: swapped fx/fy in FoV computation")


def fix_colmap_io():
    """Fix quaternion convention: convert COLMAP WXYZ to pipeline XYZW."""
    with open("/app/colmap_io.py", "r") as f:
        content = f.read()

    content = content.replace(
        "quat_xyzw = np.array([qw, qx, qy, qz], dtype=np.float64)",
        "quat_xyzw = np.array([qx, qy, qz, qw], dtype=np.float64)",
    )

    with open("/app/colmap_io.py", "w") as f:
        f.write(content)
    print("[Fixed] colmap_io.py: WXYZ -> XYZW quaternion conversion")


def implement_alignment():
    """Replace placeholder alignment with Umeyama + RANSAC implementations."""
    alignment_code = '''"""
Point cloud alignment using similarity transformations.

Provides two methods:
1. estimate_similarity_transform — Umeyama (1991) SVD-based optimal alignment
2. robust_estimate_similarity_transform — RANSAC wrapper for outlier-contaminated data

The Procrustes problem: Given corresponding 3D points P and Q, find scale s,
rotation R, and translation t minimizing: sum_i || s * R @ P_i + t - Q_i ||^2
"""

import numpy as np


def estimate_similarity_transform(source_points, target_points):
    """
    Estimate a similarity transform (scale, rotation, translation) that
    best aligns source_points to target_points in a least-squares sense.

    Uses the Umeyama (1991) method based on SVD of the cross-covariance matrix.

    The transform is: aligned = scale * (rotation @ source.T).T + translation

    Args:
        source_points: (N, 3) array of source 3D points
        target_points: (N, 3) array of corresponding target 3D points

    Returns:
        scale: scalar scale factor
        rotation: (3, 3) rotation matrix (proper, det=+1)
        translation: (3,) translation vector
    """
    assert source_points.shape == target_points.shape
    assert source_points.shape[0] >= 3, "Need at least 3 points"
    assert source_points.shape[1] == 3

    n = source_points.shape[0]

    # Step 1: Compute centroids
    mu_src = source_points.mean(axis=0)
    mu_tgt = target_points.mean(axis=0)

    # Step 2: Center the point sets
    src_c = source_points - mu_src
    tgt_c = target_points - mu_tgt

    # Step 3: Variance of source points
    var_src = np.mean(np.sum(src_c ** 2, axis=1))

    # Step 4: Cross-covariance matrix
    H = (tgt_c.T @ src_c) / n

    # Step 5: SVD
    U, S, Vt = np.linalg.svd(H)

    # Step 6: Handle reflection (ensure proper rotation with det=+1)
    d = np.linalg.det(U @ Vt)
    D = np.diag([1.0, 1.0, np.sign(d)])

    # Step 7: Optimal rotation
    rotation = U @ D @ Vt

    # Step 8: Optimal scale
    scale = np.sum(S * np.diag(D)) / var_src

    # Step 9: Optimal translation
    translation = mu_tgt - scale * rotation @ mu_src

    return scale, rotation, translation


def robust_estimate_similarity_transform(source_points, target_points,
                                          max_iterations=1000,
                                          inlier_threshold=1.0,
                                          min_inlier_ratio=0.3):
    """
    RANSAC-based robust similarity alignment that handles outlier-contaminated
    point correspondences.

    Iteratively samples minimal subsets (3 points), fits similarity transforms
    using the Umeyama method, and identifies the largest consensus set of inliers.
    After finding the best consensus set, refines the transform using all inliers.

    Args:
        source_points: (N, 3) array of source 3D points
        target_points: (N, 3) array of corresponding target 3D points
        max_iterations: maximum RANSAC iterations
        inlier_threshold: maximum residual for a point to be considered an inlier
        min_inlier_ratio: minimum fraction of inliers for a valid model

    Returns:
        scale: scalar scale factor
        rotation: (3, 3) rotation matrix (proper, det=+1)
        translation: (3,) translation vector
        inlier_mask: (N,) boolean array indicating inlier points
    """
    assert source_points.shape == target_points.shape
    n = source_points.shape[0]

    best_inlier_mask = np.zeros(n, dtype=bool)
    best_num_inliers = 0
    best_s, best_R, best_t = 1.0, np.eye(3), np.zeros(3)

    rng = np.random.default_rng(0)

    for _ in range(max_iterations):
        # Sample 3 random points (minimum for similarity transform)
        indices = rng.choice(n, 3, replace=False)

        try:
            s, R, t = estimate_similarity_transform(
                source_points[indices], target_points[indices]
            )
        except Exception:
            continue

        # Compute residuals for all points
        aligned = s * (R @ source_points.T).T + t
        residuals = np.linalg.norm(aligned - target_points, axis=1)

        # Identify inliers
        inlier_mask = residuals < inlier_threshold
        num_inliers = np.sum(inlier_mask)

        if num_inliers > best_num_inliers:
            best_num_inliers = num_inliers
            best_inlier_mask = inlier_mask.copy()
            best_s, best_R, best_t = s, R, t

    # Refine using all inliers from the best model
    if best_num_inliers >= 3:
        best_s, best_R, best_t = estimate_similarity_transform(
            source_points[best_inlier_mask], target_points[best_inlier_mask]
        )
        # Recompute inliers with refined transform
        aligned = best_s * (best_R @ source_points.T).T + best_t
        residuals = np.linalg.norm(aligned - target_points, axis=1)
        best_inlier_mask = residuals < inlier_threshold

    return best_s, best_R, best_t, best_inlier_mask


def apply_similarity_transform(points, scale, rotation, translation):
    """Apply a similarity transform to a set of 3D points.

    Args:
        points: (N, 3) array of 3D points
        scale: scalar scale factor
        rotation: (3, 3) rotation matrix
        translation: (3,) translation vector

    Returns:
        (N, 3) array of transformed points: scale * R @ p + t
    """
    return scale * (rotation @ points.T).T + translation


def compute_alignment_error(source_points, target_points):
    """
    Compute the RMSE after optimal similarity alignment.

    Args:
        source_points: (N, 3) source 3D points
        target_points: (N, 3) corresponding target 3D points

    Returns:
        rmse: root mean squared error after alignment
        scale: estimated scale
        rotation: estimated rotation
        translation: estimated translation
    """
    scale, rotation, translation = estimate_similarity_transform(
        source_points, target_points
    )
    aligned = apply_similarity_transform(source_points, scale, rotation, translation)
    errors = np.linalg.norm(aligned - target_points, axis=1)
    rmse = np.sqrt(np.mean(errors ** 2))
    return rmse, scale, rotation, translation
'''
    with open("/app/alignment.py", "w") as f:
        f.write(alignment_code)
    print("[Implemented] alignment.py: Umeyama + RANSAC similarity alignment")


if __name__ == "__main__":
    fix_rotation_utils()
    fix_geometry_utils()
    fix_pose_encoding()
    fix_colmap_io()
    implement_alignment()
    print("\nAll fixes applied and both alignment methods implemented.")
