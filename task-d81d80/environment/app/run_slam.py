#!/usr/bin/env python3
"""Run EKF-SLAM on pre-generated scenario data and print diagnostics.

"""

import pickle
import sys
import numpy as np

sys.path.insert(0, '/app')
from ekf_slam import EKFSLAM, normalize_angle


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
    true_poses = scenario['true_poses']
    true_landmarks = scenario['landmarks']
    dt = scenario['dt']
    n_steps = len(controls)

    print(f"EKF-SLAM: {n_steps} steps, {scenario['n_landmarks']} landmarks")
    print(f"Sensor range: {scenario['max_range']:.1f} m")
    print(f"Initial pose: ({true_poses[0, 0]:.2f}, {true_poses[0, 1]:.2f}, "
          f"{true_poses[0, 2]:.2f})")
    print()

    # Process initial observations (at t=0, before any motion)
    slam.update(observations[0])

    for t in range(n_steps):
        slam.predict(controls[t], dt)
        slam.update(observations[t + 1])

        # Periodic diagnostics
        if (t + 1) % 100 == 0 or t == n_steps - 1:
            pos_err = np.linalg.norm(slam.mu[:2] - true_poses[t + 1, :2])
            hdg_err = abs(normalize_angle(slam.mu[2] - true_poses[t + 1, 2]))
            eigs = np.linalg.eigvalsh(slam.Sigma)

            print(f"Step {t + 1}/{n_steps}:")
            print(f"  True:  ({true_poses[t+1, 0]:.2f}, "
                  f"{true_poses[t+1, 1]:.2f}, {true_poses[t+1, 2]:.2f})")
            print(f"  Est:   ({slam.mu[0]:.2f}, {slam.mu[1]:.2f}, "
                  f"{slam.mu[2]:.2f})")
            print(f"  Pos error: {pos_err:.3f} m | "
                  f"Hdg error: {hdg_err:.3f} rad")
            print(f"  Min eigenvalue: {np.min(eigs):.6f}")

            n_obs = int(np.sum(slam.landmark_observed))
            lm_errors = []
            for j in range(scenario['n_landmarks']):
                if slam.landmark_observed[j]:
                    err = np.linalg.norm(
                        slam.mu[3 + 2*j:3 + 2*j + 2] - true_landmarks[j]
                    )
                    lm_errors.append(err)
            if lm_errors:
                print(f"  Landmarks: {n_obs}/{scenario['n_landmarks']} | "
                      f"Avg err: {np.mean(lm_errors):.3f} m | "
                      f"Max err: {np.max(lm_errors):.3f} m")
            print()

    # Final summary
    print("=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)

    final_pos_err = np.linalg.norm(slam.mu[:2] - true_poses[-1, :2])
    final_hdg_err = abs(normalize_angle(slam.mu[2] - true_poses[-1, 2]))
    eigs = np.linalg.eigvalsh(slam.Sigma)
    min_eig = np.min(eigs)

    print(f"Robot position error:  {final_pos_err:.3f} m  (threshold: 2.0 m)")
    print(f"Robot heading error:   {final_hdg_err:.3f} rad (threshold: 0.3 rad)")
    print(f"Min eigenvalue:        {min_eig:.6f}  (must be > -1e-6)")

    n_obs = int(np.sum(slam.landmark_observed))
    print(f"Landmarks observed:    {n_obs}/{scenario['n_landmarks']}")

    lm_errors = []
    for j in range(scenario['n_landmarks']):
        if slam.landmark_observed[j]:
            est = slam.mu[3 + 2*j:3 + 2*j + 2]
            err = np.linalg.norm(est - true_landmarks[j])
            lm_errors.append(err)
            print(f"  Landmark {j}: true={true_landmarks[j]}, "
                  f"est=[{est[0]:.2f}, {est[1]:.2f}], err={err:.3f} m")

    if lm_errors:
        avg_lm = np.mean(lm_errors)
        max_lm = np.max(lm_errors)
        print(f"Avg landmark error:    {avg_lm:.3f} m  (threshold: 1.5 m)")
        print(f"Max landmark error:    {max_lm:.3f} m  (threshold: 3.0 m)")

    # Pass/fail checks
    ok = True
    if final_pos_err >= 2.0:
        print("\nFAIL: Robot position error too large")
        ok = False
    if final_hdg_err >= 0.3:
        print("\nFAIL: Robot heading error too large")
        ok = False
    if min_eig < -1e-6:
        print("\nFAIL: Covariance not positive semi-definite")
        ok = False
    if n_obs < scenario['n_landmarks']:
        print("\nFAIL: Not all landmarks observed")
        ok = False
    if lm_errors and np.mean(lm_errors) >= 1.5:
        print("\nFAIL: Landmark position error too large")
        ok = False

    print(f"\n{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
