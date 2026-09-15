"""
Dense SP2 reference implementation for validation.

This provides a straightforward dense-matrix SP2 purification that can be
used to verify sparse implementations on small systems.
"""
import numpy as np


def gershgorin_bounds_dense(H_dense):
    """Compute Gershgorin circle bounds for a dense symmetric matrix."""
    diag = np.diag(H_dense)
    row_sums = np.sum(np.abs(H_dense), axis=1) - np.abs(diag)
    emin = float(np.min(diag - row_sums))
    emax = float(np.max(diag + row_sums))
    return emin, emax


def dense_sp2(H_dense, n_occ, tol=1e-10, max_iter=200):
    """
    Dense SP2 density matrix purification (reference implementation).

    Args:
        H_dense: np.ndarray, symmetric Hamiltonian matrix
        n_occ: int, number of occupied states
        tol: float, idempotency convergence tolerance
        max_iter: int, maximum iterations

    Returns:
        D: np.ndarray, density matrix
    """
    n = H_dense.shape[0]

    emin, emax = gershgorin_bounds_dense(H_dense)

    # Scale: occupied (low energy) -> eigenvalue 1, unoccupied -> 0
    X = (emax * np.eye(n) - H_dense) / (emax - emin)

    for iteration in range(max_iter):
        X2 = X @ X

        tr_X2 = np.trace(X2)
        tr_alt = 2.0 * np.trace(X) - tr_X2

        if abs(tr_alt - n_occ) < abs(tr_X2 - n_occ):
            X = 2.0 * X - X2
        else:
            X = X2

        idem_err = np.linalg.norm(X @ X - X, 'fro')
        if idem_err < tol:
            break

    return X
