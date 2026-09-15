
"""
IPOP-CMA-ES: Covariance Matrix Adaptation Evolution Strategy
with Increasing Population Size restart strategy.

Implements the (mu/mu_w, lambda)-CMA-ES with:
  - Weighted recombination of mu-best individuals
  - Cumulative step-size adaptation (CSA)
  - Rank-1 and rank-mu covariance matrix updates
  - Evolution path cumulation with hsig correction
  - Lazy eigendecomposition for efficiency
  - Boundary handling via clamping
  - Stagnation and condition-number based termination
  - IPOP restart: double population size on each restart

Reference: Hansen, N. (2016). The CMA Evolution Strategy: A Tutorial.
"""

import numpy as np


def optimize(func, dim, lb, ub, budget, x0=None):
    """
    Minimize func using IPOP-CMA-ES.

    Parameters
    ----------
    func : callable
        Objective function taking np.ndarray of shape (dim,), returning float.
    dim : int
        Search space dimensionality.
    lb : array-like
        Lower bounds, shape (dim,).
    ub : array-like
        Upper bounds, shape (dim,).
    budget : int
        Maximum number of function evaluations.
    x0 : array-like or None
        Optional initial guess, shape (dim,).

    Returns
    -------
    best_x : np.ndarray
        Best solution found, shape (dim,).
    best_f : float
        Best function value found.
    """
    lb = np.asarray(lb, dtype=float)
    ub = np.asarray(ub, dtype=float)

    best_x_global = None
    best_f_global = float("inf")
    total_evals = 0

    lam_default = 4 + int(3 * np.log(dim))
    lam = lam_default
    max_restarts = 9

    for restart in range(max_restarts + 1):
        remaining = budget - total_evals
        if remaining < 2 * lam:
            break

        best_x_run, best_f_run, evals_run = _cmaes_single_run(
            func,
            dim,
            lb,
            ub,
            remaining,
            lam,
            x0 if restart == 0 else None,
        )
        total_evals += evals_run

        if best_f_run < best_f_global:
            best_f_global = best_f_run
            best_x_global = best_x_run.copy()

        # IPOP: double population size for next restart
        lam = 2 * lam

    return best_x_global, best_f_global


def _cmaes_single_run(func, dim, lb, ub, budget, lam, x0=None):
    """
    Execute a single CMA-ES run.

    Returns (best_x, best_f, evaluations_used).
    """
    # --- Strategy parameters ---
    mu = lam // 2
    raw_w = np.log(mu + 0.5) - np.log(np.arange(1, mu + 1))
    weights = raw_w / raw_w.sum()
    mueff = 1.0 / np.sum(weights ** 2)

    # Learning rates
    cc = (4 + mueff / dim) / (dim + 4 + 2 * mueff / dim)
    cs = (mueff + 2) / (dim + mueff + 5)
    c1 = 2.0 / ((dim + 1.3) ** 2 + mueff)
    cmu = min(1 - c1, 2 * (mueff - 2 + 1.0 / mueff) / ((dim + 2) ** 2 + mueff))
    damps = 1 + 2 * max(0, np.sqrt((mueff - 1) / (dim + 1)) - 1) + cs

    # --- State initialization ---
    if x0 is not None:
        mean = np.asarray(x0, dtype=float).copy()
    else:
        mean = lb + (ub - lb) * np.random.rand(dim)

    sigma = 0.3 * np.max(ub - lb)
    C = np.eye(dim)
    pc = np.zeros(dim)
    ps = np.zeros(dim)
    B = np.eye(dim)
    D = np.ones(dim)
    invsqrtC = np.eye(dim)
    eigeneval = 0
    chiN = np.sqrt(dim) * (1 - 1.0 / (4 * dim) + 1.0 / (21 * dim ** 2))

    counteval = 0
    gen = 0
    best_f = float("inf")
    best_x = mean.copy()
    hist_best = []

    while counteval < budget:
        gen += 1

        # --- Sample lambda offspring ---
        arz = np.random.randn(lam, dim)
        arx = np.empty((lam, dim))
        for k in range(lam):
            arx[k] = mean + sigma * (B @ (D * arz[k]))
            arx[k] = np.clip(arx[k], lb, ub)

        # --- Evaluate fitness ---
        fitness = np.full(lam, np.inf)
        n_eval = 0
        for k in range(lam):
            if counteval >= budget:
                break
            fitness[k] = float(func(arx[k]))
            counteval += 1
            n_eval += 1
            if fitness[k] < best_f:
                best_f = fitness[k]
                best_x = arx[k].copy()

        if n_eval < mu:
            break

        # --- Sort by fitness ---
        idx = np.argsort(fitness[:n_eval])

        # Select mu best
        sel = idx[:mu]
        xmean_old = mean.copy()
        mean = weights @ arx[sel]

        # --- Update evolution paths ---
        diff = (mean - xmean_old) / sigma
        ps = (1 - cs) * ps + np.sqrt(cs * (2 - cs) * mueff) * (invsqrtC @ diff)

        norm_ps = np.linalg.norm(ps)
        expected_under_random = chiN * np.sqrt(1 - (1 - cs) ** (2 * gen))
        hsig = 1.0 if norm_ps / expected_under_random < 1.4 + 2.0 / (dim + 1) else 0.0

        pc = (1 - cc) * pc + hsig * np.sqrt(cc * (2 - cc) * mueff) * diff

        # --- Adapt covariance matrix ---
        artmp = (arx[sel] - xmean_old) / sigma  # shape (mu, dim)
        rank_mu_update = artmp.T @ np.diag(weights) @ artmp

        C = (
            (1 - c1 - cmu) * C
            + c1 * (np.outer(pc, pc) + (1 - hsig) * cc * (2 - cc) * C)
            + cmu * rank_mu_update
        )

        # --- Adapt step size ---
        sigma *= np.exp((cs / damps) * (norm_ps / chiN - 1))
        sigma = max(sigma, 1e-20)

        # --- Eigendecomposition of C (lazy) ---
        if counteval - eigeneval > lam / (c1 + cmu) / dim / 10:
            eigeneval = counteval
            C = np.triu(C) + np.triu(C, 1).T  # enforce symmetry
            try:
                eigvals, B = np.linalg.eigh(C)
                eigvals = np.maximum(eigvals, 1e-20)
                D = np.sqrt(eigvals)
                invsqrtC = B @ np.diag(1.0 / D) @ B.T
            except np.linalg.LinAlgError:
                # Reset covariance on decomposition failure
                C = np.eye(dim)
                B = np.eye(dim)
                D = np.ones(dim)
                invsqrtC = np.eye(dim)

        # --- Check termination ---
        # Condition number
        if np.max(D) > 1e7 * np.min(D):
            break

        # Step size too small
        if sigma * np.max(D) < 1e-11 * np.max(ub - lb):
            break

        # Stagnation: no improvement in recent history
        hist_best.append(best_f)
        stag_window = max(20, 10 * dim + 30)
        if len(hist_best) > stag_window:
            old_best = hist_best[-stag_window]
            if abs(best_f - old_best) < 1e-12 * (abs(old_best) + 1e-30):
                break

    return best_x, best_f, counteval
