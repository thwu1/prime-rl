"""Generate synthetic point cloud data for topological data analysis task.

Creates 12 point clouds: 4 circles, 4 spheres, 4 tori, each sampled with
100 points and with increasing noise levels (0.05, 0.10, 0.15, 0.20).
"""
import numpy as np
import json
import os

def generate_data():
    rng = np.random.RandomState(42)
    n_points = 100
    clouds = []

    # --- 4 circles (unit circle in the xy-plane) ---
    for i in range(4):
        noise_std = 0.05 + 0.05 * i
        theta = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
        pts = np.column_stack([np.cos(theta), np.sin(theta), np.zeros(n_points)])
        pts += noise_std * rng.randn(n_points, 3)
        clouds.append(pts)

    # --- 4 spheres (unit sphere, Fibonacci lattice sampling) ---
    for i in range(4):
        noise_std = 0.05 + 0.05 * i
        golden_ratio = (1 + np.sqrt(5)) / 2
        indices = np.arange(n_points, dtype=float)
        theta = 2 * np.pi * indices / golden_ratio
        phi = np.arccos(1 - 2 * (indices + 0.5) / n_points)
        x = np.sin(phi) * np.cos(theta)
        y = np.sin(phi) * np.sin(theta)
        z = np.cos(phi)
        pts = np.column_stack([x, y, z])
        pts += noise_std * rng.randn(n_points, 3)
        clouds.append(pts)

    # --- 4 tori (major radius R=2, minor radius r=1) ---
    for i in range(4):
        noise_std = 0.05 + 0.05 * i
        theta = rng.uniform(0, 2 * np.pi, n_points)
        phi = rng.uniform(0, 2 * np.pi, n_points)
        R, r = 2.0, 1.0
        x = (R + r * np.cos(theta)) * np.cos(phi)
        y = (R + r * np.cos(theta)) * np.sin(phi)
        z = r * np.sin(theta)
        pts = np.column_stack([x, y, z])
        pts += noise_std * rng.randn(n_points, 3)
        clouds.append(pts)

    os.makedirs('/app/data', exist_ok=True)
    np.save('/app/data/point_clouds.npy', np.array(clouds))

    metadata = {
        "n_clouds": 12,
        "n_points_per_cloud": n_points,
        "embedding_dimension": 3,
        "n_types": 3,
        "clouds_per_type": 4,
        "noise_levels": [0.05, 0.10, 0.15, 0.20],
        "noise_type": "gaussian"
    }
    with open('/app/data/metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)


if __name__ == '__main__':
    generate_data()
