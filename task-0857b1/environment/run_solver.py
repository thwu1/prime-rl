"""
Test harness for geometric multigrid solver.
Runs mg_solve on multiple grid sizes and records convergence data to results.json.
"""

import json
import sys
import traceback
import numpy as np

sys.path.insert(0, '/app')
from poisson import assemble_poisson_matrix, rhs_manufactured, compute_error
from multigrid import mg_solve


def f_source(x, y):
    """Source term for manufactured solution u = sin(pi*x)*sin(pi*y)."""
    return 2.0 * np.pi ** 2 * np.sin(np.pi * x) * np.sin(np.pi * y)


def u_exact(x, y):
    """Exact solution."""
    return np.sin(np.pi * x) * np.sin(np.pi * y)


def run_test(n):
    """Run multigrid solve on n x n interior grid and return metrics."""
    b = rhs_manufactured(n, f_source)
    x, residuals = mg_solve(n, b, nu1=2, nu2=2, omega=2.0 / 3.0,
                            tol=1e-10, max_iter=100)

    # Compute asymptotic convergence factor: geometric mean of per-iteration
    # reduction ratios in a fixed early window (iterations 2-6), avoiding both
    # the initial transient (iteration 1) and terminal effects on fine grids.
    num_iters = len(residuals) - 1
    if num_iters >= 5:
        # Use iterations 2 through min(6, num_iters-1) for steady-state estimate
        k_start = 2
        k_end = min(6, num_iters - 1)
        if residuals[k_start] > 1e-14:
            avg_factor = float(
                (residuals[k_end] / residuals[k_start]) ** (1.0 / (k_end - k_start))
            )
        else:
            avg_factor = 0.0
    elif num_iters > 1 and residuals[1] > 1e-14:
        avg_factor = float(
            (residuals[-1] / residuals[1]) ** (1.0 / (num_iters - 1))
        )
    else:
        avg_factor = 0.0

    l2_err, linf_err = compute_error(x, n, u_exact)

    return {
        'n': n,
        'num_iterations': num_iters,
        'final_residual': float(residuals[-1]),
        'convergence_factor': avg_factor,
        'l2_error': float(l2_err),
        'linf_error': float(linf_err),
    }


def main():
    grid_sizes = [15, 31, 63, 127, 255]
    results = {}
    for n in grid_sizes:
        print(f'Solving on {n}x{n} grid ({n * n} unknowns)...')
        try:
            r = run_test(n)
            results[str(n)] = r
            print(f'  Iterations: {r["num_iterations"]}, '
                  f'Conv factor: {r["convergence_factor"]:.4f}, '
                  f'L2 error: {r["l2_error"]:.2e}')
        except Exception as e:
            print(f'  FAILED: {e}')
            traceback.print_exc()
            results[str(n)] = {'error': str(e)}

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print('\nResults saved to /app/results.json')


if __name__ == '__main__':
    main()
