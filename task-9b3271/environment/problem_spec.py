"""
Monocular Depth-Corrected Relative Pose Estimation
===================================================


Problem Statement
-----------------
Given two camera views observing the same 3D scene, with:
  - 2D point correspondences: x1[i] in camera 1, x2[i] in camera 2 (homogeneous, z=1)
  - Monocular depth estimates: d1[i] for camera 1, d2[i] for camera 2

The monocular depths are related to true depths by unknown per-view affine params:
    true_depth_1[i] = a1 * d1[i] + b1
    true_depth_2[i] = a2 * d2[i] + b2

where (a1, b1) and (a2, b2) are unknown scale-shift parameters.

Goal: recover the relative camera pose (rotation R, translation t) such that the
3D points are consistent across views: X2[i] = R @ X1[i] + t.

Mathematical Formulation
------------------------
Fix a1 = 1 to resolve the global scale ambiguity. The corrected depths are:
    D1[i] = d1[i] + b1
    D2[i] = a2 * d2[i] + b2

The 3D points in each camera frame:
    X1[i] = x1[i] * D1[i]
    X2[i] = x2[i] * D2[i]

Key constraint (distance consistency): since rigid transforms preserve distances,
for each pair of points (i, j):

    || X1[i] - X1[j] ||^2 = || X2[i] - X2[j] ||^2

Expanding:
    D1[i]^2 * (x1[i] . x1[i]) + D1[j]^2 * (x1[j] . x1[j]) - 2 * D1[i] * D1[j] * (x1[i] . x1[j])
  = D2[i]^2 * (x2[i] . x2[i]) + D2[j]^2 * (x2[j] . x2[j]) - 2 * D2[i] * D2[j] * (x2[i] . x2[j])

With 3 points, we get 3 independent pairwise constraints (pairs (0,1), (0,2), (1,2)).
After substituting D1[k] = d1[k] + b1 and D2[k] = a2*d2[k] + b2, each constraint
becomes a degree-2 polynomial equation in the 3 unknowns (b1, a2, b2).

Coefficient Computation
-----------------------
The polynomial coefficients for the 3-constraint system are computed by the C library
at /app/coeffgen.c. Compile it to a shared library and call it from Python.

The C function ``compute_coefficients`` takes the 3-point correspondences and depths
and produces 18 coefficients (6 per point pair). See the header documentation in
coeffgen.c for the monomial ordering:

    c[6k+0]*b2^2 + c[6k+1]*b1^2 + c[6k+2]*a2*b2 + c[6k+3]*a2^2
      + c[6k+4]*b1 + c[6k+5] = 0

for each pair k = 0, 1, 2. This is a system of 3 polynomial equations of degree 2
in 3 unknowns (b1, a2, b2), which generally has a finite number of isolated solutions.

Function Signatures
-------------------
"""

import numpy as np
import json
import os


def load_scenario(scenario_path):
    """Load a test scenario from a JSON file.

    Returns dict with keys:
        x1: ndarray (N, 3) - homogeneous 2D coords in camera 1
        x2: ndarray (N, 3) - homogeneous 2D coords in camera 2
        d1: ndarray (N,) - observed depths in camera 1
        d2: ndarray (N,) - observed depths in camera 2
        R_gt: ndarray (3, 3) - ground truth rotation
        t_gt: ndarray (3,) - ground truth translation (unit norm)
        a1_gt, b1_gt, a2_gt, b2_gt: float - ground truth scale/shift
        num_points: int - total number of correspondences
        num_inliers: int - number of inlier correspondences
        is_inlier: list of bool - inlier flags
    """
    with open(scenario_path, 'r') as f:
        data = json.load(f)

    return {
        'x1': np.array(data['x1']),
        'x2': np.array(data['x2']),
        'd1': np.array(data['d1']),
        'd2': np.array(data['d2']),
        'R_gt': np.array(data['R_gt']),
        't_gt': np.array(data['t_gt']),
        'a1_gt': data['a1_gt'],
        'b1_gt': data['b1_gt'],
        'a2_gt': data['a2_gt'],
        'b2_gt': data['b2_gt'],
        'num_points': data['num_points'],
        'num_inliers': data['num_inliers'],
        'is_inlier': data['is_inlier'],
    }


# ---------------------------------------------------------------------------
# Required function signatures for /app/solver.py
# ---------------------------------------------------------------------------
#
# def solve_scale_shift(x1, x2, d1, d2):
#     """Minimal 3-point solver for depth scale/shift parameters.
#
#     Given 3 pairs of 2D correspondences (homogeneous) and their observed
#     depths, find all real solutions (a1, b1, a2, b2) with a1=1 that satisfy
#     the distance consistency constraints.
#
#     Must use the compiled C library /app/libcoeffgen.so for coefficient
#     computation via ctypes.
#
#     Args:
#         x1: ndarray (3, 3) - three homogeneous 2D points in camera 1
#                               (x1[k] is the k-th point, shape (3,))
#         x2: ndarray (3, 3) - three homogeneous 2D points in camera 2
#         d1: ndarray (3,) - observed depths in camera 1
#         d2: ndarray (3,) - observed depths in camera 2
#
#     Returns:
#         list of tuples (a1, b1, a2, b2) where a1=1.0 always.
#         Each tuple represents one real solution.
#         Filter out solutions with complex or NaN components.
#     """
#
# def estimate_rotation(source_pts, target_pts):
#     """Optimal rotation estimation from paired point sets.
#
#     Finds R that minimizes || target_pts - R @ source_pts ||_F.
#     Points should be zero-mean (centered) when translation is present.
#
#     Args:
#         source_pts: ndarray (3, N) - source 3D points (columns)
#         target_pts: ndarray (3, N) - target 3D points (columns)
#
#     Returns:
#         R: ndarray (3, 3) - proper rotation matrix (det(R) = +1)
#     """
#
# def recover_translation(X1, X2, R):
#     """Recover unit translation from paired 3D points and rotation.
#
#     Assumes X2[i] = R @ X1[i] + t for each point.
#
#     Args:
#         X1: ndarray (N, 3) - 3D points in frame 1 (rows)
#         X2: ndarray (N, 3) - 3D points in frame 2 (rows)
#         R: ndarray (3, 3) - rotation matrix
#
#     Returns:
#         t: ndarray (3,) - unit translation vector
#     """
#
# def robust_pose_estimate(x1s, x2s, d1s, d2s, threshold=0.01,
#                          max_iterations=1000):
#     """Robust pose estimation with outlier rejection.
#
#     Given N correspondences (some of which may be outliers), estimate
#     the relative camera pose using the 3-point minimal solver.
#
#     Args:
#         x1s: ndarray (N, 3) - 2D correspondences in camera 1 (homogeneous)
#         x2s: ndarray (N, 3) - 2D correspondences in camera 2 (homogeneous)
#         d1s: ndarray (N,) - observed depths in camera 1
#         d2s: ndarray (N,) - observed depths in camera 2
#         threshold: float - inlier residual threshold
#         max_iterations: int - maximum iterations
#
#     Returns:
#         R: ndarray (3, 3) - rotation matrix
#         t: ndarray (3,) - unit translation vector
#         params: tuple (a1, b1, a2, b2) - best scale/shift parameters
#         inlier_mask: ndarray (N,) bool - inlier flags
#     """
