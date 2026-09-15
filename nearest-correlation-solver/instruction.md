Build a solver that processes problem files at `/app/problems/problem_N.json` (N=1..5) and writes solutions to `/app/solutions/solution_N.json`.

Each problem provides a symmetric matrix with unit diagonal that may have negative eigenvalues (i.e., not a valid correlation matrix). Compute the nearest valid correlation matrix — symmetric, positive semidefinite, unit diagonal — minimizing the Frobenius norm of the difference, along with any requested numerical analyses.

## Input Format

Each problem JSON contains:

- `matrix`: symmetric matrix with unit diagonal (may be indefinite)
- `weights`: optional weight vector `w`. When present, minimize `||diag(w)^{1/2} (X-A) diag(w)^{1/2}||_F` instead of `||X-A||_F`
- `fixed_entries`: optional list of `[i,j]` index pairs whose values must be preserved exactly from the input matrix in the result
- `tol`: convergence tolerance
- `compute_modified_cholesky`: when true, analyze the original matrix to determine the minimum-norm perturbation making it positive semidefinite via factorization-based methods
- `solve_system_rhs`: optional right-hand side vector `b`. When present, solve `Cx = b` where `C` is the computed nearest correlation matrix and report backward errors

## Required Output

Each `/app/solutions/solution_N.json` must contain:

```json
{
  "nearest_correlation_matrix": [[...], ...],
  "frobenius_distance": <float>,
  "min_eigenvalue": <float>,
  "iterations": <int>,
  "modified_cholesky": {
    "perturbation_frobenius_norm": <float>,
    "perturbed_min_eigenvalue": <float>,
    "condition_number": <float>
  },
  "linear_system": {
    "solution": [<float>, ...],
    "normwise_backward_error": <float>,
    "componentwise_backward_error": <float>
  }
}
```

- `frobenius_distance`: unweighted `||X-A||_F` or weighted `||W^{1/2}(X-A)W^{1/2}||_F` as appropriate
- `min_eigenvalue`: smallest eigenvalue of the computed nearest correlation matrix
- `modified_cholesky` / `linear_system`: `null` when not requested
- Normwise backward error: `eta = ||r||_inf / (||C||_inf * ||x||_inf + ||b||_inf)` where `r = b - Cx`
- Componentwise backward error: `omega = max_i |r_i| / (|C| |x| + |b|)_i`

All computed nearest correlation matrices must be symmetric, have unit diagonal, and have minimum eigenvalue >= -1e-8. Frobenius distances must be within 0.1% of optimal.