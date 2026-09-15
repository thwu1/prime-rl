The directory `/app/` contains two Python modules:

- `fem_framework.py` — utilities for structured triangular mesh generation on [0,1]², quadrature rules, and basis function evaluation for mixed finite elements.
- `problem_spec.py` — exact velocity and pressure fields for a manufactured solution to the 2D steady Stokes equations (−Δu + ∇p = f, ∇·u = 0) on [0,1]². The body force f that makes these fields satisfy the governing equations is **not** provided and must be determined.

Create `/app/stokes_solver.py` that uses the provided framework to numerically solve the Stokes problem, compare the numerical solution against the manufactured exact solution, and produce a mesh convergence study for mesh sizes n ∈ {4, 8, 16, 32}. The solver must import and use utilities from the provided framework modules.

Write results to `/app/results.json` in this format:

```json
{
  "mesh_sizes": [4, 8, 16, 32],
  "velocity_l2_errors": [e1, e2, e3, e4],
  "pressure_l2_errors": [e1, e2, e3, e4],
  "velocity_convergence_rates": [r1, r2, r3],
  "pressure_convergence_rates": [r1, r2, r3],
  "velocity_avg_convergence_rate": float,
  "pressure_avg_convergence_rate": float
}
```

Each convergence rate: r_i = log(e_i / e_{i+1}) / log(2).

Acceptance criteria:

- All L2 errors positive and strictly decreasing with refinement
- Rates consistent with errors (recomputed rates match within 0.01)
- Average velocity convergence rate ∈ [2.5, 3.5]
- Average pressure convergence rate ∈ [1.5, 2.5]
- Individual velocity rates ∈ [2.0, 4.0]; individual pressure rates ∈ [1.0, 3.0]
- At n=32: velocity L2 error < 0.005, pressure L2 error < 0.05