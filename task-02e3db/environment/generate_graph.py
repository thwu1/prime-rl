"""Generate synthetic pose graph dataset for PGO benchmarking.

Creates a 40-pose circular trajectory with sequential odometry edges,
correct loop closure edges, and outlier loop closure edges.
Writes to /app/pose_graph.json.
"""
import numpy as np
import json
from se3 import rodrigues, se3_inverse, se3_compose


def generate_and_save(output_path='/app/pose_graph.json'):
    rng = np.random.RandomState(54321)
    n_poses = 40
    radius = 5.0

    # Ground truth: circular trajectory in XY plane with Z oscillation
    true_poses = []
    for i in range(n_poses):
        angle = 2.0 * np.pi * i / n_poses
        cx = radius * np.cos(angle)
        cy = radius * np.sin(angle)
        cz = 0.3 * np.sin(2.0 * angle)
        heading = angle + np.pi / 2.0
        R_world = rodrigues(np.array([0.0, 0.0, heading]))
        R_wc = R_world.T
        t_wc = -R_wc @ np.array([cx, cy, cz])
        true_poses.append((R_wc, t_wc))

    edges = []
    odom_weight = 30000.0
    lc_weight = 3.0

    # Sequential odometry edges (0->1, 1->2, ..., 38->39)
    for i in range(n_poses - 1):
        j = i + 1
        Ri, ti = true_poses[i]
        Rj, tj = true_poses[j]
        Ri_inv, ti_inv = se3_inverse(Ri, ti)
        R_rel, t_rel = se3_compose(Rj, tj, Ri_inv, ti_inv)
        noise_t = 0.005 * rng.randn(3)
        noise_r = np.radians(0.05) * rng.randn(3)
        R_meas = rodrigues(noise_r) @ R_rel
        t_meas = t_rel + noise_t
        edges.append({
            'i': i, 'j': j,
            'R': R_meas, 't': t_meas,
            'info_weight': odom_weight,
        })

    # Loop closures (correct)
    loop_closures = [
        (39, 0, 0.01, 0.1),
        (0, 20, 0.015, 0.15),
        (10, 30, 0.015, 0.15),
        (5, 15, 0.02, 0.2),
        (15, 25, 0.02, 0.2),
        (25, 35, 0.02, 0.2),
        (30, 0, 0.02, 0.2),
        (5, 35, 0.02, 0.2),
        (20, 0, 0.02, 0.2),
    ]
    for a, b, noise_t_scale, noise_r_deg in loop_closures:
        Ri, ti = true_poses[a]
        Rj, tj = true_poses[b]
        Ri_inv, ti_inv = se3_inverse(Ri, ti)
        R_rel, t_rel = se3_compose(Rj, tj, Ri_inv, ti_inv)
        noise_t = noise_t_scale * rng.randn(3)
        noise_r = np.radians(noise_r_deg) * rng.randn(3)
        R_meas = rodrigues(noise_r) @ R_rel
        t_meas = t_rel + noise_t
        edges.append({
            'i': a, 'j': b,
            'R': R_meas, 't': t_meas,
            'info_weight': lc_weight,
        })

    # Outlier loop closures (deliberately wrong measurements)
    for a, b in [(5, 25), (15, 35)]:
        R_meas = rodrigues(rng.randn(3) * 1.5)
        t_meas = rng.randn(3) * 8.0
        edges.append({
            'i': a, 'j': b,
            'R': R_meas, 't': t_meas,
            'info_weight': lc_weight,
        })

    # Initial estimate: dead-reckoning from odometry with drift
    init_poses = [(true_poses[0][0].copy(), true_poses[0][1].copy())]
    for k in range(1, n_poses):
        R_prev, t_prev = init_poses[k - 1]
        e = edges[k - 1]  # odometry edge k-1 -> k
        R_rel = e['R']
        t_rel = e['t']
        R_new, t_new = se3_compose(R_rel, t_rel, R_prev, t_prev)
        # Add extra drift per step
        drift_r = np.radians(0.1) * rng.randn(3)
        drift_t = 0.005 * rng.randn(3)
        R_drift = rodrigues(drift_r)
        R_new = R_drift @ R_new
        t_new = R_drift @ t_new + drift_t
        init_poses.append((R_new, t_new))

    dataset = {
        'n_poses': n_poses,
        'fixed_poses': [0],
        'edges': [{'i': e['i'], 'j': e['j'],
                   'R': np.asarray(e['R']).tolist(),
                   't': np.asarray(e['t']).tolist(),
                   'info_weight': e['info_weight']} for e in edges],
        'init_poses': [{'R': R.tolist(), 't': t.tolist()} for R, t in init_poses],
        'true_poses': [{'R': R.tolist(), 't': t.tolist()} for R, t in true_poses],
    }

    with open(output_path, 'w') as f:
        json.dump(dataset, f)

    print(f"Generated pose graph: {n_poses} poses, {len(edges)} edges")


if __name__ == '__main__':
    generate_and_save()
