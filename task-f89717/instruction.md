A numerical integration library at `/app/quadrature.py` implements the G7-K15 adaptive Gauss-Kronrod quadrature algorithm with Wynn epsilon convergence acceleration and semi-infinite interval support via variable transformation. The implementation contains multiple bugs across different algorithmic components that cause incorrect results for various classes of integrals.

The benchmark script `/app/compute.py` evaluates six definite integrals covering smooth, oscillatory, singular, and semi-infinite domains against known analytical values. Currently several of these fail to converge within the required tolerance of 1e-8.

A backup copy of the original source files is at `/opt/task/` if needed.

Identify and fix all bugs in `/app/quadrature.py` so that running `python3 /app/compute.py` produces correct results for all six benchmark integrals. The computed values are written to `/app/results.json`.