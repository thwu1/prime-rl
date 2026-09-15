"""
Gromov-Wasserstein optimal transport toolkit.

Standalone implementation (no POT dependency) of:
- Gromov-Wasserstein distance (conditional gradient solver)
- Fused Gromov-Wasserstein distance
- GW barycenters (block coordinate descent)

Uses the factored loss decomposition from Peyre, Cuturi & Solomon (ICML 2016)
for O(n^2) tensor-matrix products, with closed-form quadratic line search.
"""

import numpy as np
from scipy.optimize import linprog
from scipy.spatial.distance import cdist as scipy_cdist


# ---------------------------------------------------------------------------
# Inner linear OT solver via LP
# ---------------------------------------------------------------------------

def _emd(p, q, M):
    """Solve the Earth Mover's Distance linear program.

    min <T, M>  s.t.  T @ 1 = p,  T.T @ 1 = q,  T >= 0
    """
    n, m = len(p), len(q)
    c = M.flatten()

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

    result = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=(0, None), method='highs')
    if not result.success:
        raise RuntimeError(f"EMD LP solver failed: {result.message}")
    T = result.x.reshape(n, m)
    T = np.maximum(T, 0.0)
    return T


# ---------------------------------------------------------------------------
# Loss decomposition utilities
# ---------------------------------------------------------------------------

def _transform_matrix(C1, C2, loss_fun):
    """Decompose loss L(a,b) = f1(a) + f2(b) - h1(a)*h2(b)."""
    if loss_fun == 'square_loss':
        fC1 = C1 ** 2
        fC2 = C2 ** 2
        hC1 = C1.copy()
        hC2 = 2.0 * C2
    elif loss_fun == 'kl_loss':
        fC1 = C1 * np.log(C1 + 1e-18) - C1
        fC2 = C2.copy()
        hC1 = C1.copy()
        hC2 = np.log(C2 + 1e-18)
    else:
        raise ValueError(f"Unknown loss_fun: '{loss_fun}'. Use 'square_loss' or 'kl_loss'.")
    return fC1, fC2, hC1, hC2


def _init_matrix(C1, C2, p, q, loss_fun):
    """Compute constC, hC1, hC2 for the tensor-product formula.

    constC_{ij} = (f1(C1) @ p)_i + (q^T @ f2(C2)^T)_j
    """
    fC1, fC2, hC1, hC2 = _transform_matrix(C1, C2, loss_fun)
    p_col = p.reshape(-1, 1)
    q_row = q.reshape(1, -1)
    constC = (fC1 @ p_col) @ np.ones((1, len(q))) + \
             np.ones((len(p), 1)) @ (q_row @ fC2.T)
    return constC, hC1, hC2


def _tensor_product(constC, hC1, hC2, T):
    """Compute L(C1, C2) ⊗ T = constC - hC1 @ T @ hC2^T."""
    return constC - hC1 @ T @ hC2.T


def _gwloss(constC, hC1, hC2, T):
    """GW loss: <L(C1,C2) ⊗ T, T>."""
    return np.sum(_tensor_product(constC, hC1, hC2, T) * T)


def _gwggrad(constC, hC1, hC2, T):
    """GW gradient: 2 * (L(C1,C2) ⊗ T).

    Note: differs from the true gradient by a constant in the null space
    of marginal-preserving directions; equivalent for the CG linear subproblem.
    """
    return 2.0 * _tensor_product(constC, hC1, hC2, T)


def _solve_1d_linesearch_quad(a, b):
    """Minimize f(t) = a*t^2 + b*t over [0, 1]."""
    if a > 0:
        return np.clip(-b / (2.0 * a), 0.0, 1.0)
    elif a + b < 0:
        return 1.0
    else:
        return 0.0


# ---------------------------------------------------------------------------
# Gromov-Wasserstein solver
# ---------------------------------------------------------------------------

