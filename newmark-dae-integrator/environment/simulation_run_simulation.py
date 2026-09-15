"""
Main simulation runner for the spatial double pendulum.

"""

import sys
import os
import json
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'simulation'))

import config
from bodies import DoublePendulumSystem
from integrator import NewmarkBetaDAE
from constraints import compute_constraints


def run():
    # Create system
    system = DoublePendulumSystem(config)
    system.set_initial_conditions()

    # Create integrator
    integrator = NewmarkBetaDAE(system, config)

    # Storage for results
    n_steps = int(config.T_FINAL / config.TIMESTEP)
    times = np.zeros(n_steps + 1)
    energies = np.zeros(n_steps + 1)
    constraint_violations = np.zeros(n_steps + 1)
    positions_link1 = np.zeros((n_steps + 1, 3))
    positions_link2 = np.zeros((n_steps + 1, 3))
    quat_norms_1 = np.zeros(n_steps + 1)
    quat_norms_2 = np.zeros(n_steps + 1)

    # Initial values
    times[0] = 0.0
    energies[0] = system.compute_total_energy()
    C0 = compute_constraints(system)
    constraint_violations[0] = np.max(np.abs(C0))
    positions_link1[0] = system.link1.pos.copy()
    positions_link2[0] = system.link2.pos.copy()
    quat_norms_1[0] = np.linalg.norm(system.link1.quat)
    quat_norms_2[0] = np.linalg.norm(system.link2.quat)

    E0 = energies[0]
    print(f"Initial energy: {E0:.6f} J")
    print(f"Initial constraint violation: {constraint_violations[0]:.2e}")
    print(f"Simulating {n_steps} steps...")

    failed = False
    for i in range(1, n_steps + 1):
        converged, n_iter = integrator.step()

        times[i] = i * config.TIMESTEP
        energies[i] = system.compute_total_energy()
        C = compute_constraints(system)
        constraint_violations[i] = np.max(np.abs(C))
        positions_link1[i] = system.link1.pos.copy()
        positions_link2[i] = system.link2.pos.copy()
        quat_norms_1[i] = np.linalg.norm(system.link1.quat)
        quat_norms_2[i] = np.linalg.norm(system.link2.quat)

        if not converged:
            print(f"Step {i}: Newton solver did not converge after {n_iter} iterations")
            failed = True
            break

        if constraint_violations[i] > 1e-2:
            print(f"Step {i}: Constraint violation too large: {constraint_violations[i]:.2e}")
            failed = True
            break

        if i % 1000 == 0:
            rel_energy_err = abs(energies[i] - E0) / abs(E0)
            print(f"  t={times[i]:.1f}s: E={energies[i]:.6f} J, "
                  f"dE/E0={rel_energy_err:.2e}, "
                  f"max|C|={constraint_violations[i]:.2e}, "
                  f"iters={n_iter}")

    if failed:
        n_completed = i
    else:
        n_completed = n_steps

    avg_iters = integrator.total_iterations / max(integrator.total_steps, 1)

    # Save results
    results = {
        'completed': not failed,
        'n_steps_completed': int(n_completed),
        'n_steps_total': n_steps,
        'initial_energy': float(E0),
        'final_energy': float(energies[n_completed]),
        'max_constraint_violation': float(np.max(constraint_violations[:n_completed+1])),
        'avg_newton_iterations': float(avg_iters),
        'final_pos_link1': positions_link1[n_completed].tolist(),
        'final_pos_link2': positions_link2[n_completed].tolist(),
    }

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/simulation_results.json', 'w') as f:
        json.dump(results, f, indent=2)

    np.savez('/app/results/trajectories.npz',
             times=times[:n_completed+1],
             energies=energies[:n_completed+1],
             constraint_violations=constraint_violations[:n_completed+1],
             positions_link1=positions_link1[:n_completed+1],
             positions_link2=positions_link2[:n_completed+1],
             quat_norms_1=quat_norms_1[:n_completed+1],
             quat_norms_2=quat_norms_2[:n_completed+1])

    print(f"\nSimulation {'completed' if not failed else 'FAILED'}")
    print(f"Average Newton iterations per step: {avg_iters:.1f}")
    print(f"Results saved to /app/results/")

    return not failed


if __name__ == '__main__':
    success = run()
    sys.exit(0 if success else 1)
