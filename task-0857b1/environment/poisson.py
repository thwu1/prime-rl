"""
2D Poisson equation framework.
Discretizes -Laplacian(u) = f on [0,1]^2 with homogeneous Dirichlet BCs
using the standard 5-point finite difference stencil.
"""

import numpy as np
from scipy import sparse


def assemble_poisson_matrix(n):
    """
    Assemble the 2D Poisson matrix using 5-point stencil.

    Parameters:
        n: number of interior grid points per dimension

    Returns:
        (n*n) x (n*n) sparse CSR matrix representing -Laplacian
        with grid spacing h = 1/(n+1)
    """
    h = 1.0 / (n + 1)
    N = n * n

    diag_main = 4.0 * np.ones(N) / h ** 2
    diag_lr = -1.0 * np.ones(N - 1) / h ** 2
    diag_tb = -1.0 * np.ones(N - n) / h ** 2

    # Zero out connections that cross row boundaries
    for i in range(1, n):
        diag_lr[i * n - 1] = 0.0

    A = sparse.diags(
        [diag_main, diag_lr, diag_lr, diag_tb, diag_tb],
        [0, -1, 1, -n, n],
        format='csr',
    )
    return A


def rhs_manufactured(n, f_func):
    """
    Assemble RHS vector from a source function f(x, y).

    Parameters:
        n: number of interior grid points per dimension
        f_func: callable f(x, y) returning source term value

    Returns:
        vector of length n*n (row-major ordering: index = j*n + i)
    """
    h = 1.0 / (n + 1)
    b = np.zeros(n * n)
    for j in range(n):
        for i in range(n):
            x = (i + 1) * h
            y = (j + 1) * h
            b[j * n + i] = f_func(x, y)
    return b


def compute_error(u_numerical, n, u_exact_func):
    """
    Compute L2 and Linf error against an exact solution.

    Parameters:
        u_numerical: computed solution vector (length n*n)
        n: number of interior grid points per dimension
        u_exact_func: callable u(x, y)

    Returns:
        (l2_error, linf_error)
    """
    h = 1.0 / (n + 1)
    u_exact = np.zeros(n * n)
    for j in range(n):
        for i in range(n):
            x = (i + 1) * h
            y = (j + 1) * h
            u_exact[j * n + i] = u_exact_func(x, y)

    diff = u_numerical - u_exact
    l2_error = np.sqrt(h * h * np.sum(diff ** 2))
    linf_error = np.max(np.abs(diff))
    return l2_error, linf_error


def jacobi_solve(A, b, x0=None, max_iter=10000, tol=1e-10, omega=2.0 / 3.0):
    """
    Weighted Jacobi iterative solver (baseline, very slow for large grids).
    """
    n = len(b)
    x = np.zeros(n) if x0 is None else x0.copy()
    D_inv = 1.0 / A.diagonal()
    residuals = []
    for k in range(max_iter):
        r = b - A @ x
        rnorm = np.linalg.norm(r)
        residuals.append(rnorm)
        if rnorm < tol:
            break
        x = x + omega * D_inv * r
    return x, residuals
