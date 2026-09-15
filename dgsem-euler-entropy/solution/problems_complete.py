"""

Problem definitions and simulation drivers for DGSEM benchmarks.
"""

import numpy as np
import csv
import json
import os
from .euler import (primitive_to_conserved, conserved_to_primitive,
                    lax_friedrichs_flux, chandrashekar_flux,
                    euler_flux, mathematical_entropy, GAMMA)
from .solver import DGSolver, Mesh1D, compute_rhs_flux_differencing, compute_max_dt
from .timestepping import ssp_rk3_step


def run_sod():
    """Run the Sod shock tube problem and write results to /app/results/sod.csv."""
    N = 3
    n_elements = 64
    cfl = 0.5
    t_final = 0.2

    solver = DGSolver(N)
    mesh = Mesh1D(0.0, 1.0, n_elements, periodic=False)

    # Initialize solution: element-based (all nodes in an element get the
    # same state, placing the discontinuity cleanly at the element boundary)
    U_all = np.zeros((n_elements, 3, solver.n_nodes))
    for e in range(n_elements):
        x_l, x_r = mesh.element_bounds(e)
        x_center = 0.5 * (x_l + x_r)
        if x_center < 0.5:
            W = np.array([1.0, 0.0, 1.0])
        else:
            W = np.array([0.125, 0.0, 0.1])
        for i in range(solver.n_nodes):
            U_all[e, :, i] = primitive_to_conserved(W)

    # Store boundary states for fixed BC
    U_bc_left = U_all[0, :, 0].copy()
    U_bc_right = U_all[-1, :, -1].copy()

    def rhs(U):
        U_copy = U.copy()
        U_copy[0, :, 0] = U_bc_left
        U_copy[-1, :, -1] = U_bc_right
        return compute_rhs_flux_differencing(U_copy, solver, mesh,
                                             lax_friedrichs_flux,
                                             chandrashekar_flux)

    # Time integration
    t = 0.0
    step = 0
    while t < t_final - 1e-14:
        dt = compute_max_dt(U_all, solver, mesh, cfl)
        if t + dt > t_final:
            dt = t_final - t
        U_all = ssp_rk3_step(U_all, dt, rhs)
        t += dt
        step += 1

    print(f"  Sod: completed at t={t:.6f}, steps={step}")

    # Write cell-averaged results
    os.makedirs("/app/results", exist_ok=True)
    rows = []
    for e in range(n_elements):
        x_phys = mesh.physical_nodes(e, solver.nodes)
        x_center = 0.5 * (x_phys[0] + x_phys[-1])
        # Cell average using LGL quadrature (weights sum to 2 on [-1,1])
        rho_avg = np.sum(solver.weights * U_all[e, 0, :]) / 2.0
        rho_v_avg = np.sum(solver.weights * U_all[e, 1, :]) / 2.0
        E_avg = np.sum(solver.weights * U_all[e, 2, :]) / 2.0
        U_avg = np.array([rho_avg, rho_v_avg, E_avg])
        W_avg = conserved_to_primitive(U_avg)
        rows.append({"x": x_center, "rho": W_avg[0], "v": W_avg[1], "p": W_avg[2]})

    rows.sort(key=lambda r: r["x"])
    with open("/app/results/sod.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["x", "rho", "v", "p"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: f"{v:.10e}" for k, v in row.items()})

    print("  Sod: wrote /app/results/sod.csv")


def run_entropy_conservation():
    """Run entropy conservation test and write results to /app/results/entropy.json."""
    N = 4
    n_elements = 16
    cfl = 0.3
    t_final = 2.0

    solver = DGSolver(N)
    mesh = Mesh1D(0.0, 1.0, n_elements, periodic=True)

    # Initialize with smooth density perturbation
    U_all = np.zeros((n_elements, 3, solver.n_nodes))
    for e in range(n_elements):
        x_phys = mesh.physical_nodes(e, solver.nodes)
        for i in range(solver.n_nodes):
            rho = 1.0 + 0.5 * np.sin(2.0 * np.pi * x_phys[i])
            v = 1.0
            p = 1.0
            W = np.array([rho, v, p])
            U_all[e, :, i] = primitive_to_conserved(W)

    # Compute initial total entropy using LGL quadrature
    S_initial = 0.0
    for e in range(n_elements):
        for i in range(solver.n_nodes):
            S_initial += solver.weights[i] * mathematical_entropy(U_all[e, :, i]) * (mesh.dx / 2.0)

    print(f"  Entropy: S_initial = {S_initial:.15e}")

    # Use Chandrashekar flux as both surface AND volume flux (no dissipation)
    def rhs(U):
        return compute_rhs_flux_differencing(U, solver, mesh,
                                             chandrashekar_flux,
                                             chandrashekar_flux)

    # Time integration
    t = 0.0
    step = 0
    while t < t_final - 1e-14:
        dt = compute_max_dt(U_all, solver, mesh, cfl)
        if t + dt > t_final:
            dt = t_final - t
        U_all = ssp_rk3_step(U_all, dt, rhs)
        t += dt
        step += 1

    print(f"  Entropy: completed at t={t:.6f}, steps={step}")

    # Compute final total entropy
    S_final = 0.0
    for e in range(n_elements):
        for i in range(solver.n_nodes):
            S_final += solver.weights[i] * mathematical_entropy(U_all[e, :, i]) * (mesh.dx / 2.0)

    S_change = S_final - S_initial
    print(f"  Entropy: S_final = {S_final:.15e}")
    print(f"  Entropy: S_change = {S_change:.15e}")

    os.makedirs("/app/results", exist_ok=True)
    result = {
        "S_initial": S_initial,
        "S_final": S_final,
        "S_change": S_change
    }
    with open("/app/results/entropy.json", "w") as f:
        json.dump(result, f, indent=2)

    print("  Entropy: wrote /app/results/entropy.json")
