Implement a finite element solver for the incompressible Navier-Stokes equations on the Kovasznay flow benchmark problem. Create your solver at `/app/solver.py`.

The file `/app/problem_spec.py` defines the problem on a unit square domain [0,1]^2 at Reynolds number 25, including exact velocity and pressure solution functions, discretization parameters (mesh resolution, polynomial degree), and time-stepping configuration. DOLFINx with PETSc and MUMPS is installed under `/opt/conda` and available on `PATH`.

Your solver must read the parameters from `/app/problem_spec.py` and compute a numerical solution to the Navier-Stokes equations that converges to steady state. After convergence, compute L2 error norms of the velocity, pressure, and velocity divergence against the exact Kovasznay solution and write results to `/app/results.json`:

```json
{
  "velocity_l2_error": <float>,
  "pressure_l2_error": <float>,
  "divergence_l2_error": <float>
}
```

**Verification requirements:**

- All three error values must be finite, non-negative numbers.
- Velocity L2 error < 5e-2.
- Pressure L2 error < 5e-1.
- Divergence L2 error < 1e-8 (the discretization must conserve mass to near machine precision).
- Velocity and pressure L2 errors must each exceed 1e-5 (to confirm errors arise from a genuine finite element computation, not fabricated values).
- `/app/solver.py` must be a substantive DOLFINx/UFL-based finite element implementation containing at least 50 non-empty, non-comment lines of code (i.e., it must import and use `dolfinx` or `ufl`).