def gromov_wasserstein(C1, C2, p=None, q=None, loss_fun='square_loss',
                       max_iter=1000, tol=1e-9):
    """Compute the Gromov-Wasserstein transport plan and distance.

    Uses conditional gradient (Frank-Wolfe) with closed-form line search.

    Parameters
    ----------
    C1 : (n, n) array - source structure matrix
    C2 : (m, m) array - target structure matrix
    p  : (n,) array or None - source distribution (uniform if None)
    q  : (m,) array or None - target distribution (uniform if None)
    loss_fun : 'square_loss' or 'kl_loss'
    max_iter : maximum CG iterations
    tol : convergence threshold on plan change (Frobenius norm)

    Returns
    -------
    T : (n, m) array - optimal transport plan
    distance : float - GW distance value
    """
    C1 = np.asarray(C1, dtype=np.float64)
    C2 = np.asarray(C2, dtype=np.float64)
    n, m = C1.shape[0], C2.shape[0]

    if p is None:
        p = np.ones(n, dtype=np.float64) / n
    else:
        p = np.asarray(p, dtype=np.float64)
    if q is None:
        q = np.ones(m, dtype=np.float64) / m
    else:
        q = np.asarray(q, dtype=np.float64)

    symmetric = np.allclose(C1, C1.T, atol=1e-10) and np.allclose(C2, C2.T, atol=1e-10)

    # Initial transport plan: outer product of marginals
    G = np.outer(p, q)

    # Precompute factored loss matrices
    constC, hC1, hC2 = _init_matrix(C1, C2, p, q, loss_fun)
    if not symmetric:
        constCt, hC1t, hC2t = _init_matrix(C1.T, C2.T, p, q, loss_fun)

    for _ in range(int(max_iter)):
        old_G = G.copy()

        # Compute gradient
        if symmetric:
            grad = _gwggrad(constC, hC1, hC2, G)
        else:
            grad = 0.5 * (_gwggrad(constC, hC1, hC2, G) +
                          _gwggrad(constCt, hC1t, hC2t, G))

        # Solve linear OT sub-problem
        Gc = _emd(p, q, grad)
        deltaG = Gc - G

        # Closed-form quadratic line search
        dot = hC1 @ deltaG @ hC2.T
        a = -np.sum(dot * deltaG)
        if symmetric:
            b = -2.0 * np.sum(dot * G)
        else:
            b = -(np.sum(dot * G) + np.sum((hC1 @ G @ hC2.T) * deltaG))

        t = _solve_1d_linesearch_quad(a, b)
        G = G + t * deltaG

        if np.linalg.norm(G - old_G) < tol:
            break

    distance = _gwloss(constC, hC1, hC2, G)
    return G, float(distance)


# ---------------------------------------------------------------------------
# Fused Gromov-Wasserstein solver
# ---------------------------------------------------------------------------

def fused_gromov_wasserstein(M, C1, C2, p=None, q=None, loss_fun='square_loss',
                              alpha=0.5, max_iter=1000, tol=1e-9):
    """Compute the Fused Gromov-Wasserstein transport plan and distance.

    Objective: (1-alpha)*<T, M> + alpha * GW_structural(T)

    Parameters
    ----------
    M  : (n, m) array - cross-domain feature cost
    C1 : (n, n) array - source structure matrix
    C2 : (m, m) array - target structure matrix
    p  : (n,) or None - source distribution
    q  : (m,) or None - target distribution
    loss_fun : 'square_loss' or 'kl_loss'
    alpha : float in (0, 1) - structure vs feature trade-off
    max_iter, tol : convergence parameters

    Returns
    -------
    T : (n, m) array - optimal transport plan
    distance : float - FGW distance value
    """
    M = np.asarray(M, dtype=np.float64)
    C1 = np.asarray(C1, dtype=np.float64)
    C2 = np.asarray(C2, dtype=np.float64)
    n, m = C1.shape[0], C2.shape[0]

    if p is None:
        p = np.ones(n, dtype=np.float64) / n
    else:
        p = np.asarray(p, dtype=np.float64)
    if q is None:
        q = np.ones(m, dtype=np.float64) / m
    else:
        q = np.asarray(q, dtype=np.float64)

    symmetric = np.allclose(C1, C1.T, atol=1e-10) and np.allclose(C2, C2.T, atol=1e-10)

    G = np.outer(p, q)
    constC, hC1, hC2 = _init_matrix(C1, C2, p, q, loss_fun)
    if not symmetric:
        constCt, hC1t, hC2t = _init_matrix(C1.T, C2.T, p, q, loss_fun)

    M_lin = (1.0 - alpha) * M

    for _ in range(int(max_iter)):
        old_G = G.copy()

        if symmetric:
            gw_grad = _gwggrad(constC, hC1, hC2, G)
        else:
            gw_grad = 0.5 * (_gwggrad(constC, hC1, hC2, G) +
                             _gwggrad(constCt, hC1t, hC2t, G))

        grad = M_lin + alpha * gw_grad

        Gc = _emd(p, q, grad)
        deltaG = Gc - G

        # Line search
        dot = hC1 @ deltaG @ hC2.T
        a = -alpha * np.sum(dot * deltaG)
        if symmetric:
            b = np.sum(M_lin * deltaG) - 2.0 * alpha * np.sum(dot * G)
        else:
            b = np.sum(M_lin * deltaG) - alpha * (
                np.sum(dot * G) + np.sum((hC1 @ G @ hC2.T) * deltaG)
            )

        t = _solve_1d_linesearch_quad(a, b)
        G = G + t * deltaG

        if np.linalg.norm(G - old_G) < tol:
            break

    gw_loss = _gwloss(constC, hC1, hC2, G)
    lin_loss = np.sum(M * G)
    distance = (1.0 - alpha) * lin_loss + alpha * gw_loss
    return G, float(distance)


