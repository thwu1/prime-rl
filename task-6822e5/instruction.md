A 2D Brusselator reaction-diffusion system is defined in `/app/problem.py`. The file specifies the PDE system, parameters, grid, initial conditions, and a right-hand-side function. The system is stiff (diffusion-dominated, eigenvalues scale as O(N²)) and the provided RHS implementation has correctness and performance issues that prevent it from producing valid results within any reasonable time.

Create `/app/solver.py` exporting these four functions:

- `brusselator_rhs(t, u)` — Correct, efficient right-hand-side function for the Brusselator PDE. Must implement the boundary conditions described in the problem docstring and be fast enough for a stiff implicit solver to converge within 120 seconds.
- `build_jacobian_sparsity(N)` — Returns a `scipy.sparse` matrix representing the Jacobian sparsity pattern for an N×N grid with 2 coupled species in the state vector layout defined by `problem.py`.
- `compute_jacobian(t, u)` — Returns a `scipy.sparse` matrix containing the analytical Jacobian values at state `u` and time `t`.
- `solve_brusselator()` — Solves the full PDE system and saves output to `/app/results.npz`.

The results file `/app/results.npz` must contain:
- `times`: shape `(5,)` — output times `[0.0, 1.0, 2.0, 5.0, 11.5]`
- `U`: shape `(5, 32, 32)` — U-species concentration snapshots at each output time
- `V`: shape `(5, 32, 32)` — V-species concentration snapshots at each output time

Run your solver to produce `/app/results.npz`.