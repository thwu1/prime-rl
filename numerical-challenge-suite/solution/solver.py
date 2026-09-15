#!/usr/bin/env python3
"""

Audit solver: independently computes correct values for all five
experiments, compares with originals, and writes the audit report.
"""

import json
import math
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu
from scipy.integrate import quad


def solve_gauss_legendre():
    """Verify via high-precision adaptive quadrature."""
    val, _ = quad(lambda x: np.exp(x) / (1.0 + 25.0 * x**2), -1, 1,
                  limit=200)
    return float(val)


def solve_hermite_quadrature():
    """Analytical formula: integral of exp(-x^2)(x^4 + 2x^2 + 3) dx.

    Using Gaussian moment formulas:
      int x^{2n} exp(-x^2) dx = (2n-1)!! * sqrt(pi) / 2^n
    n=0: sqrt(pi)
    n=1: sqrt(pi)/2
    n=2: 3*sqrt(pi)/4

    Result = 3*sqrt(pi)/4 + 2*sqrt(pi)/2 + 3*sqrt(pi)
           = sqrt(pi) * (3/4 + 1 + 3)
           = 19*sqrt(pi)/4
    """
    return 19.0 * math.sqrt(math.pi) / 4.0


def solve_sturm_eigencount():
    """Reimplement Sturm sequence independently."""
    N = 5000
    diag = [2.0 + 0.3 * math.sin(2.0 * math.pi * i / N)
            for i in range(1, N + 1)]

    def count_below(sigma):
        cnt = 0
        q = diag[0] - sigma
        if q < 0:
            cnt += 1
        for k in range(1, N):
            if abs(q) < 1e-300:
                q = 1e-300 if q >= 0 else -1e-300
            q = (diag[k] - sigma) - 1.0 / q
            if q < 0:
                cnt += 1
        return cnt

    return count_below(0.8) - count_below(0.2)


def solve_sparse_logdet():
    """Build the CORRECT symmetric matrix with off-diag = 0.05.

    The buggy script only stores upper triangle, then applies
    (M + M.T) / 2 which halves off-diag to 0.025. We build the
    full symmetric matrix directly.
    """
    N = 1500
    rows, cols, data = [], [], []

    for i in range(N):
        rows.append(i)
        cols.append(i)
        data.append(np.sqrt(float(i + 1)))

    bands = [3**k for k in range(7)]
    for i in range(N):
        for b in bands:
            j = i + b
            if 0 <= j < N:
                rows.extend([i, j])
                cols.extend([j, i])
                data.extend([0.05, 0.05])

    M = sp.coo_matrix((data, (rows, cols)), shape=(N, N)).tocsc()
    lu = splu(M)
    return float(np.sum(np.log(np.abs(lu.U.diagonal()))))


def solve_spectral_radius():
    """Use full eigendecomposition instead of power iteration.

    The buggy script uses only 50 power iterations, insufficient
    because the matrix has closely-clustered top eigenvalues
    (ratio |lambda_2/lambda_1| ~ 0.993), giving very slow convergence.
    """
    N = 400
    bw = 20
    B = np.zeros((N, N))
    for i in range(N):
        for d in range(-bw, bw + 1):
            j = i + d
            if 0 <= j < N:
                B[i, j] = 1.0 / (1.0 + abs(d))
    return float(np.max(np.linalg.eigvalsh(B)))


def values_match(v1, v2, is_int=False):
    if is_int:
        return int(v1) == int(v2)
    rel_err = abs(float(v1) - float(v2)) / max(abs(float(v2)), 1e-300)
    return rel_err < 1e-6


def main():
    # Load original experiment results
    with open('/app/lab/results.json') as f:
        originals = json.load(f)

    print("Computing correct reference values...\n")

    # Solve each experiment
    solvers = {
        "gauss_legendre": (solve_gauss_legendre, False),
        "hermite_quadrature": (solve_hermite_quadrature, False),
        "sturm_eigencount": (solve_sturm_eigencount, True),
        "sparse_logdet": (solve_sparse_logdet, False),
        "spectral_radius": (solve_spectral_radius, False),
    }

    report = {}
    for name, (solver_fn, is_int) in solvers.items():
        correct_val = solver_fn()
        orig_val = originals.get(name)
        is_correct = values_match(correct_val, orig_val, is_int) if orig_val is not None else False

        report[name] = {
            "value": correct_val,
            "original_is_correct": is_correct,
        }

        status = "CORRECT" if is_correct else "INCORRECT"
        if is_int:
            print(f"  {name}: correct={correct_val}, original={orig_val}, [{status}]")
        else:
            print(f"  {name}: correct={correct_val:.15e}, original={orig_val}, [{status}]")

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("\nAudit report written to /app/audit_report.json")


if __name__ == "__main__":
    main()