# ---------------------------------------------------------------------------
# Gromov-Wasserstein barycenters
# ---------------------------------------------------------------------------

def gw_barycenters(N, Cs, ps=None, p=None, lambdas=None, loss_fun='square_loss',
                    max_iter=100, tol=1e-3, init_C=None, random_state=None):
    """Compute the GW barycenter structure matrix via block coordinate descent.

    Alternates between:
    1. Computing GW transport plans from barycenter to each input
    2. Updating the barycenter structure via weighted Frechet mean

    Parameters
    ----------
    N : int - barycenter size
    Cs : list of S (n_s, n_s) arrays - input structure matrices
    ps : list of S (n_s,) arrays or None - input distributions
    p  : (N,) array or None - barycenter distribution
    lambdas : list of S floats or None - mixture weights
    loss_fun : 'square_loss' or 'kl_loss'
    max_iter, tol : convergence parameters
    init_C : (N, N) array or None - initial barycenter (random if None)
    random_state : int or None - for reproducible random initialization

    Returns
    -------
    C : (N, N) array - barycenter structure matrix
    """
    S = len(Cs)
    Cs = [np.asarray(C, dtype=np.float64) for C in Cs]

    if ps is None:
        ps = [np.ones(C.shape[0], dtype=np.float64) / C.shape[0] for C in Cs]
    else:
        ps = [np.asarray(pi, dtype=np.float64) for pi in ps]

    if p is None:
        p = np.ones(N, dtype=np.float64) / N
    else:
        p = np.asarray(p, dtype=np.float64)

    if lambdas is None:
        lambdas = [1.0 / S] * S

    # Initialize barycenter
    if init_C is not None:
        C = np.asarray(init_C, dtype=np.float64).copy()
    else:
        rng = np.random.RandomState(random_state)
        xalea = rng.randn(N, 2)
        C = scipy_cdist(xalea, xalea)
        if C.max() > 0:
            C = C / C.max()

    # Precompute inverse marginal outer product
    inv_p = np.where(p > 1e-16, 1.0 / p, 0.0)
    prod = np.outer(inv_p, inv_p)

    for _ in range(int(max_iter)):
        Cprev = C.copy()

        # Step 1: Compute GW transport plans
        Ts = []
        for s in range(S):
            T_s, _ = gromov_wasserstein(C, Cs[s], p, ps[s], loss_fun,
                                         max_iter=max_iter, tol=1e-5)
            Ts.append(T_s)

        # Step 2: Update barycenter structure
        if loss_fun == 'square_loss':
            numerator = sum(
                lambdas[s] * Ts[s] @ Cs[s] @ Ts[s].T for s in range(S)
            )
            C = numerator * prod
        elif loss_fun == 'kl_loss':
            log_sum = sum(
                lambdas[s] * Ts[s] @ np.log(np.maximum(Cs[s], 1e-16)) @ Ts[s].T
                for s in range(S)
            )
            C = np.exp(log_sum * prod)

        err = np.linalg.norm(C - Cprev)
        if err < tol:
            break

    return C
