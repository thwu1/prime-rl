#!/usr/bin/env python3
"""Generate synthetic point cloud data for registration task.

"""
import numpy as np
import h5py
import os

np.random.seed(42)


def generate_trefoil(n_points=600):
    """Generate points sampling a trefoil knot tube."""
    t = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    x = np.sin(t) + 2.0 * np.sin(2.0 * t)
    y = np.cos(t) - 2.0 * np.cos(2.0 * t)
    z = -np.sin(3.0 * t)
    points = np.column_stack([x, y, z])
    points += np.random.normal(0, 0.15, points.shape)
    return points


def axis_angle_to_rotation(axis, angle_deg):
    """Rodrigues rotation formula: axis-angle to 3x3 rotation matrix."""
    if angle_deg == 0:
        return np.eye(3)
    angle = np.radians(angle_deg)
    axis = np.array(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1.0 - np.cos(angle)) * (K @ K)


# Ground truth rigid transforms: (rotation_axis, angle_degrees, translation)
# scan_i = R_i @ reference_points + t_i + noise
TRANSFORMS = [
    ([0, 0, 1],  0, [0.0,  0.0,  0.0]),
    ([0, 0, 1], 30, [0.5, -0.3,  0.2]),
    ([0, 1, 0], 45, [-0.4, 0.6, -0.1]),
    ([1, 0, 0], 55, [0.3,  0.2,  0.7]),
    ([1, 1, 1], 20, [-0.2, 0.1, -0.5]),
]

os.makedirs('/app/data', exist_ok=True)

ref_points = generate_trefoil(600)

with h5py.File('/app/data/scans.h5', 'w') as f:
    f.attrs['format_version'] = '1.0'
    f.attrs['coordinate_system'] = 'right-handed'
    f.attrs['num_scans'] = 5
    f.attrs['units'] = 'meters'

    for idx, (axis, angle, trans) in enumerate(TRANSFORMS):
        R = axis_angle_to_rotation(axis, angle)
        t_vec = np.array(trans, dtype=float)

        transformed = (R @ ref_points.T).T + t_vec
        noisy = transformed + np.random.normal(0, 0.02, transformed.shape)

        # Add outlier points
        n_outliers = len(ref_points) // 10
        mins = noisy.min(axis=0) - 1.0
        maxs = noisy.max(axis=0) + 1.0
        outliers = np.random.uniform(mins, maxs, (n_outliers, 3))

        scan_points = np.vstack([noisy, outliers])
        perm = np.random.permutation(len(scan_points))
        scan_points = scan_points[perm]

        # Add intensity channel (irrelevant but realistic for lidar data)
        intensity = np.random.uniform(0.1, 1.0, len(scan_points))

        grp = f.create_group(f'scan_{idx}')
        grp.create_dataset('points', data=scan_points, dtype='float64')
        grp.create_dataset('intensity', data=intensity, dtype='float64')
        grp.attrs['sensor_id'] = f'lidar_{idx % 2}'
        grp.attrs['timestamp'] = 1700000000 + idx * 300
        grp.attrs['num_points'] = len(scan_points)

print(f"Generated {len(TRANSFORMS)} scans in /app/data/scans.h5")
print(f"{len(ref_points)} inliers + {len(ref_points) // 10} outliers each")
