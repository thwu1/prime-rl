#!/usr/bin/env python3
"""Run convergence study and Sod shock tube simulation.

Convergence study: smooth density wave, polynomial degree N=3,
    volume flux = entropy-conservative,
    surface flux = Riemann solver.

Sod shock tube: N=0 (finite volume), surface flux = Riemann solver.
"""
import os
import json
import csv
import numpy as np
from core import (Mesh1D, DGSolver, ic_smooth_wave, ic_sod,
                  exact_smooth_wave, cons2prim, GAMMA)
from fluxes import ec_flux, rs_flux, central_flux


def convergence_study():
    """Measure L2 errors and empirical convergence orders."""
    N = 3
    t_final = 0.5
    elements_list = [4, 8, 16, 32]
    errors = []

    for K in elements_list:
        mesh = Mesh1D(0.0, 1.0, K)
        solver = DGSolver(mesh, N, ec_flux, rs_flux, bc='periodic')
        solver.initialize(ic_smooth_wave)
        solver.run(t_final, cfl=0.1)

        err_sq = 0.0
        J = mesh.jacobian()
        for k in range(solver.K):
            for i in range(solver.Np):
                exact = exact_smooth_wave(solver.x[k, i], t_final)
                diff = solver.u[k, i] - exact
                err_sq += J * solver.weights[i] * np.dot(diff, diff)
        err = np.sqrt(err_sq)
        errors.append(err)
        print(f"  K={K:4d}  L2_err={err:.6e}")

    orders = []
    for i in range(1, len(errors)):
        if errors[i] > 0 and errors[i - 1] > 0:
            ratio = elements_list[i] / elements_list[i - 1]
            r = np.log(errors[i - 1] / errors[i]) / np.log(ratio)
            orders.append(round(float(r), 4))
        else:
            orders.append(0.0)

    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/convergence.json', 'w') as f:
        json.dump({
            'polynomial_degree': N,
            'elements': elements_list,
            'errors': [float(e) for e in errors],
            'orders': orders
        }, f, indent=2)
    print(f"  Orders: {orders}")


def sod_simulation():
    """Run Sod shock tube with first-order FV + Riemann solver."""
    N = 0
    K = 200
    t_final = 0.2
    mesh = Mesh1D(0.0, 1.0, K)
    solver = DGSolver(mesh, N, central_flux, rs_flux, bc='transmissive')
    solver.initialize(ic_sod)
    solver.run(t_final, cfl=0.5)

    x, u = solver.get_solution_arrays()
    os.makedirs('/app/results', exist_ok=True)
    with open('/app/results/sod_solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['x', 'rho', 'v', 'p'])
        for i in range(len(x)):
            rho, v, p = cons2prim(u[i])
            writer.writerow([f'{x[i]:.10f}', f'{rho:.10f}',
                             f'{v:.10f}', f'{p:.10f}'])
    print(f"  Written {len(x)} points to sod_solution.csv")


if __name__ == '__main__':
    print("=== Convergence Study (N=3) ===")
    convergence_study()
    print("\n=== Sod Shock Tube (N=0 FV) ===")
    sod_simulation()
    print("\nDone. Results in /app/results/")
