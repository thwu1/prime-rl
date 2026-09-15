A molecular dynamics benchmarking framework at `/app/benchmark.py` simulates a 1D harmonic oscillator chain and measures energy conservation properties of symplectic integrators. The framework includes the system setup, energy/force computation, a working Velocity Verlet (2nd-order) integrator, a convergence analysis harness, and stubs for two 4th-order integrators.

Your task: implement the **Forest-Ruth** and **PEFRL** (Position-Extended Forest-Ruth-Like) symplectic integrators using the existing function signatures, then run the convergence analysis and write results.

The Forest-Ruth integrator uses the symmetric triple-jump composition of the leapfrog with parameter `theta = 1/(2 - 2^(1/3))`. After merging adjacent drift stages, it has 7 stages (4 position drifts, 3 force evaluations). See Forest & Ruth, *Physica D* 43 (1990) 105–117.

The PEFRL integrator is a 9-stage optimized scheme from Omelyan, Mryglod & Folk, *Comp. Phys. Comm.* 146 (2002) 188–199. It achieves significantly lower error constants than Forest-Ruth despite requiring only one additional force evaluation per step.

Each integrator function takes `(q, p, dt)` — positions, momenta, and timestep — and returns updated `(q, p)`. Forces must be recomputed after each position update within a single step.

Write results to `/app/results.json` containing at minimum:
- `velocity_verlet_order`, `forest_ruth_order`, `pefrl_order` — measured convergence orders from log-log regression of max relative energy error vs timestep
- `pefrl_to_fr_error_ratio` — ratio of PEFRL to Forest-Ruth max energy error at a common timestep
- `fr_force_evals` and `pefrl_force_evals` — number of force evaluations per integration step
- `{name}_errors` — dict mapping timestep strings to measured max relative energy errors for each integrator