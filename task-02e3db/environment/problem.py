"""Synthetic bundle adjustment problem generator.

Creates a deterministic 5-camera, 50-point scene with noisy pixel
observations, noisy depth measurements, and an initial estimate that
has a 2x global scale drift (a gauge ambiguity that pure reprojection
BA cannot resolve -- depth anchoring is required).
"""
import numpy as np
from se3 import transform_point


def generate_problem():
    """Generate synthetic multi-view BA problem.

    Returns
    -------
    dict with keys:
        camera       : {fx, fy, cx, cy}
        true_poses   : list of (R[3x3], t[3]) ground-truth poses
        true_points  : (50, 3) ground-truth 3D points
        observations : list of observation dicts
        init_poses   : list of (R, t) with 2x scale drift
        init_points  : (50, 3) with 2x scale drift
    """
    rng = np.random.RandomState(42)
    cam = {'fx': 600.0, 'fy': 600.0, 'cx': 320.0, 'cy': 240.0}

    # 5 cameras along +X at 0.1 m spacing, identity rotation, looking down +Z
    positions = [np.array([i * 0.1, 0.0, 0.0]) for i in range(5)]
    # Pose stores world->cam: R=I, t = -camera_position
    true_poses = [(np.eye(3), -p.copy()) for p in positions]

    # 50 3D points scattered at depth ~2.5-5.5 m in front of cameras
    true_points = np.zeros((50, 3))
    for k in range(50):
        kf = float(k)
        true_points[k] = [
            np.sin(kf * 0.37) * 1.2 + np.cos(kf * 0.13) * 0.4,
            np.cos(kf * 0.29) * 0.9 + np.sin(kf * 0.11) * 0.3,
            4.0 + np.sin(kf * 0.41) * 1.5,
        ]

    # Build observations with pixel noise (sigma=0.3 px) and depth noise (sigma=2%)
    observations = []
    for pi, (R, t) in enumerate(true_poses):
        for xi in range(50):
            pc = transform_point(R, t, true_points[xi])
            if pc[2] <= 0.2:
                continue
            u = cam['fx'] * pc[0] / pc[2] + cam['cx'] + 0.3 * rng.randn()
            v = cam['fy'] * pc[1] / pc[2] + cam['cy'] + 0.3 * rng.randn()
            d_sigma = max(0.02 * pc[2], 1e-6)
            d_meas = float(pc[2] + 0.02 * pc[2] * rng.randn())
            observations.append({
                'pose_idx': pi,
                'point_idx': xi,
                'pixel': np.array([u, v]),
                'depth_meas': d_meas,
                'depth_sigma': d_sigma,
                'fixed_pose': (pi == 0),  # anchor first pose
            })

    # Initial estimates: 2x scale drift
    # Scaling both poses and points by the same factor preserves reprojection
    # (gauge ambiguity), so reprojection-only BA cannot recover the true scale.
    init_poses = [(R.copy(), t * (2.0 if i > 0 else 1.0))
                  for i, (R, t) in enumerate(true_poses)]
    init_points = true_points * 2.0

    return {
        'camera': cam,
        'true_poses': true_poses,
        'true_points': true_points,
        'observations': observations,
        'init_poses': init_poses,
        'init_points': init_points.copy(),
    }
