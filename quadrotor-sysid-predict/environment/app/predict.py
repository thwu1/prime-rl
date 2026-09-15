#!/usr/bin/env python3
"""Trajectory prediction pipeline.

This script:
1. Loads known parameters and training data
2. Runs system identification to estimate unknown parameters (mass, k_f, k_m)
3. Predicts trajectories for three test scenarios
4. Writes results to /app/output/
"""

import json
import os
import numpy as np

from dynamics import compute_body_wrench, quat_to_rotation_matrix, state_derivatives, quat_multiply
from integrator import rk4_step, simulate
from sysid import estimate_parameters


def main():
    # Load known parameters
    with open('/app/known_params.json') as f:
        known = json.load(f)

    known_params = {
        'arm_length': known['arm_length'],
        'J': np.array(known['J']),
        'g': known['g'],
        'drag': np.diag(known['drag_coeffs']),
        'motor_spin_dirs': known['motor_spin_dirs'],
    }
    known_params['J_inv'] = np.linalg.inv(known_params['J'])

    # Step 1: System identification
    training_files = [
        '/app/data/training_hover.npz',
        '/app/data/training_vstep.npz',
        '/app/data/training_roll.npz',
        '/app/data/training_yaw.npz',
    ]
    estimated = estimate_parameters(training_files, known_params)
    print(f"Estimated parameters: {estimated}")

    # Combine all parameters
    params = {**known_params, **estimated}

    # Step 2: Predict test trajectories
    test_data = np.load('/app/data/test_inputs.npz')
    dt = known['dt']

    os.makedirs('/app/output', exist_ok=True)

    for i in range(1, 4):
        scenario = f'scenario_{i}'
        initial_state = {
            'pos': test_data[f'{scenario}_pos0'].copy(),
            'quat': test_data[f'{scenario}_quat0'].copy(),
            'vel': test_data[f'{scenario}_vel0'].copy(),
            'ang_vel': test_data[f'{scenario}_angvel0'].copy(),
        }
        rpm_sequence = test_data[f'{scenario}_rpms']

        result = simulate(initial_state, rpm_sequence, params, dt)

        np.savez(f'/app/output/{scenario}.npz',
                 positions=result['positions'],
                 quaternions=result['quaternions'],
                 velocities=result['velocities'],
                 angular_velocities=result['angular_velocities'])
        print(f"  {scenario}: {len(rpm_sequence)} steps, "
              f"final pos = {result['positions'][-1]}")

    # Save estimated parameters
    est_out = {}
    for k, v in estimated.items():
        if isinstance(v, np.ndarray):
            est_out[k] = v.tolist()
        elif isinstance(v, (np.floating, np.integer)):
            est_out[k] = float(v)
        else:
            est_out[k] = v

    with open('/app/output/estimated_params.json', 'w') as f:
        json.dump(est_out, f, indent=2)

    print("Prediction complete. Results written to /app/output/")


if __name__ == '__main__':
    main()
