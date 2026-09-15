The `/app/` directory contains project files for a 2D steady-state incompressible Stokes flow simulation in a lid-driven cavity on the unit square. A previous solver attempt exists in the project but was abandoned after failing internal validation. No documentation was left explaining what went wrong.

Explore the project directory to locate and understand the problem configuration, run and analyze the previous solver to determine why it produces incorrect results, and implement a correct solver that passes all validation criteria below.

Write output to `/app/output/`.

## Required output files (all in `/app/output/`)

- `velocity_u.csv`: horizontal velocity interpolated to cell centers, CSV with ny rows (row 0 = bottom of domain) by nx columns (col 0 = left of domain)
- `velocity_v.csv`: vertical velocity at cell centers, same row/column layout
- `pressure.csv`: pressure at cell centers, same layout
- `divergence.csv`: discrete divergence at each cell computed from face velocities, same layout
- `solver_info.json`: JSON object with exactly three keys: `"iterations"` (integer), `"final_residual"` (float), and `"converged"` (boolean)

## Validation criteria

All of the following must hold (grid dimensions nx and ny are specified in the project configuration):

1. All five output files must exist with array shape (ny, nx)
2. Mass conservation: maximum absolute value of divergence field < 1e-4
3. Horizontal velocity symmetric about vertical centerline: max|u(x,y) - u(1-x,y)| < 1e-5
4. Vertical velocity antisymmetric about vertical centerline: max|v(x,y) + v(1-x,y)| < 1e-5
5. Pressure antisymmetric about vertical centerline: max|p(x,y) + p(1-x,y)| < 1e-3
6. Zero-mean pressure: |mean(p)| < 1e-4
7. Flow direction: mean horizontal velocity in the topmost row > 0.3; negative horizontal velocity (return flow) must exist along the vertical centerline
8. Iterative solver convergence: `converged` is true, with 1 < iterations < 500
9. Maximum flow speed between 0.1 and 2.0