A 2D computational fluid dynamics framework at `/app/` requires implementation of core numerical algorithms. Four modules contain stub functions that raise `NotImplementedError`:

- `/app/cg_solver.py` — Conjugate Gradient (CG) and Preconditioned CG (PCG) iterative solvers for symmetric positive definite linear systems
- `/app/preconditioner.py` — Diagonal (Jacobi) and Incomplete Cholesky IC(0) preconditioners
- `/app/fmm_solver.py` — Fast Marching Method for 2D signed distance field reinitialization (Eikonal equation solver)
- `/app/poisson.py` — 2D negative-Laplacian operator assembly using the 5-point finite difference stencil in CSR format

The CSR sparse matrix implementation (`/app/sparse_matrix.py`) is complete and provides `matvec`, `diagonal`, `get`, `lower_triangle_entries`, and `from_entries` methods. Do not modify it.

All implementations must satisfy the numerical contracts in the function docstrings. The CG solver must handle zero-iteration edge cases and return the correct initial residual norm. The IC(0) preconditioner must compute L with the same sparsity pattern as the lower triangle of A and implement forward/backward triangular substitution. The FMM must handle both exact and distorted input fields while preserving sign information.