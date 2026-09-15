#!/usr/bin/env python3
"""
Topology Optimization Driver — SIMP Compliance Minimization

Runs the optimization loop using functions from framework.py and saves results.
Do NOT modify this file.  Implement the functions in framework.py.
"""

import numpy as np
import json
import os
import sys

from framework import (
    compute_element_stiffness,
    assemble_global_stiffness,
    apply_boundary_conditions_and_solve,
    compute_sensitivities,
    apply_density_filter,
    optimality_criteria_update,
    get_dof_indices,
)


def main():
    # Load configuration
    with open("/app/config.json", "r") as f:
        config = json.load(f)

    nelx = config["nelx"]
    nely = config["nely"]
    volfrac = config["volfrac"]
    penal = config["penal"]
    rmin = config["rmin"]
    E0 = config["E0"]
    Emin = config["Emin"]
    nu = config["nu"]
    max_iter = config["max_iter"]
    tol = config["convergence_tol"]

    ndof = 2 * (nelx + 1) * (nely + 1)

    # Initialize density field (uniform at target volume fraction)
    x = np.full((nely, nelx), volfrac)

    # Compute element stiffness matrix (unit Young's modulus)
    KE = compute_element_stiffness(nu)

    # Save KE matrix for verification
    os.makedirs("/app/results", exist_ok=True)
    np.savetxt("/app/results/ke_matrix.csv", KE, delimiter=",")

    # Define loads: unit downward force at bottom-right corner
    F = np.zeros(ndof)
    load_node = nelx * (nely + 1) + nely
    F[2 * load_node + 1] = -1.0

    # Fix left edge (all DOFs of nodes in column 0)
    fixed_nodes = list(range(nely + 1))
    fixed_dofs = []
    for n in fixed_nodes:
        fixed_dofs.extend([2 * n, 2 * n + 1])
    fixed_dofs = np.array(fixed_dofs)

    # Optimization loop
    compliance_history = []
    change = 1.0

    for iteration in range(max_iter):
        # Assemble global stiffness with SIMP penalization
        K = assemble_global_stiffness(nelx, nely, x, penal, KE, E0, Emin)

        # Solve equilibrium
        U = apply_boundary_conditions_and_solve(K, F, fixed_dofs, ndof)

        # Compute compliance
        compliance = float(F @ U)
        compliance_history.append(compliance)

        # Compute sensitivities
        dc, dv = compute_sensitivities(nelx, nely, x, U, KE, penal, E0, Emin)

        # Filter sensitivities
        dc = apply_density_filter(nelx, nely, rmin, x, dc)

        # Update densities (OC)
        x_old = x.copy()
        x = optimality_criteria_update(nelx, nely, x, dc, dv, volfrac)

        # Check convergence
        change = np.max(np.abs(x - x_old))
        vol = np.mean(x)

        print(
            f"Iter {iteration + 1:4d}: compliance = {compliance:.4f}, "
            f"vol = {vol:.4f}, change = {change:.6f}"
        )

        if change < tol and iteration > 10:
            print(f"Converged after {iteration + 1} iterations.")
            break

    # Save results
    np.savetxt("/app/results/compliance_history.csv", compliance_history, delimiter=",")
    np.savetxt("/app/results/density_field.csv", x, delimiter=",")

    final_stats = {
        "final_compliance": float(compliance_history[-1]),
        "final_volume_fraction": float(np.mean(x)),
        "iterations": len(compliance_history),
        "converged": bool(change < tol),
    }
    with open("/app/results/final_stats.json", "w") as f:
        json.dump(final_stats, f, indent=2)

    print(f"\nFinal compliance: {final_stats['final_compliance']:.4f}")
    print(f"Final volume fraction: {final_stats['final_volume_fraction']:.4f}")
    print(f"Iterations: {final_stats['iterations']}")
    print("Results saved to /app/results/")


if __name__ == "__main__":
    main()
