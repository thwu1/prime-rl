#!/usr/bin/env python3
"""Comparative evaluation of EKF covariance update formulations.

Implements two mathematically distinct covariance update strategies,
runs each under clean and corrupted conditions, and evaluates which
is most robust based on quantitative metrics.

"""

import copy
import json
import pickle
import sys

import numpy as np

sys.path.insert(0, '/app')
from ekf_slam import EKFSLAM, normalize_angle


class JosephFormEKFSLAM(EKFSLAM):
    """EKF-SLAM using the Joseph-form covariance update for numerical stability.

    Standard update:  P = (I - KH) P
    Joseph form:      P = (I - KH) P (I - KH)^T + K Q K^T

    The Joseph form is guaranteed to produce a symmetric positive semi-definite
    covariance matrix even under numerical perturbation, because it is a sum
    of two PSD quadratic forms.
    """

    def update(self, observations):
        """Correction step using Joseph-form covariance update."""
        for landmark_id, z_range, z_bearing in observations:
            if not self.landmark_observed[landmark_id]:
                self._initialize_landmark(landmark_id, z_range, z_bearing)
                continue

            j = landmark_id
            lx = self.mu[3 + 2 * j]
            ly = self.mu[3 + 2 * j + 1]
            rx, ry, rtheta = self.mu[0], self.mu[1], self.mu[2]

            dx = lx - rx
            dy = ly - ry
            q = dx**2 + dy**2
            sqrt_q = np.sqrt(q)

            z_hat = np.array([
                sqrt_q,
                normalize_angle(np.arctan2(dy, dx) - rtheta)
            ])

            H = np.zeros((2, self.state_dim))
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
                normalize_angle(z_bearing - z_hat[1])
            ])

            S = H @ self.Sigma @ H.T + self.Qt
            K = self.Sigma @ H.T @ np.linalg.inv(S)

            self.mu += K @ innovation
            self.mu[2] = normalize_angle(self.mu[2])

            # Joseph-form covariance update
            I_KH = np.eye(self.state_dim) - K @ H
            self.Sigma = I_KH @ self.Sigma @ I_KH.T + K @ self.Qt @ K.T


def corrupt_observations(observations, seed=99, outlier_fraction=0.15,
                         outlier_range_max=50.0):
    """Create a corrupted copy of observations with outlier range measurements.

    Uses a fixed RandomState seed for reproducibility. Replaces a fraction of
    range observations with values drawn from U[0, outlier_range_max].
    """
    rng = np.random.RandomState(seed)
    corrupted = []
    for obs_t in observations:
        new_obs = []
        for landmark_id, z_range, z_bearing in obs_t:
            if rng.random() < outlier_fraction:
                z_range = float(rng.uniform(0, outlier_range_max))
            new_obs.append((landmark_id, z_range, z_bearing))
        corrupted.append(new_obs)
    return corrupted


def compute_nis(slam, landmark_id, z_range, z_bearing):
    """Compute Normalized Innovation Squared for a single observation."""
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
    try:
        nis = float(innovation @ np.linalg.solve(S, innovation))
    except np.linalg.LinAlgError:
        nis = float('inf')
    return nis


def run_experiment(slam_class, scenario, observations):
    """Run a filter experiment and collect robustness metrics."""
    slam = slam_class(
        sigma_v=scenario['sigma_v'],
        sigma_omega=scenario['sigma_omega'],
        sigma_range=scenario['sigma_range'],
        sigma_bearing=scenario['sigma_bearing'],
        n_landmarks=scenario['n_landmarks'],
    )

    controls = scenario['controls']
    true_poses = scenario['true_poses']
    dt = scenario['dt']
    n_steps = len(controls)

    nis_values = []
    psd_maintained = True

    # Process initial observations
    slam.update(observations[0])
    estimated_poses = [slam.mu[:3].copy()]

    for t in range(n_steps):
        slam.predict(controls[t], dt)

        # Collect NIS before update (only for already-observed landmarks)
        for lid, zr, zb in observations[t + 1]:
            if slam.landmark_observed[lid]:
                nis = compute_nis(slam, lid, zr, zb)
                if np.isfinite(nis):
                    nis_values.append(nis)

        slam.update(observations[t + 1])
        estimated_poses.append(slam.mu[:3].copy())

        # Check PSD
        min_eig = np.min(np.linalg.eigvalsh(slam.Sigma))
        if min_eig < -1e-6:
            psd_maintained = False

    estimated_poses = np.array(estimated_poses)

    # Position RMSE
    pos_errors = np.linalg.norm(
        estimated_poses[:, :2] - true_poses[:, :2], axis=1
    )
    rmse = float(np.sqrt(np.mean(pos_errors**2)))

    # NIS statistics
    chi2_95 = 5.991
    if len(nis_values) > 0:
        nis_arr = np.array(nis_values)
        mean_nis = float(np.mean(nis_arr))
        nis_below_pct = float(
            np.sum(nis_arr < chi2_95) / len(nis_arr) * 100.0
        )
    else:
        mean_nis = 0.0
        nis_below_pct = 0.0

    # Condition number of final covariance
    try:
        cond = np.linalg.cond(slam.Sigma)
        log10_cond = float(np.log10(cond)) if np.isfinite(cond) else None
    except np.linalg.LinAlgError:
        log10_cond = None

    return {
        'position_rmse': round(rmse, 4),
        'mean_nis': round(mean_nis, 4),
        'nis_below_95pct': round(nis_below_pct, 2),
        'log10_condition_number': round(log10_cond, 4) if log10_cond is not None else None,
        'psd_maintained': psd_maintained,
    }


