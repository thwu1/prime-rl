A 2D incompressible Navier-Stokes solver at `/app/ns2d/` has been refactored into a modular Python package but now produces incorrect results. The package spans modules for grid construction, spectral operators, time integration, and diagnostics. Reference data is at `/app/reference/`, configuration in `/app/config.toml`, and a driver at `/app/run_sim.py`.

## Objectives

1. **Diagnose and repair** all bugs in `/app/ns2d/`. The repaired solver must satisfy:

   - Poisson inversion of single Fourier modes: L-inf error < 1e-10
   - Velocity from known streamfunction: L-inf error < 1e-10
   - Taylor-Green vortex (N=64, Re=100, dt=0.01, T=5): vorticity L-inf < 1e-6; energy and enstrophy relative errors < 1e-6
   - Initial Taylor-Green energy = 0.25 (error < 1e-12), enstrophy = 0.5 (error < 1e-12)
   - Near-inviscid (Re=1e15) energy conservation: relative change < 1e-10 over T=1
   - Time integrator convergence: third-order (rate 2.7-3.5, measured with dt = 0.1, 0.05, 0.025)
   - Dissipation relation dE/dt = -2*nu*Z: max relative error < 1e-3
   - Energy spectrum: shell sum = total energy (relative error < 1e-10); Taylor-Green energy in k=1 shell only, higher shells < 1e-20

   Write `/app/results/bug_report.json` — JSON array, each entry has `"module"`, `"description"`, `"fix"`. At least 3 entries.

2. **Design and execute a convergence verification study**: After repairing the solver, evaluate whether its numerical accuracy matches its theoretical design guarantees.

   - **Temporal convergence**: Choose at least four timestep sizes in a halving sequence and run the Taylor-Green problem (N=64, Re=100, T=1.0) at each. Measure L-inf vorticity error against the exact solution and compute convergence orders between successive pairs. Judge whether the measured orders are consistent with the SSP-RK3 integrator's theoretical 3rd-order accuracy.
   - **Spatial accuracy assessment**: Evaluate the solver's spatial discretization accuracy at multiple resolutions. Determine whether the pseudo-spectral method achieves spectral accuracy and justify your conclusion — if the chosen test problem cannot demonstrate spatial convergence, explain the mathematical reason and what this implies about the solver's spatial accuracy.

   Write the complete analysis to `/app/results/convergence_eval.json` with structure:
   - `"temporal"`: object with `"timesteps"`, `"errors"`, `"convergence_orders"`, `"theoretical_order"` (integer), `"matches_theory"` (boolean), `"conclusion"` (string)
   - `"spatial"`: object with `"resolutions"`, `"errors"`, `"is_spectral"` (boolean), `"justification"` (string)

3. **Comparative parameter estimation**: `/app/reference/unknown_decay.csv` contains kinetic energy decay from a Taylor-Green simulation at an unknown Reynolds number. Implement at least two fundamentally different estimation approaches (e.g., nonlinear least-squares fitting of E(t)=0.25·exp(-4t/Re), linear regression on log-transformed energy data, finite-difference energy derivative method). For each method, compute the estimated Re and the residual norm. Evaluate which method yields the most accurate estimate and provide a justified recommendation explaining why.

   Write the comparison to `/app/results/estimation_comparison.json` with fields:
   - `"methods"`: array of `{"name", "estimated_Re", "residual_norm"}`
   - `"best_method"` (string), `"best_estimate"` (float), `"recommendation_rationale"` (string, substantive justification)

   Also write the best estimate to `/app/results/estimated_Re.txt` as a float (must be within 1% of the true value).

## Solver interface (preserve)

`from ns2d import NS2DSolver` with `(N, Re, dt, dealias=True)`. Methods: `initialize_taylor_green()`, `solve_poisson(omega)`, `compute_velocity(psi)`, `step(omega)`, `compute_energy(omega)`, `compute_enstrophy(omega)`, `compute_energy_spectrum(omega)`, `run(omega, T)`. Attributes: `solver.X`, `solver.Y` (meshgrid, `indexing='ij'`). `run` returns dict with keys `'omega'`, `'times'`, `'energies'`, `'enstrophies'`.