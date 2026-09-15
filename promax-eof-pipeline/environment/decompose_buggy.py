"""Decomposition module: EOF analysis via SVD."""
import numpy as np
from scipy.linalg import svd


def eof_decompose(X, n_modes):
    """
    Compute EOF decomposition via Singular Value Decomposition.

    Parameters
    ----------
    X : ndarray, shape (n_time, n_features)
        Centered data matrix.
    n_modes : int
        Number of modes to retain.

    Returns
    -------
    components : ndarray, shape (n_modes, n_features)
    scores : ndarray, shape (n_time, n_modes)
    singular_values : ndarray, shape (n_modes,)
    exp_var : ndarray, shape (n_modes,)
    exp_var_ratio : ndarray, shape (n_modes,)
    total_var : float
    """
    n_time, n_features = X.shape

    U, s, Vt = svd(X, full_matrices=False)

    # Truncate
    U = U[:, :n_modes]
    s = s[:n_modes]
    Vt = Vt[:n_modes, :]

    # Deterministic sign convention: max absolute value is positive
    for i in range(n_modes):
        max_idx = np.argmax(np.abs(Vt[i]))
        if Vt[i, max_idx] < 0:
            Vt[i] *= -1
            U[:, i] *= -1

    components = Vt
    scores = U * s[None, :]

    # Explained variance from singular values
    exp_var = s ** 2 / n_time
    total_var = np.sum(np.var(X, axis=0, ddof=1))
    exp_var_ratio = exp_var / total_var

    return components, scores, s, exp_var, exp_var_ratio, total_var
