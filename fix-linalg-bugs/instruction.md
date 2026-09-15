The file `/app/naive_impl.py` contains naive implementations of three matrix functions using mpmath arbitrary-precision arithmetic:

- `matrix_exp(A, dps)` — matrix exponential
- `matrix_sqrt(A, dps)` — principal matrix square root
- `matrix_log(A, dps)` — principal matrix logarithm

Each takes an mpmath matrix `A` and a precision target `dps` (decimal digits), returning an mpmath matrix. These naive Taylor series implementations work for trivial inputs (small norm, close to identity) but fail on challenging matrices: they diverge, suffer catastrophic cancellation, or require impractical computation time for matrices with large norms, repeated eigenvalues, or eigenvalues outside the series' convergence radius.

Create `/app/matrix_functions.py` exporting `matrix_exp(A, dps)`, `matrix_log(A, dps)`, and `matrix_sqrt(A, dps)` that compute correct results to `dps` decimal digits of precision for all test matrices, including matrices with 1-norm exceeding 100, non-symmetric matrices with repeated eigenvalues, and 4x4 symmetric positive-definite systems. The three functions must be mutually consistent: `exp(log(A)) = A` for positive-definite A, `sqrt(A)^2 = A`, and `sqrt(A) = exp(log(A)/2)`.