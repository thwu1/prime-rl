"""
Iterative Krylov subspace solver for Newton linear systems.

This module should implement restarted GMRES with left preconditioning
via Arnoldi iteration and Givens rotations for the Hessenberg
least-squares subproblem.
"""
import numpy as np


def preconditioned_gmres(A_matvec, b, x0=None, M_solve=None,
                         tol=1e-6, max_iter=100, restart=30):
    """Solve Ax = b using left-preconditioned restarted GMRES.

    Parameters
    ----------
    A_matvec : callable
        Computes the matrix-vector product A @ v for a given vector v.
    b : ndarray, shape (n,)
        Right-hand side vector.
    x0 : ndarray or None
        Initial guess. Defaults to zero vector.
    M_solve : callable or None
        Left preconditioner: computes M^{-1} @ v. If None, no
        preconditioning is applied (identity preconditioner).
    tol : float
        Relative residual tolerance: converge when ||r_k|| / ||b|| < tol.
    max_iter : int
        Maximum total number of matrix-vector products across all restarts.
    restart : int
        Restart the Arnoldi process after this many inner iterations.

    Returns
    -------
    x : ndarray, shape (n,)
        Approximate solution vector.
    converged : bool
        True if relative residual tolerance was achieved.
    n_matvecs : int
        Total number of A_matvec calls performed.
    """
    raise NotImplementedError(
        "GMRES solver not yet implemented. Implement Arnoldi iteration "
        "with Givens rotations for the Hessenberg least-squares problem."
    )
