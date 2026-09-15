"""Generate test scenarios for monocular depth-corrected pose estimation.

"""

import numpy as np
import json
import os


def _random_rotation(rng):
    """Generate a bounded rotation (axis-angle, up to ~45 degrees)."""
    axis = rng.standard_normal(3)
    axis = axis / np.linalg.norm(axis)
    angle = rng.uniform(0.05, 0.8)
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def generate_scenario(seed, num_inliers=20, num_outliers=5, noise_level=0.0):
    rng = np.random.RandomState(seed)

    R = _random_rotation(rng)
    t = rng.standard_normal(3) * 0.5
    t = t / np.linalg.norm(t)

    a1 = 1.0
    b1 = rng.standard_normal() * 0.5
    a2 = rng.uniform(0.5, 2.0)
    b2 = rng.standard_normal() * 0.5

    x1_list, x2_list, d1_list, d2_list = [], [], [], []

    attempts = 0
    while len(x1_list) < num_inliers and attempts < num_inliers * 10:
        attempts += 1
        X = rng.standard_normal(3) * 1.5 + np.array([0.0, 0.0, 5.0])
        if X[2] < 0.5:
            continue

        d1_true = X[2]
        x1_h = X / d1_true

        X2 = R @ X + t
        if X2[2] < 0.5:
            continue

        d2_true = X2[2]
        x2_h = X2 / d2_true

        d1_obs = (d1_true - b1) / a1
        d2_obs = (d2_true - b2) / a2

        if noise_level > 0:
            x1_h = x1_h + np.array([rng.standard_normal() * noise_level,
                                     rng.standard_normal() * noise_level, 0.0])
            x2_h = x2_h + np.array([rng.standard_normal() * noise_level,
                                     rng.standard_normal() * noise_level, 0.0])

        x1_list.append(x1_h)
        x2_list.append(x2_h)
        d1_list.append(float(d1_obs))
        d2_list.append(float(d2_obs))

    actual_inliers = len(x1_list)

    for _ in range(num_outliers):
        x1_list.append(np.array([rng.standard_normal(), rng.standard_normal(), 1.0]))
        x2_list.append(np.array([rng.standard_normal(), rng.standard_normal(), 1.0]))
        d1_list.append(float(rng.uniform(0.5, 10.0)))
        d2_list.append(float(rng.uniform(0.5, 10.0)))

    is_inlier = [True] * actual_inliers + [False] * num_outliers
    indices = rng.permutation(len(x1_list)).tolist()
    x1_list = [x1_list[i] for i in indices]
    x2_list = [x2_list[i] for i in indices]
    d1_list = [d1_list[i] for i in indices]
    d2_list = [d2_list[i] for i in indices]
    is_inlier = [is_inlier[i] for i in indices]

    return {
        'x1': [x.tolist() for x in x1_list],
        'x2': [x.tolist() for x in x2_list],
        'd1': d1_list,
        'd2': d2_list,
        'R_gt': R.tolist(),
        't_gt': t.tolist(),
        'a1_gt': float(a1),
        'b1_gt': float(b1),
        'a2_gt': float(a2),
        'b2_gt': float(b2),
        'num_points': len(x1_list),
        'num_inliers': actual_inliers,
        'noise_level': float(noise_level),
        'is_inlier': is_inlier,
    }


if __name__ == '__main__':
    os.makedirs('/app/data', exist_ok=True)
    for i in range(5):
        scenario = generate_scenario(
            seed=42 + i,
            num_inliers=25,
            num_outliers=8,
            noise_level=0.0,
        )
        path = f'/app/data/scenario_{i}.json'
        with open(path, 'w') as f:
            json.dump(scenario, f, indent=2)
    print("Generated 5 scenarios in /app/data/")
