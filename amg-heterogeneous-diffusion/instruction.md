Solve the sparse linear system arising from the 2D heterogeneous diffusion problem fully specified in `/app/problem.json`. The configuration file defines the PDE, domain, boundary conditions, coefficient field (with high-contrast inclusions), grid discretization parameters, preconditioner settings, and iterative solver parameters. Your implementation must honor all parameters in the configuration. You may use standard linear algebra libraries (e.g., for sparse matrix operations and direct solves on small systems), but all solver and preconditioner components described in the configuration must be implemented from scratch.

Write results to `/app/results.json` with the following fields and acceptance criteria:

- `n_unknowns` (int): total number of interior grid unknowns; must equal `grid_size²` from the config
- `n_levels` (int): number of levels in the preconditioner hierarchy; must be >= 3
- `grid_complexity` (float): sum of grid sizes across all levels divided by finest-level grid size; must be in (1.0, 3.0)
- `operator_complexity` (float): sum of matrix nonzeros across all levels divided by finest-level nonzeros; must be in (1.0, 6.0)
- `pcg_iterations` (int): number of outer solver iterations to convergence; must be < 100
- `convergence_factor` (float): asymptotic convergence factor computed as (final_residual / initial_residual)^(1/iterations); must be in (0.0, 0.7)
- `solution_norm` (float): L2 norm of the computed solution vector; verified against an independent direct-solve reference within 1e-3 relative error
- `probe_values` (object): keys are `"i_j"` strings for each `[i, j]` in the config's `output.probe_points_ij` array; values are the computed solution at those grid indices; each verified against a direct-solve reference within max(1e-8, 1e-4 * |reference_value|) absolute error