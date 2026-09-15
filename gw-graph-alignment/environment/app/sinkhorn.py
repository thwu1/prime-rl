import numpy as np


def sinkhorn(a, b, M, reg, max_iter=1000, tol=1e-9, log=False):
    """Solve entropic regularized OT via Sinkhorn-Knopp.

    min_T <T, M> + reg * KL(T | a b^T)
    s.t. T 1 = a, T^T 1 = b

    Parameters
    ----------
    a : array (n,) - source distribution
    b : array (m,) - target distribution
    M : array (n, m) - cost matrix
    reg : float - regularization parameter
    max_iter : int
    tol : float
    log : bool

    Returns
    -------
    T : array (n, m) - transport plan
    log_dict : dict (if log=True)
    """
    n, m = len(a), len(b)

    K = np.exp(-M / reg)

    # Scaling vectors
    u = np.ones(n)
    v = np.ones(m)

    iterations = 0
    for i in range(max_iter):
        u_prev = u  # track previous iteration

        # Sinkhorn updates (in-place for performance)
        np.divide(a, K @ v, out=u)
        np.divide(b, K.T @ u, out=v)

        iterations = i + 1

        # Check convergence on dual variable change
        err = np.max(np.abs(u - u_prev))
        if err < tol:
            break

    # Construct transport plan
    T = u[:, None] * K * v[None, :]
    cost = np.sum(T * M)

    if log:
        return T, {"cost": cost, "iterations": iterations, "err": float(err)}
    return T


def sinkhorn_barycenter(distributions, M, reg, weights=None,
                        max_iter=100, tol=1e-7):
    """Compute Wasserstein barycenter via Sinkhorn iterations.

    Parameters
    ----------
    distributions : list of arrays, each (m,) - input distributions
    M : array (m, m) - ground cost matrix
    reg : float - regularization
    weights : array (K,) - barycentric weights (default: uniform)
    max_iter : int
    tol : float

    Returns
    -------
    bary : array (m,) - barycenter distribution
    """
    K_dists = len(distributions)
    m = len(distributions[0])

    if weights is None:
        weights = np.ones(K_dists) / K_dists

    K = np.exp(-M / reg)

    # Initialize barycenter as uniform
    bary = np.ones(m) / m

    for iteration in range(max_iter):
        bary_prev = bary.copy()

        # Aggregate dual information from each distribution
        log_bary = np.zeros(m)
        for k in range(K_dists):
            # Inner Sinkhorn projection of bary onto distributions[k]
            u_k = np.ones(m)
            v_k = np.ones(m)
            for _ in range(50):
                u_k = bary / (K @ v_k + 1e-300)
                v_k = distributions[k] / (K.T @ u_k + 1e-300)

            log_bary += weights[k] * np.log(np.maximum(u_k, 1e-300))

        bary = np.exp(log_bary)
        bary = bary / np.sum(bary)

        if np.max(np.abs(bary - bary_prev)) < tol:
            break

    return bary
