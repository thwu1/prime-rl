
"""RANSAC-based robust relative pose estimation with affine depth correction."""

import numpy as np
from .types import AffineParams, PoseResult
from .minimal_solver import solve_affine_depth
from .pose_recovery import recover_pose, find_rotation


def ransac_estimate(x1: np.ndarray, x2: np.ndarray,
                    d1: np.ndarray, d2: np.ndarray,
                    n_iterations: int = 100,
                    inlier_threshold: float = 0.1) -> PoseResult:
    """RANSAC-based robust pose estimation with affine depth correction."""
    n_points = x1.shape[0]

    best_result = None
    best_n_inliers = 0

    for _ in range(n_iterations):
        # Sample 3 random points
        idx = np.random.choice(n_points, 3, replace=False)

        try:
            solutions = solve_affine_depth(x1[idx], x2[idx], d1[idx], d2[idx])
        except (np.linalg.LinAlgError, ValueError, ZeroDivisionError):
            continue

        for sol in solutions:
            if sol.a2 <= 1e-12:
                continue

            # Correct all depths with this candidate solution
            d1_c = sol.a1 * d1 + sol.b1
            d2_c = sol.a2 * d2 + sol.b2

            # Skip if any corrected depth is non-positive
            if np.any(d1_c <= 0) or np.any(d2_c <= 0):
                # Only check sample points for positivity
                if np.any(d1_c[idx] <= 0) or np.any(d2_c[idx] <= 0):
                    continue

            # Reconstruct 3D points
            X1_all = x1 * d1_c[:, None]
            X2_all = x2 * d2_c[:, None]

            # Estimate pose from the 3 sample points
            try:
                R, t = find_rotation(X1_all[idx], X2_all[idx])
            except np.linalg.LinAlgError:
                continue

            # Compute residuals for all points
            X2_pred = X1_all @ R.T + t
            residuals = np.linalg.norm(X2_all - X2_pred, axis=1)

            # Normalize by point cloud scale
            scale = np.mean(np.linalg.norm(X1_all, axis=1))
            if scale < 1e-10:
                continue
            relative_residuals = residuals / scale

            inlier_mask = relative_residuals < inlier_threshold
            n_inliers = np.sum(inlier_mask)

            if n_inliers > best_n_inliers:
                best_n_inliers = n_inliers

                # Refine pose on all inliers
                if n_inliers >= 3:
                    try:
                        R_ref, t_ref = find_rotation(
                            X1_all[inlier_mask], X2_all[inlier_mask])
                    except np.linalg.LinAlgError:
                        R_ref, t_ref = R, t
                else:
                    R_ref, t_ref = R, t

                best_result = PoseResult(
                    R=R_ref, t=t_ref,
                    affine=sol, inlier_mask=inlier_mask
                )

    if best_result is None:
        # Fallback: use first 3 points
        solutions = solve_affine_depth(x1[:3], x2[:3], d1[:3], d2[:3])
        if solutions:
            result = recover_pose(x1, x2, d1, d2, solutions[0])
            result.inlier_mask = np.ones(n_points, dtype=bool)
            return result
        raise RuntimeError("RANSAC failed to find any valid solution")

    return best_result
