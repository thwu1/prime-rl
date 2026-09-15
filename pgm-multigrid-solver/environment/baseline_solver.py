#!/usr/bin/env python3
"""
Baseline solver: unpreconditioned Conjugate Gradient for sparse SPD systems.
Reads Matrix Market format and solves Ax = b with b = ones.

Known limitations:
- No preconditioning — convergence degrades with condition number
- Single-level approach — no hierarchical structure
- Pure Python — no optimized sparse algebra
"""

import argparse
import json
import math


def read_matrix_market(filepath):
    """Parse a Matrix Market coordinate file into entry lists."""
    with open(filepath) as f:
        line = f.readline()
        while line.startswith('%'):
            line = f.readline()

        nrows, ncols, nnz_total = map(int, line.split())

        row_idx = []
        col_idx = []
        values = []
        for line in f:
            parts = line.split()
            r, c, v = int(parts[0]) - 1, int(parts[1]) - 1, float(parts[2])
            row_idx.append(r)
            col_idx.append(c)
            values.append(v)

    return nrows, row_idx, col_idx, values, nnz_total


def spmv(n, row_idx, col_idx, values, x):
    """Sparse matrix-vector multiply y = A*x."""
    y = [0.0] * n
    for r, c, v in zip(row_idx, col_idx, values):
        y[r] += v * x[c]
    return y


def dot_product(a, b):
    s = 0.0
    for ai, bi in zip(a, b):
        s += ai * bi
    return s


def vec_norm(a):
    return math.sqrt(dot_product(a, a))


def vec_add(a, b, alpha=1.0):
    """Return a + alpha * b."""
    return [ai + alpha * bi for ai, bi in zip(a, b)]


def cg_solve(n, row_idx, col_idx, values, b, tol=1e-8, maxiter=500):
    """Unpreconditioned Conjugate Gradient method."""
    x = [0.0] * n
    r = list(b)
    p = list(r)

    rr = dot_product(r, r)
    b_norm = vec_norm(b)
    if b_norm == 0:
        return x, 0, 0.0, True

    last_iter = 0
    for k in range(1, maxiter + 1):
        last_iter = k
        Ap = spmv(n, row_idx, col_idx, values, p)
        pAp = dot_product(p, Ap)

        if pAp <= 0:
            break

        alpha = rr / pAp
        x = vec_add(x, p, alpha)
        r = vec_add(r, Ap, -alpha)

        r_norm = vec_norm(r)
        if r_norm / b_norm < tol:
            return x, k, r_norm, True

        rr_new = dot_product(r, r)
        beta = rr_new / rr
        p = vec_add(r, p, beta)
        rr = rr_new

    Ax = spmv(n, row_idx, col_idx, values, x)
    true_r = vec_add(b, Ax, -1.0)
    true_norm = vec_norm(true_r)
    return x, last_iter, true_norm, (true_norm / b_norm < tol)


def main():
    parser = argparse.ArgumentParser(description="Baseline CG solver")
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--tol", type=float, default=1e-8)
    parser.add_argument("--maxiter", type=int, default=500)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    n, row_idx, col_idx, values, nnz = read_matrix_market(args.matrix)
    b = [1.0] * n

    x, iters, res_norm, converged = cg_solve(
        n, row_idx, col_idx, values, b, tol=args.tol, maxiter=args.maxiter
    )

    b_norm = vec_norm(b)
    rel_res = res_norm / b_norm if b_norm > 0 else 0.0

    results = {
        "iterations": iters,
        "residual_norm": res_norm,
        "relative_residual": rel_res,
        "converged": converged,
        "grid_complexity": 1.0,
        "operator_complexity": 1.0,
        "n_levels": 1,
        "level_sizes": [n],
    }

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    status = "CONVERGED" if converged else "FAILED"
    print(f"{status}: {iters} iterations, relative_residual={rel_res:.2e}")


if __name__ == "__main__":
    main()
