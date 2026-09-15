#!/usr/bin/env python3
"""Evaluate EKF-SLAM filter consistency using Normalized Innovation Squared (NIS).

Runs the corrected filter on the scenario data, computes per-observation NIS
statistics, and writes a consistency report to /app/consistency_report.json.

"""

import json
import pickle
import sys

import numpy as np

sys.path.insert(0, '/app')
from ekf_slam import EKFSLAM, normalize_angle


def compute_nis(slam, landmark_id, z_range, z_bearing):
    """Compute NIS for a single observation at the current filter state.

    NIS = innovation^T S^{-1} innovation
    where innovation = z - z_hat and S = H P H^T + Q.
    """
    j = landmark_id
    lx = slam.mu[3 + 2 * j]
    ly = slam.mu[3 + 2 * j + 1]
    rx, ry, rtheta = slam.mu[0], slam.mu[1], slam.mu[2]

    dx = lx - rx
    dy = ly - ry
    q = dx**2 + dy**2
    sqrt_q = np.sqrt(q)

    z_hat = np.array([
        sqrt_q,
        normalize_angle(np.arctan2(dy, dx) - rtheta),
    ])

    H = np.zeros((2, slam.state_dim))
    H[0, 0] = -dx / sqrt_q
    H[0, 1] = -dy / sqrt_q
    H[0, 2] = 0
    H[1, 0] = dy / q
    H[1, 1] = -dx / q
    H[1, 2] = -1

    lidx = 3 + 2 * j
    H[0, lidx] = dx / sqrt_q
    H[0, lidx + 1] = dy / sqrt_q
    H[1, lidx] = -dy / q
    H[1, lidx + 1] = dx / q

    innovation = np.array([
        z_range - z_hat[0],
        normalize_angle(z_bearing - z_hat[1]),
    ])

    S = H @ slam.Sigma @ H.T + slam.Qt
    nis = float(innovation @ np.linalg.solve(S, innovation))
    return nis


def main():
    with open('/app/scenario.pkl', 'rb') as f:
        scenario = pickle.load(f)

    slam = EKFSLAM(
        sigma_v=scenario['sigma_v'],
        sigma_omega=scenario['sigma_omega'],
        sigma_range=scenario['sigma_range'],
        sigma_bearing=scenario['sigma_bearing'],
        n_landmarks=scenario['n_landmarks'],
    )

    controls = scenario['controls']
    observations = scenario['observations']
    dt = scenario['dt']
    n_steps = len(controls)

    nis_values = []

    # Process each timestep, each observation individually
    for t in range(n_steps + 1):
        if t > 0:
            slam.predict(controls[t - 1], dt)

        for landmark_id, z_range, z_bearing in observations[t]:
            if slam.landmark_observed[landmark_id]:
                nis = compute_nis(slam, landmark_id, z_range, z_bearing)
                nis_values.append(nis)
            # Process this single observation (initialize or Kalman update)
            slam.update([(landmark_id, z_range, z_bearing)])

    # Compute statistics
    nis_arr = np.array(nis_values)
    obs_dim = 2  # range-bearing observations

    # Chi-squared 95% critical value for df=2: -2*ln(0.05) = 5.991
    chi2_95 = 5.991

    mean_nis = float(np.mean(nis_arr))
    below_pct = float(np.sum(nis_arr < chi2_95) / len(nis_arr) * 100.0)
    total_obs = len(nis_values)
    is_consistent = (0.5 < mean_nis < 4.0) and (below_pct > 85.0)

    report = {
        'mean_nis': round(mean_nis, 4),
        'nis_below_threshold_pct': round(below_pct, 2),
        'total_observations': total_obs,
        'is_consistent': is_consistent,
    }

    with open('/app/consistency_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"NIS Statistics:")
    print(f"  Mean NIS:            {mean_nis:.4f}  (expected ~{obs_dim:.1f})")
    print(f"  Below 95% threshold: {below_pct:.1f}%")
    print(f"  Total observations:  {total_obs}")
    print(f"  Consistent:          {is_consistent}")
    print(f"\nReport written to /app/consistency_report.json")


if __name__ == '__main__':
    main()
