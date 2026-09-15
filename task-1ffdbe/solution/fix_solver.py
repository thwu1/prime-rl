#!/usr/bin/env python3
"""
Fix all bugs in the Brusselator solver pipeline and implement GMRES.

"""

# ============================================================
# FIX 1: solver/system.py -- boundary condition for v
# The Brusselator steady state is u_ss = A, v_ss = B/A.
# The code has v_left = v_right = A/B (wrong).
# ============================================================

path1 = '/app/solver/system.py'
with open(path1, 'r') as f:
    src = f.read()
src = src.replace('v_left = A / B', 'v_left = B / A')
src = src.replace('v_right = A / B', 'v_right = B / A')
with open(path1, 'w') as f:
    f.write(src)
print("[FIX 1] system.py: boundary conditions corrected (v_bc = B/A)")


# ============================================================
# FIX 2: solver/sparse_diff.py -- column connectivity graph
# The inner loop only connects adjacent pairs in each row's
# nonzero column list: range(ii+1, min(ii+2, ...)).
# Must connect ALL pairs: range(ii+1, len(nz_cols)).
# ============================================================

path2 = '/app/solver/sparse_diff.py'
with open(path2, 'r') as f:
    src = f.read()
src = src.replace(
    'for jj in range(ii + 1, min(ii + 2, len(nz_cols))):',
    'for jj in range(ii + 1, len(nz_cols)):'
)
with open(path2, 'w') as f:
    f.write(src)
print("[FIX 2] sparse_diff.py: connectivity graph corrected")


# ============================================================
# FIX 3: solver/stepping.py -- PI controller exponent scaling
# For implicit Euler (order p=1), the PI exponents must be
# divided by (p+1) = 2. alpha=0.7 -> 0.35, beta=0.4 -> 0.2.
# ============================================================

path3 = '/app/solver/stepping.py'
with open(path3, 'r') as f:
    src = f.read()
src = src.replace('alpha = 0.7\n', 'alpha = 0.7 / 2.0\n')
src = src.replace('beta = 0.4\n', 'beta = 0.4 / 2.0\n')
with open(path3, 'w') as f:
    f.write(src)
print("[FIX 3] stepping.py: PI controller exponents scaled by 1/(p+1)")


# ============================================================
# IMPLEMENT: krylov.py -- restarted GMRES with left preconditioning
# Arnoldi iteration + Givens rotations for the Hessenberg
# least-squares subproblem.
# ============================================================

krylov_src = '''\
"""
Iterative Krylov subspace solver for Newton linear systems.
Implements restarted GMRES with left preconditioning via
Arnoldi iteration and Givens rotations.
"""
import numpy as np


def preconditioned_gmres(A_matvec, b, x0=None, M_solve=None,
                         tol=1e-6, max_iter=100, restart=30):
    """Solve Ax = b using left-preconditioned restarted GMRES.

    Parameters
    ----------
    A_matvec : callable
        Computes the matrix-vector product A @ v.
    b : ndarray, shape (n,)
        Right-hand side.
    x0 : ndarray or None
        Initial guess (zero if None).
    M_solve : callable or None
        Left preconditioner M^{-1} @ v.  Identity if None.
    tol : float
        Relative residual tolerance.
    max_iter : int
        Maximum total matrix-vector products across all restarts.
    restart : int
        Inner Arnoldi cycle length before restart.

    Returns
    -------
    x : ndarray
    converged : bool
    n_matvecs : int
    """
    n = len(b)
    if x0 is None:
        x = np.zeros(n)
    else:
        x = x0.copy()

    if M_solve is None:
        M_solve = lambda v: v.copy()

    b_norm = np.linalg.norm(b)
    if b_norm < 1e-15:
        return np.zeros(n), True, 0

    total_mv = 0

    # Outer restart loop
    max_outer = max(1, max_iter // max(restart, 1) + 1)
    for _ in range(max_outer):
        # Compute preconditioned residual
        r = M_solve(b - A_matvec(x))
        beta = np.linalg.norm(r)

        if beta / b_norm < tol:
            return x, True, total_mv

        m = min(restart, max_iter - total_mv)
        if m <= 0:
            break

        # Arnoldi process with Givens rotations
        V = np.zeros((n, m + 1))
        H = np.zeros((m + 1, m))
        V[:, 0] = r / beta

        # Givens rotation storage
        cs = np.zeros(m)
        sn = np.zeros(m)
        g = np.zeros(m + 1)
        g[0] = beta

        for j in range(m):
            total_mv += 1
            # Arnoldi step: w = M^{-1} A v_j
            w = M_solve(A_matvec(V[:, j]))

            # Modified Gram-Schmidt orthogonalisation
            for i in range(j + 1):
                H[i, j] = np.dot(w, V[:, i])
                w = w - H[i, j] * V[:, i]

            H[j + 1, j] = np.linalg.norm(w)
            if H[j + 1, j] > 1e-14:
                V[:, j + 1] = w / H[j + 1, j]

            # Apply previous Givens rotations to column j of H
            for i in range(j):
                tmp = cs[i] * H[i, j] + sn[i] * H[i + 1, j]
                H[i + 1, j] = -sn[i] * H[i, j] + cs[i] * H[i + 1, j]
                H[i, j] = tmp

            # Compute new Givens rotation for (H[j,j], H[j+1,j])
            rr = np.sqrt(H[j, j] ** 2 + H[j + 1, j] ** 2)
            if rr > 1e-14:
                cs[j] = H[j, j] / rr
                sn[j] = H[j + 1, j] / rr
            else:
                cs[j] = 1.0
                sn[j] = 0.0

            # Eliminate H[j+1, j]
            H[j, j] = cs[j] * H[j, j] + sn[j] * H[j + 1, j]
            H[j + 1, j] = 0.0

            # Update RHS of least-squares problem
            tmp = cs[j] * g[j] + sn[j] * g[j + 1]
            g[j + 1] = -sn[j] * g[j] + cs[j] * g[j + 1]
            g[j] = tmp

            # Check convergence
            if abs(g[j + 1]) / b_norm < tol:
                # Back-substitution on upper triangular H
                y = np.zeros(j + 1)
                for k in range(j, -1, -1):
                    y[k] = g[k]
                    for l in range(k + 1, j + 1):
                        y[k] -= H[k, l] * y[l]
                    y[k] /= H[k, k]
                x = x + V[:, :j + 1] @ y
                return x, True, total_mv

        # End of inner cycle: solve least-squares and update x
        y = np.zeros(m)
        for k in range(m - 1, -1, -1):
            y[k] = g[k]
            for l in range(k + 1, m):
                y[k] -= H[k, l] * y[l]
            y[k] /= H[k, k]
        x = x + V[:, :m] @ y

    # Did not converge within max_iter
    return x, False, total_mv
'''

krylov_path = '/app/solver/krylov.py'
with open(krylov_path, 'w') as f:
    f.write(krylov_src)
print("[IMPL] krylov.py: restarted GMRES with Givens rotations implemented")

print("\nAll fixes and implementations applied.")
