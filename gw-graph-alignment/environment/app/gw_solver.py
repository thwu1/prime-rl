import numpy as np
from scipy.optimize import linprog


def gromov_wasserstein(C1, C2, p, q, loss_fun='square_loss',
                       max_iter=1000, tol=1e-9, log=False):
    """Compute Gromov-Wasserstein distance via conditional gradient.

    Solves: min_T sum_{ijkl} L(C1_{ik}, C2_{jl}) T_{ij} T_{kl}
    s.t. T 1 = p, T^T 1 = q, T >= 0

    Parameters
    ----------
    C1 : array (n, n) - structure matrix in source space (symmetric)
    C2 : array (m, m) - structure matrix in target space (symmetric)
    p : array (n,) - source distribution
    q : array (m,) - target distribution
    loss_fun : str - 'square_loss'
    max_iter : int
    tol : float
    log : bool

    Returns
    -------
    T : array (n, m) - transport plan
    log_dict : dict (if log=True)
    """
    n, m = len(p), len(q)

    # Initialize with independent coupling
    T = np.outer(p, q)

    for iteration in range(max_iter):
        # Compute gradient tensor (proportional to true gradient)
        grad = _gwgrad(C1, C2, T)

        # Solve linear OT subproblem for descent direction
        G = _solve_lp(grad, p, q)
        deltaT = G - T

        # Quadratic line search
        alpha = _line_search(C1, C2, T, deltaT)

        T_new = T + alpha * deltaT
        change = np.max(np.abs(T_new - T))
        T = T_new

        if change < tol:
            break

    gw_dist = _gwcost(C1, C2, T, loss_fun)

    if log:
        return T, {"gw_dist": gw_dist, "iterations": iteration + 1}
    return T


def _gwgrad(C1, C2, T):
    """Gradient tensor of GW square-loss objective.

    For the conditional gradient LP subproblem, the argmin is invariant
    to positive scaling of the gradient, so we use the compact tensor form
    constC - 2 * C1 @ T @ C2^T rather than the full gradient.
    """
    n, m = T.shape
    p = T.sum(axis=1)
    q = T.sum(axis=0)

    constC = np.outer(C1 ** 2 @ p, np.ones(m)) + \
             np.outer(np.ones(n), q @ C2 ** 2)

    return constC - 2 * C1 @ T @ C2.T


def _line_search(C1, C2, T, deltaT):
    """Closed-form quadratic line search for GW square-loss.

    Along T(alpha) = T + alpha * deltaT, the GW cost is quadratic in alpha:
        f(alpha) = a * alpha^2 + b * alpha + const

    Coefficients derived from the tensor structure of the loss.
    """
    dot = C1 @ deltaT @ C2.T
    dot_val = np.sum(dot * deltaT)
    a = -2 * dot_val

    b = -4 * np.sum(dot * T)

    return _solve_1d_linesearch_quad(a, b)


def _solve_1d_linesearch_quad(a, b):
    """Minimize f(x) = a*x^2 + b*x + c over [0, 1]."""
    if a > 0:
        return min(1.0, max(0.0, -b / (2.0 * a)))
    else:
        if a + b < 0:
            return 1.0
        else:
            return 0.0


def _gwcost(C1, C2, T, loss_fun):
    """Compute GW cost using the factored form for efficiency."""
    if loss_fun == 'square_loss':
        n, m = T.shape
        p = T.sum(axis=1)
        q = T.sum(axis=0)
        constC = np.outer(C1 ** 2 @ p, np.ones(m)) + \
                 np.outer(np.ones(n), q @ C2 ** 2)
        tens = constC - 2 * C1 @ T @ C2.T
        return np.sum(constC * T)
    else:
        raise ValueError(f"Unsupported loss: {loss_fun}")


def _solve_lp(cost, p, q):
    """Solve the linear OT problem: min <cost, T> s.t. T1=p, T^T1=q, T>=0."""
    n, m = len(p), len(q)
    c = cost.flatten()

    # Row-sum constraints
    A_rows = np.zeros((n, n * m))
    for i in range(n):
        A_rows[i, i * m:(i + 1) * m] = 1.0

    # Column-sum constraints
    A_cols = np.zeros((m, n * m))
    for j in range(m):
        for i in range(n):
            A_cols[j, i * m + j] = 1.0

    A_eq = np.vstack([A_rows, A_cols])
    b_eq = np.concatenate([p, q])

    res = linprog(c, A_eq=A_eq, b_eq=b_eq,
                  bounds=[(0, None)] * (n * m), method='highs')

    if res.success:
        return res.x.reshape(n, m)
    # Fallback to independent coupling
    return np.outer(p, q)
