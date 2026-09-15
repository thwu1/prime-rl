`/app/poisson.py` provides a finite-difference framework for -Δu = f on [0,1]² (5-point stencil, homogeneous Dirichlet BCs). `/app/run_solver.py` is the test harness.

Create `/app/multigrid.py` implementing a geometric multigrid V-cycle solver. The module must export these functions:

- `build_prolongation(nc, nf)` — 2D bilinear interpolation operator from nc×nc to nf×nf interior grid (returns scipy sparse matrix)
- `build_restriction(nc, nf)` — 2D full-weighting restriction operator from nf×nf to nc×nc interior grid (returns scipy sparse matrix)
- `smooth(A, b, x, nu, omega)` — weighted Jacobi smoother: nu iterations with relaxation parameter omega, returns updated x
- `mg_solve(n, b, num_levels=None, nu1=2, nu2=2, omega=2.0/3.0, tol=1e-10, max_iter=100)` — V-cycle solver, returns `(solution_vector, residual_norms_list)`

Grid sizes follow 2^k − 1 for clean geometric coarsening (tested: n = 15, 31, 63, 127, 255 interior points per dimension). Coarsest level uses a direct solve. The finest-level discretization uses the standard 5-point stencil with h = 1/(n+1) as provided by `/app/poisson.py`.

The solver must achieve:
- Convergence factor < 0.2 per V-cycle iteration
- Mesh-independent convergence factor (variation < 0.07 across grid sizes 31 through 255)
- O(h²) discretization error against u(x,y) = sin(πx)sin(πy)

After implementing, run `python3 /app/run_solver.py` to produce `/app/results.json`.