def main():
    with open('/app/scenario.pkl', 'rb') as f:
        scenario = pickle.load(f)

    clean_obs = scenario['observations']
    corrupted_obs = corrupt_observations(clean_obs)

    formulations = [
        ('standard', EKFSLAM),
        ('joseph', JosephFormEKFSLAM),
    ]

    results = []
    for name, cls in formulations:
        clean_metrics = run_experiment(cls, scenario, clean_obs)
        corrupted_metrics = run_experiment(cls, scenario, corrupted_obs)
        results.append({
            'name': name,
            'clean': clean_metrics,
            'corrupted': corrupted_metrics,
        })
        print(f"\n--- {name} ---")
        print(f"  Clean:     RMSE={clean_metrics['position_rmse']:.3f}m  "
              f"NIS={clean_metrics['mean_nis']:.3f}  "
              f"NIS<95%={clean_metrics['nis_below_95pct']:.1f}%  "
              f"PSD={clean_metrics['psd_maintained']}  "
              f"log10(cond)={clean_metrics['log10_condition_number']}")
        print(f"  Corrupted: RMSE={corrupted_metrics['position_rmse']:.3f}m  "
              f"NIS={corrupted_metrics['mean_nis']:.3f}  "
              f"NIS<95%={corrupted_metrics['nis_below_95pct']:.1f}%  "
              f"PSD={corrupted_metrics['psd_maintained']}  "
              f"log10(cond)={corrupted_metrics['log10_condition_number']}")

    # Evaluate: score each formulation on robustness criteria
    # Weight: clean performance (must be good) + corrupted stability (differentiator)
    best_name = None
    best_score = -float('inf')

    for r in results:
        score = 0.0
        # Clean scenario: both should be good, reward low RMSE and high NIS consistency
        if r['clean']['position_rmse'] < 2.0:
            score += 2.0
        score += r['clean']['nis_below_95pct'] / 100.0

        # Corrupted scenario: reward PSD maintenance and lower RMSE
        if r['corrupted']['psd_maintained']:
            score += 3.0
        # Lower corrupted RMSE is better (invert, cap contribution)
        score += max(0, 10.0 - r['corrupted']['position_rmse']) / 10.0
        # Higher NIS consistency under corruption is better
        score += r['corrupted']['nis_below_95pct'] / 100.0

        if score > best_score:
            best_score = score
            best_name = r['name']

    # Build rationale from quantitative evidence
    best_data = next(r for r in results if r['name'] == best_name)
    other_data = [r for r in results if r['name'] != best_name]

    rationale_parts = []
    rationale_parts.append(
        f"The {best_name} formulation achieves "
        f"clean RMSE={best_data['clean']['position_rmse']:.3f}m "
        f"and corrupted RMSE={best_data['corrupted']['position_rmse']:.3f}m"
    )
    if best_data['corrupted']['psd_maintained']:
        rationale_parts.append(
            "maintains positive semi-definite covariance under outlier corruption"
        )
    if other_data:
        o = other_data[0]
        if not o['corrupted']['psd_maintained'] and best_data['corrupted']['psd_maintained']:
            rationale_parts.append(
                f"while the {o['name']} formulation loses PSD under corruption"
            )
        elif o['corrupted']['position_rmse'] > best_data['corrupted']['position_rmse']:
            rationale_parts.append(
                f"outperforming the {o['name']} formulation "
                f"(corrupted RMSE={o['corrupted']['position_rmse']:.3f}m) under adversarial conditions"
            )

    rationale = "; ".join(rationale_parts) + "."

    report = {
        'formulations': results,
        'recommended_formulation': best_name,
        'rationale': rationale,
    }

    with open('/app/filter_evaluation.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\nRecommended: {best_name}")
    print(f"Rationale: {rationale}")
    print(f"\nReport written to /app/filter_evaluation.json")


if __name__ == '__main__':
    main()
