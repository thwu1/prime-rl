"""
Geometric Multigrid V-Cycle solver for 2D Poisson equation.
Implements bilinear prolongation, full-weighting restriction,
weighted Jacobi smoothing, and recursive V-cycle with Galerkin
coarse-grid operators and coarsest-level direct solve.
"""

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve


def _assemble_poisson(n):
    """Assemble 2D Poisson matrix for n interior points per dimension."""
    h = 1.0 / (n + 1)
    N = n * n
    if n == 1:
        return sparse.csr_matrix(np.array([[4.0 / h ** 2]]))
    diag_main = 4.0 * np.ones(N) / h ** 2
    diag_lr = -np.ones(N - 1) / h ** 2
    diag_tb = -np.ones(N - n) / h ** 2
    for i in range(1, n):
        diag_lr[i * n - 1] = 0.0
    return sparse.diags(
        [diag_main, diag_lr, diag_lr, diag_tb, diag_tb],
        [0, -1, 1, -n, n],
        format='csr',
    )


def _prolongation_1d(nc, nf):
    """
    Build 1D prolongation (linear interpolation) from nc to nf interior points.
    Requires nf = 2*nc + 1 for standard geometric coarsening.

    Coarse point j coincides with fine point 2*j+1.
    Fine points at even indices lie midway between coarse points
    (or between a coarse point and the zero boundary).
    """
    rows, cols, vals = [], [], []
    for i in range(nf):
        if i % 2 == 1:
            j = (i - 1) // 2
            rows.append(i)
            cols.append(j)
            vals.append(1.0)
        else:
            j_left = i // 2 - 1
            j_right = i // 2
            if 0 <= j_left < nc:
                rows.append(i)
                cols.append(j_left)
                vals.append(0.5)
            if 0 <= j_right < nc:
                rows.append(i)
                cols.append(j_right)
                vals.append(0.5)
    return sparse.csr_matrix((vals, (rows, cols)), shape=(nf, nc))


def build_prolongation(nc, nf):
    """
    Build 2D bilinear interpolation (prolongation) operator.
    Maps from nc*nc coarse grid unknowns to nf*nf fine grid unknowns.
    Constructed as Kronecker product of 1D prolongation operators.
    """
    P1d = _prolongation_1d(nc, nf)
    return sparse.kron(P1d, P1d, format='csr')


def build_restriction(nc, nf):
    """
    Build 2D full-weighting restriction operator.
    R = (1/4) * P^T in 2D.
    """
    P = build_prolongation(nc, nf)
    return (0.25 * P.T).tocsr()


def smooth(A, b, x, nu, omega):
    """
    Weighted Jacobi smoother.
    Performs nu iterations of: x <- x + omega * D^{-1} * (b - A*x)
    """
    D_inv = 1.0 / A.diagonal()
    for _ in range(nu):
        r = b - A @ x
        x = x + omega * D_inv * r
    return x


def mg_solve(n, b, num_levels=None, nu1=2, nu2=2, omega=2.0 / 3.0,
             tol=1e-10, max_iter=100):
    """
    Solve the 2D Poisson equation using geometric multigrid V-cycles.
    Uses Galerkin coarse-grid operators (A_c = R * A_f * P) for optimal
    convergence.

    Parameters:
        n: interior grid points per dimension (should be 2^k - 1)
        b: right-hand side vector (length n*n)
        num_levels: number of grid levels (auto-computed if None)
        nu1: number of pre-smoothing steps
        nu2: number of post-smoothing steps
        omega: weighted Jacobi relaxation parameter
        tol: relative residual tolerance for convergence
        max_iter: maximum number of V-cycles

    Returns:
        (x, residuals): solution vector and list of residual norms
    """
    # Determine grid hierarchy depth
    if num_levels is None:
        num_levels = 1
        m = n
        while m > 1 and m % 2 == 1:
            m = (m - 1) // 2
            num_levels += 1
            if m <= 1:
                break

    # Build grid sizes: finest to coarsest
    grid_sizes = [n]
    m = n
    for _ in range(1, num_levels):
        m = (m - 1) // 2
        grid_sizes.append(m)

    # Build finest-level Poisson operator
    matrices = [_assemble_poisson(n)]

    # Build inter-grid transfer operators and Galerkin coarse-grid operators
    prolongations = []
    restrictions = []
    for lvl in range(num_levels - 1):
        nf = grid_sizes[lvl]
        nc = grid_sizes[lvl + 1]
        P = build_prolongation(nc, nf)
        R = (0.25 * P.T).tocsr()
        prolongations.append(P)
        restrictions.append(R)
        # Galerkin condition: A_coarse = R * A_fine * P
        A_coarse = (R @ matrices[lvl] @ P).tocsr()
        matrices.append(A_coarse)

    def _vcycle(lvl, rhs, x0):
        """Recursive V-cycle."""
        if lvl == num_levels - 1:
            return spsolve(matrices[lvl], rhs)

        # Pre-smoothing
        x0 = smooth(matrices[lvl], rhs, x0, nu1, omega)

        # Compute and restrict the residual
        residual = rhs - matrices[lvl] @ x0
        r_coarse = restrictions[lvl] @ residual

        # Recursively solve the coarse-grid error equation
        e_coarse = _vcycle(lvl + 1, r_coarse, np.zeros(len(r_coarse)))

        # Prolongate correction and apply
        x0 = x0 + prolongations[lvl] @ e_coarse

        # Post-smoothing
        x0 = smooth(matrices[lvl], rhs, x0, nu2, omega)

        return x0

    # Main V-cycle iteration
    x = np.zeros(n * n)
    r0_norm = np.linalg.norm(b)
    if r0_norm < 1e-15:
        return x, [0.0]

    residuals = [r0_norm]
    for _ in range(max_iter):
        x = _vcycle(0, b, x)
        r_norm = np.linalg.norm(b - matrices[0] @ x)
        residuals.append(r_norm)
        if r_norm < tol * r0_norm or r_norm < 1e-15:
            break

    return x, residuals
