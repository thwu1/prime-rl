#!/usr/bin/env python3
"""
Mixed-precision geometric multigrid V-cycle preconditioned CG solver
for the 2D Poisson equation on [0,1]^2.

"""

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def build_2d_laplacian(n, dtype=np.float64):
    """Build the unscaled 2D 5-point Laplacian for n x n interior grid."""
    e = np.ones(n, dtype=dtype)
    T = sparse.diags([-e[:-1], 2 * e, -e[:-1]], [-1, 0, 1], format='csr')
    I_n = sparse.eye(n, dtype=dtype, format='csr')
    A = sparse.kron(I_n, T, format='csr') + sparse.kron(T, I_n, format='csr')
    return A.astype(dtype)


def build_rhs(n, dtype=np.float64):
    """Build RHS b = h^2 * f(x,y) where f = 2*pi^2*sin(pi*x)*sin(pi*y)."""
    h = 1.0 / (n + 1)
    pts = np.array([(k + 1) * h for k in range(n)], dtype=np.float64)
    X, Y = np.meshgrid(pts, pts)
    f_vals = 2.0 * np.pi ** 2 * np.sin(np.pi * X) * np.sin(np.pi * Y)
    return (h ** 2 * f_vals).flatten().astype(dtype)


def exact_solution_vec(n):
    """Exact solution u(x,y) = sin(pi*x)*sin(pi*y) at interior grid points."""
    h = 1.0 / (n + 1)
    pts = np.array([(k + 1) * h for k in range(n)], dtype=np.float64)
    X, Y = np.meshgrid(pts, pts)
    return (np.sin(np.pi * X) * np.sin(np.pi * Y)).flatten()


def build_prolongation_1d(n_coarse, dtype=np.float64):
    """Build 1D bilinear interpolation from n_coarse to n_fine = 2*n_coarse+1."""
    n_fine = 2 * n_coarse + 1
    rows, cols, vals = [], [], []

    for j in range(n_coarse):
        rows.append(2 * j + 1)
        cols.append(j)
        vals.append(1.0)

    for k in range(n_coarse + 1):
        fi = 2 * k
        if fi >= n_fine:
            break
        if k > 0:
            rows.append(fi)
            cols.append(k - 1)
            vals.append(0.5)
        if k < n_coarse:
            rows.append(fi)
            cols.append(k)
            vals.append(0.5)

    return sparse.csr_matrix(
        (np.array(vals, dtype=dtype), (rows, cols)),
        shape=(n_fine, n_coarse)
    )


def setup_multigrid(n, fine_dtype=np.float64, coarse_dtype=np.float32):
    """Build multigrid hierarchy with transfer operators and Galerkin coarse
    operators. Level 0 is finest (n x n)."""
    levels = []
    current_n = n

    A0 = build_2d_laplacian(current_n, dtype=fine_dtype)
    levels.append({'n': current_n, 'A': A0, 'dtype': fine_dtype})

    while current_n >= 3 and (current_n - 1) % 2 == 0:
        n_c = (current_n - 1) // 2
        if n_c < 1:
            break

        P1d = build_prolongation_1d(n_c, dtype=np.float64)
        P = sparse.kron(P1d, P1d, format='csr')
        R = (0.25 * P.T).tocsr()

        levels[-1]['P'] = P
        levels[-1]['R'] = R

        A_fine_f64 = levels[-1]['A'].astype(np.float64)
        A_c_f64 = (R @ A_fine_f64 @ P).tocsr()

        dt = coarse_dtype
        levels.append({'n': n_c, 'A': A_c_f64.astype(dt), 'dtype': dt})
        current_n = n_c

    return levels


def weighted_jacobi(A, b, x, omega, steps):
    """Weighted Jacobi smoother preserving dtype of x."""
    dt = x.dtype
    d_inv = (1.0 / A.diagonal()).astype(dt)
    w = dt.type(omega)
    for _ in range(steps):
        r = (b - A @ x).astype(dt)
        x = x + w * (d_inv * r)
    return x


