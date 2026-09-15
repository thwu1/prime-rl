"""
Verification script for the double pendulum simulation results.

"""

import sys
import os
import json
import numpy as np


def verify():
    results_file = '/app/results/simulation_results.json'
    traj_file = '/app/results/trajectories.npz'

    if not os.path.exists(results_file):
        print("FAIL: No simulation results found. Run the simulation first.")
        return False

    with open(results_file) as f:
        results = json.load(f)

    if not results['completed']:
        print(f"FAIL: Simulation did not complete (only {results['n_steps_completed']}/{results['n_steps_total']} steps)")
        return False

    # Check constraint violation
    if results['max_constraint_violation'] > 1e-6:
        print(f"FAIL: Max constraint violation {results['max_constraint_violation']:.2e} > 1e-6")
        return False
    print(f"PASS: Constraint violation {results['max_constraint_violation']:.2e} < 1e-6")

    # Check energy conservation (2% tolerance)
    E0 = results['initial_energy']
    Ef = results['final_energy']
    rel_err = abs(Ef - E0) / abs(E0)
    if rel_err > 0.02:
        print(f"FAIL: Energy drift {rel_err:.4f} > 0.02")
        return False
    print(f"PASS: Energy conservation relative error {rel_err:.2e} < 0.02")

    # Check Newton convergence
    if results['avg_newton_iterations'] > 10:
        print(f"FAIL: Average Newton iterations {results['avg_newton_iterations']:.1f} > 10")
        return False
    print(f"PASS: Average Newton iterations {results['avg_newton_iterations']:.1f} <= 10")

    # Check trajectory data
    if os.path.exists(traj_file):
        data = np.load(traj_file)
        qn1 = data['quat_norms_1']
        qn2 = data['quat_norms_2']
        max_qn_err = max(np.max(np.abs(qn1 - 1.0)), np.max(np.abs(qn2 - 1.0)))
        if max_qn_err > 1e-4:
            print(f"FAIL: Quaternion norm deviation {max_qn_err:.2e} > 1e-4")
            return False
        print(f"PASS: Quaternion norms within tolerance (max deviation {max_qn_err:.2e})")

        # Check energy over full trajectory
        energies = data['energies']
        max_rel_err = np.max(np.abs(energies - energies[0]) / abs(energies[0]))
        if max_rel_err > 0.02:
            print(f"FAIL: Max energy drift over trajectory {max_rel_err:.4f} > 0.02")
            return False
        print(f"PASS: Max energy drift over trajectory {max_rel_err:.2e} < 0.02")

    print("\nAll checks passed!")
    return True


if __name__ == '__main__':
    success = verify()
    sys.exit(0 if success else 1)
