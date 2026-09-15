A numerical pipeline at `/app/` discretizes a 2D partial differential equation on a structured unit-square grid and solves the resulting sparse linear system. The pipeline is broken in two ways:

1. The matrix generator at `/app/matrix_gen/` (a CMake-based C project) has not been compiled. Build it and run the resulting executable to produce `/app/A.mtx` and `/app/b.mtx`.

2. The iterative solver at `/app/naive_solver.py` fails to converge within its iteration budget (see `/app/benchmark_log.txt` for diagnostics).

Write a replacement solver that satisfies these acceptance criteria:

- Relative residual `||r|| / ||r_0||` below `1e-10` within at most **50 iterations**
- Discretization error `||u_computed - u_exact||_∞ < 1e-2` (the PDE and its forcing function are defined in the generator source code; derive the analytical solution from them)
- Solution vector dtype: `float64`

Produce these output files:

- `/app/solution.npy` — solution vector, shape `(N*N,)`, dtype `float64`, where `N` is the interior grid size per direction
- `/app/results.json` — JSON object with fields: `grid_size` (int), `total_iterations` (int), `final_relative_residual` (float), `solution_error_linf` (float), `convergence_history` (list of per-iteration relative residuals)
- `/app/convergence.png` — plot of relative residual vs. iteration number