def v_cycle(levels, level, b, x, omega=2.0 / 3.0, nu1=2, nu2=2):
    """Multigrid V-cycle with weighted Jacobi smoothing."""
    A = levels[level]['A']
    dt = levels[level]['dtype']

    if level == len(levels) - 1:
        n = A.shape[0]
        if n == 1:
            return np.array([b[0] / A[0, 0]], dtype=dt)
        sol = spsolve(A.astype(np.float64), b.astype(np.float64))
        return sol.astype(dt)

    x = weighted_jacobi(A, b.astype(dt), x, omega, nu1)

    r = (b.astype(np.float64) -
         levels[level]['A'].astype(np.float64) @ x.astype(np.float64))

    R = levels[level]['R']
    r_c = (R @ r).astype(levels[level + 1]['dtype'])

    n_c = levels[level + 1]['n']
    e_c = np.zeros(n_c * n_c, dtype=levels[level + 1]['dtype'])
    e_c = v_cycle(levels, level + 1, r_c, e_c, omega, nu1, nu2)

    P = levels[level]['P']
    e_f = (P @ e_c.astype(np.float64)).astype(dt)

    x = x + e_f
    x = weighted_jacobi(A, b.astype(dt), x, omega, nu2)

    return x


def pcg(A, b, precond, tol=1e-10, maxiter=50):
    """Preconditioned Conjugate Gradient returning convergence history."""
    n = len(b)
    x = np.zeros(n, dtype=np.float64)
    r = b.copy().astype(np.float64)
    r0_norm = float(np.linalg.norm(r))
    history = []

    z = precond(r)
    p = z.copy()
    rz = float(np.dot(r, z))

    for k in range(1, maxiter + 1):
        Ap = (A @ p).astype(np.float64)
        pAp = float(np.dot(p, Ap))
        alpha = rz / pAp

        x = x + alpha * p
        r = r - alpha * Ap

        r_norm = float(np.linalg.norm(r))
        rel_res = r_norm / r0_norm
        history.append(rel_res)

        if rel_res < tol:
            return x, k, rel_res, history

        z = precond(r)
        rz_new = float(np.dot(r, z))
        beta = rz_new / rz
        p = z + beta * p
        rz = rz_new

    return x, maxiter, float(np.linalg.norm(r)) / r0_norm, history


def main():
    N = 63

    A = build_2d_laplacian(N, dtype=np.float64)
    b = build_rhs(N, dtype=np.float64)

    levels = setup_multigrid(N, fine_dtype=np.float64, coarse_dtype=np.float32)

    print(f"Multigrid levels: {len(levels)}")
    for i, lev in enumerate(levels):
        print(f"  Level {i}: {lev['n']}x{lev['n']} "
              f"({lev['n']**2} unknowns), dtype={lev['dtype']}")

    def mg_precond(r):
        x0 = np.zeros_like(r, dtype=np.float64)
        result = v_cycle(levels, 0, r, x0)
        return result.astype(np.float64)

    x, iters, rel_res, history = pcg(A, b, mg_precond, tol=1e-10, maxiter=50)

    u_exact = exact_solution_vec(N)
    error_linf = float(np.max(np.abs(x - u_exact)))

    # Save solution
    np.save('/app/solution.npy', x.astype(np.float64))

    # Save results
    results = {
        'grid_size': N,
        'total_iterations': iters,
        'final_relative_residual': rel_res,
        'solution_error_linf': error_linf,
        'convergence_history': history,
    }
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Generate convergence plot
    plt.figure(figsize=(8, 5))
    plt.semilogy(range(1, len(history) + 1), history, 'b-o', markersize=5)
    plt.xlabel('Iteration')
    plt.ylabel('Relative Residual ||r|| / ||r_0||')
    plt.title('Solver Convergence History')
    plt.grid(True, which='both', linestyle='--', alpha=0.5)
    plt.tight_layout()
    plt.savefig('/app/convergence.png', dpi=100)
    plt.close()

    print(f"\nConverged in {iters} iterations")
    print(f"Final relative residual: {rel_res:.2e}")
    print(f"Solution error (L-inf): {error_linf:.2e}")


if __name__ == '__main__':
    main()
