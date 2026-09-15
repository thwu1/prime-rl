#!/usr/bin/env python3
"""Generate synthetic point cloud scans stored in HDF5 format."""
import numpy as np
import h5py
import os


def generate_ground_truth_poses():
    """Generate deterministic ground truth poses (no random numbers used).

    Returns world poses and reference-frame poses (scan 0 = identity).
    """
    positions = np.array([
        [-5.0, -4.0, 1.5],
        [-1.0, -4.0, 1.5],
        [ 3.0, -4.0, 1.5],
        [ 6.0, -1.0, 1.5],
        [ 6.0,  3.0, 1.5],
        [ 2.0,  5.0, 1.5],
        [-3.0,  4.0, 1.5],
        [-6.0,  0.0, 1.5],
    ])

    gt_world_poses = []
    for i in range(8):
        next_i = (i + 1) % 8
        dx = positions[next_i, 0] - positions[i, 0]
        dy = positions[next_i, 1] - positions[i, 1]
        heading = np.arctan2(dy, dx)

        c, s = np.cos(heading), np.sin(heading)
        T = np.eye(4)
        T[0, 0] = c
        T[0, 1] = -s
        T[1, 0] = s
        T[1, 1] = c
        T[:3, 3] = positions[i]
        gt_world_poses.append(T)

    gt_world_poses = np.array(gt_world_poses)
    T_ref_inv = np.linalg.inv(gt_world_poses[0])
    gt_poses = np.array([T_ref_inv @ gt_world_poses[i] for i in range(8)])
    return gt_world_poses, gt_poses


def generate_scene():
    """Generate a synthetic indoor environment with walls, floor, ceiling, and pillars."""
    np.random.seed(12345)
    scene_points = []

    n = 5000
    scene_points.append(np.column_stack([
        np.random.uniform(-10, 10, n),
        np.random.uniform(-8, 8, n),
        np.zeros(n)
    ]))

    scene_points.append(np.column_stack([
        np.random.uniform(-10, 10, n),
        np.random.uniform(-8, 8, n),
        np.full(n, 3.5)
    ]))

    n_wall = 2500
    scene_points.append(np.column_stack([
        np.full(n_wall, -10.0),
        np.random.uniform(-8, 8, n_wall),
        np.random.uniform(0, 3.5, n_wall)
    ]))
    scene_points.append(np.column_stack([
        np.full(n_wall, 10.0),
        np.random.uniform(-8, 8, n_wall),
        np.random.uniform(0, 3.5, n_wall)
    ]))
    scene_points.append(np.column_stack([
        np.random.uniform(-10, 10, n_wall),
        np.full(n_wall, -8.0),
        np.random.uniform(0, 3.5, n_wall)
    ]))
    scene_points.append(np.column_stack([
        np.random.uniform(-10, 10, n_wall),
        np.full(n_wall, 8.0),
        np.random.uniform(0, 3.5, n_wall)
    ]))

    pillar_positions = [(-3, -2), (1, -2), (5, -2), (5, 2), (1, 3), (-4, 2)]
    for cx, cy in pillar_positions:
        n_cyl = 1500
        radius = 0.5
        angles = np.random.uniform(0, 2 * np.pi, n_cyl)
        scene_points.append(np.column_stack([
            cx + radius * np.cos(angles),
            cy + radius * np.sin(angles),
            np.random.uniform(0, 3.5, n_cyl)
        ]))

    box_specs = [
        (-7, 0, 1.0, 0.8, 2.5),
        (0, -6, 0.6, 1.2, 1.8),
        (3, 3, 1.5, 0.5, 3.0),
        (-2, 5, 0.8, 0.8, 2.0),
    ]
    for bx, by, sx, sy, sz in box_specs:
        n_face = 400
        scene_points.append(np.column_stack([
            np.full(n_face, bx + sx / 2),
            np.random.uniform(by - sy / 2, by + sy / 2, n_face),
            np.random.uniform(0, sz, n_face)
        ]))
        scene_points.append(np.column_stack([
            np.full(n_face, bx - sx / 2),
            np.random.uniform(by - sy / 2, by + sy / 2, n_face),
            np.random.uniform(0, sz, n_face)
        ]))
        scene_points.append(np.column_stack([
            np.random.uniform(bx - sx / 2, bx + sx / 2, n_face),
            np.full(n_face, by + sy / 2),
            np.random.uniform(0, sz, n_face)
        ]))
        scene_points.append(np.column_stack([
            np.random.uniform(bx - sx / 2, bx + sx / 2, n_face),
            np.full(n_face, by - sy / 2),
            np.random.uniform(0, sz, n_face)
        ]))

    return np.vstack(scene_points)


def generate_scans(scene_points, gt_world_poses):
    """Simulate sensor scans by capturing nearby scene points from each pose."""
    np.random.seed(54321)
    max_range = 8.0
    target_n_points = 2500
    scans = []

    for i in range(8):
        T_inv = np.linalg.inv(gt_world_poses[i])
        local_pts = (T_inv[:3, :3] @ scene_points.T + T_inv[:3, 3:4]).T
        dists = np.linalg.norm(local_pts, axis=1)
        mask = dists < max_range
        scan = local_pts[mask].copy()

        if len(scan) > target_n_points:
            idx = np.random.choice(len(scan), target_n_points, replace=False)
            scan = scan[idx]

        scan += np.random.randn(*scan.shape) * 0.02
        scans.append(scan)

    return scans


def generate_initial_poses(gt_poses):
    """Generate noisy initial pose estimates by perturbing ground truth."""
    np.random.seed(99999)
    init_poses = np.zeros((8, 4, 4))
    init_poses[0] = np.eye(4)

    for i in range(1, 8):
        T = gt_poses[i].copy()
        T[:3, 3] += np.random.randn(3) * 0.3
        axis = np.random.randn(3)
        axis = axis / (np.linalg.norm(axis) + 1e-12)
        angle = np.random.randn() * 0.05
        K = np.array([[0, -axis[2], axis[1]],
                       [axis[2], 0, -axis[0]],
                       [-axis[1], axis[0], 0]])
        R_noise = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)
        T[:3, :3] = R_noise @ T[:3, :3]
        init_poses[i] = T

    return init_poses


if __name__ == '__main__':
    gt_world_poses, gt_poses = generate_ground_truth_poses()
    scene = generate_scene()
    scans = generate_scans(scene, gt_world_poses)
    init_poses = generate_initial_poses(gt_poses)

    os.makedirs('/app/data', exist_ok=True)

    pairs = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 0)]

    with h5py.File('/app/data/scans.h5', 'w') as f:
        scans_group = f.create_group('scans')
        for i, scan in enumerate(scans):
            scans_group.create_dataset(
                'scan_{:03d}'.format(i), data=scan,
                dtype='float64', compression='gzip', compression_opts=4
            )
        f.create_dataset('initial_poses', data=init_poses, dtype='float64')
        f.create_dataset('overlap_pairs',
                         data=np.array(pairs, dtype='int32'))
