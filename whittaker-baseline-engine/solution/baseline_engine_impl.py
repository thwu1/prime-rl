"""
Whittaker-smoothing baseline correction engine.

Implements five iterative penalized least squares algorithms from scratch
using only numpy and scipy.

"""

import numpy as np
from scipy.sparse import diags as sp_diags, eye as sp_eye
from scipy.sparse.linalg import spsolve
from scipy.special import expit

_EPS = np.finfo(float).eps


# ---------------------------------------------------------------------------
# Penalty matrix construction
# ---------------------------------------------------------------------------

def _diff_matrix_sparse(n, diff_order):
    """Build the finite-difference matrix D_d as a sparse CSC matrix."""
    diagonals = np.zeros(2 * diff_order + 1)
    diagonals[diff_order] = 1
    for _ in range(diff_order):
        diagonals = diagonals[:-1] - diagonals[1:]
    # diagonals now has length diff_order + 1, e.g. [-1, 1] for order 1
    return sp_diags(
        diagonals,
        np.arange(diff_order + 1),
        shape=(n - diff_order, n),
        format="csc",
    )


def _penalty_sparse(n, diff_order):
    """Return D_d^T @ D_d as sparse CSC matrix."""
    D = _diff_matrix_sparse(n, diff_order)
    return (D.T @ D).tocsc()


def diff_penalty_diags(n, diff_order=2, lower_only=True):
    """
    Banded diagonals of D_d^T @ D_d.

    Parameters
    ----------
    n : int
        Data size.
    diff_order : int
        Finite-difference order.
    lower_only : bool
        If True return (diff_order+1, n) with main diagonal at row 0.
        If False return (2*diff_order+1, n) in LAPACK banded format.

    Returns
    -------
    numpy.ndarray
    """
    if diff_order == 0:
        return np.ones((1, n))

    P = _penalty_sparse(n, diff_order).toarray()

    if lower_only:
        result = np.zeros((diff_order + 1, n))
        for k in range(diff_order + 1):
            d = np.diag(P, -k)
            result[k, : len(d)] = d
    else:
        num = 2 * diff_order + 1
        result = np.zeros((num, n))
        for k in range(num):
            offset = diff_order - k
            d = np.diag(P, offset)
            if offset >= 0:
                result[k, offset : offset + len(d)] = d
            else:
                result[k, : len(d)] = d

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relative_difference(old, new):
    """L2 relative difference with eps floor on denominator."""
    denom = max(np.linalg.norm(old), _EPS)
    return np.linalg.norm(new - old) / denom


def _safe_std(arr, ddof=1):
    """Standard deviation protected against empty / single-element arrays."""
    if arr.size < 2:
        return _EPS
    s = np.std(arr, ddof=ddof)
    if s == 0:
        return _EPS
    return s


def _solve(y, weights, lam, penalty_sparse):
    """Solve (diag(weights) + lam * P) v = diag(weights) y."""
    n = len(y)
    W = sp_diags(weights, 0, shape=(n, n), format="csc")
    A = W + lam * penalty_sparse
    return spsolve(A, weights * y)


# ---------------------------------------------------------------------------
# asls
# ---------------------------------------------------------------------------

def asls(y, lam=1e6, p=0.01, diff_order=2, max_iter=50, tol=1e-3):
    y = np.asarray(y, dtype=float)
    n = len(y)
    P = _penalty_sparse(n, diff_order)
    weights = np.ones(n)
    tol_history = np.empty(max_iter + 1)

    for i in range(max_iter + 1):
        baseline = _solve(y, weights, lam, P)
        new_weights = np.where(y > baseline, p, 1 - p)
        calc_diff = _relative_difference(weights, new_weights)
        tol_history[i] = calc_diff
        if calc_diff < tol:
            break
        weights = new_weights

    return baseline, {"weights": weights, "tol_history": tol_history[: i + 1]}


# ---------------------------------------------------------------------------
# arpls
# ---------------------------------------------------------------------------

def arpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3):
    y = np.asarray(y, dtype=float)
    n = len(y)
    P = _penalty_sparse(n, diff_order)
    weights = np.ones(n)
    tol_history = np.empty(max_iter + 1)

    for i in range(max_iter + 1):
        baseline = _solve(y, weights, lam, P)
        residual = y - baseline
        neg_residual = residual[residual < 0]
        if neg_residual.size < 2:
            i -= 1
            break
        std = _safe_std(neg_residual, ddof=1)
        mean_neg = np.mean(neg_residual)
        # expit(x) = 1/(1+exp(-x)); use negative sign to match formula
        new_weights = expit(-(2 / std) * (residual - (2 * std - mean_neg)))
        calc_diff = _relative_difference(weights, new_weights)
        tol_history[i] = calc_diff
        if calc_diff < tol:
            break
        weights = new_weights

    return baseline, {"weights": weights, "tol_history": tol_history[: i + 1]}


# ---------------------------------------------------------------------------
# iarpls
# ---------------------------------------------------------------------------

def iarpls(y, lam=1e5, diff_order=2, max_iter=50, tol=1e-3):
    y = np.asarray(y, dtype=float)
    n = len(y)
    P = _penalty_sparse(n, diff_order)
    weights = np.ones(n)
    tol_history = np.empty(max_iter + 1)

    for i in range(1, max_iter + 2):
        baseline = _solve(y, weights, lam, P)
        residual = y - baseline
        neg_residual = residual[residual < 0]
        if neg_residual.size < 2:
            i -= 1
            break
        std = _safe_std(neg_residual, ddof=1)
        inner = (np.exp(min(i, 100)) / std) * (residual - 2 * std)
        new_weights = 0.5 * (1 - inner / np.sqrt(1 + inner ** 2))
        calc_diff = _relative_difference(weights, new_weights)
        tol_history[i - 1] = calc_diff
        if calc_diff < tol:
            break
        weights = new_weights

    return baseline, {"weights": weights, "tol_history": tol_history[:i]}


# ---------------------------------------------------------------------------
# drpls
# ---------------------------------------------------------------------------

def drpls(y, lam=1e5, eta=0.5, diff_order=2, max_iter=50, tol=1e-3):
    if diff_order < 2:
        raise ValueError('diff_order must be 2 or greater')
    y = np.asarray(y, dtype=float)
    n = len(y)

    P_d = _penalty_sparse(n, diff_order)
    P_1 = _penalty_sparse(n, 1)
    P_n = lam * P_d
    I_n = sp_eye(n, format="csc")

    # Fixed term: I - eta * P_n  (used for weight-dependent penalty each iteration)
    term = I_n - eta * P_n
    # Fixed base penalty: P_1 + P_n
    base = (P_1 + P_n).tocsc()

    weights = np.ones(n)
    tol_history = np.empty(max_iter + 1)

    for i in range(1, max_iter + 2):
        # System: (P_1 + P_n + diag(w) @ (I - eta*P_n)) v = w * y
        W_diag = sp_diags(weights, 0, shape=(n, n), format="csc")
        A = base + W_diag @ term
        baseline = spsolve(A, weights * y)

        residual = y - baseline
        neg_residual = residual[residual < 0]
        if neg_residual.size < 2:
            i -= 1
            break
        std = _safe_std(neg_residual, ddof=1)
        mean_neg = np.mean(neg_residual)
        inner = (np.exp(min(i, 100)) / std) * (
            residual - (2 * std - mean_neg)
        )
        new_weights = 0.5 * (1 - inner / (1 + np.abs(inner)))
        calc_diff = _relative_difference(weights, new_weights)
        tol_history[i - 1] = calc_diff
        if calc_diff < tol:
            break
        weights = new_weights

    return baseline, {"weights": weights, "tol_history": tol_history[:i]}


# ---------------------------------------------------------------------------
# aspls
# ---------------------------------------------------------------------------

def aspls(y, lam=1e5, diff_order=2, max_iter=100, tol=1e-3, asymmetric_coef=0.5):
    y = np.asarray(y, dtype=float)
    n = len(y)

    P_d = _penalty_sparse(n, diff_order)
    weights = np.ones(n)
    alpha = np.ones(n)
    tol_history = np.empty(max_iter + 1)

    for i in range(max_iter + 1):
        # System: (diag(w) + lam * diag(alpha) @ P_d) v = diag(w) y
        W_diag = sp_diags(weights, 0, shape=(n, n), format="csc")
        A_diag = sp_diags(alpha, 0, shape=(n, n), format="csc")
        A = W_diag + lam * A_diag @ P_d
        baseline = spsolve(A, weights * y)

        residual = y - baseline
        neg_residual = residual[residual < 0]
        if neg_residual.size < 2:
            i -= 1
            break
        std = _safe_std(neg_residual, ddof=1)
        # expit(-z) = 1/(1+exp(z))
        new_weights = expit(-(asymmetric_coef / std) * (residual - std))
        calc_diff = _relative_difference(weights, new_weights)
        tol_history[i] = calc_diff
        if calc_diff < tol:
            break
        weights = new_weights
        abs_d = np.abs(residual)
        alpha = abs_d / abs_d.max()

    return baseline, {
        "weights": weights,
        "alpha": alpha,
        "tol_history": tol_history[: i + 1],
    }


# ---------------------------------------------------------------------------
# auto_baseline
# ---------------------------------------------------------------------------

def auto_baseline(y, algorithms=None, lam_candidates=None):
    y = np.asarray(y, dtype=float)

    if algorithms is None:
        algorithms = ["asls", "arpls", "iarpls", "drpls", "aspls"]
    if lam_candidates is None:
        lam_candidates = [1e3, 1e4, 1e5, 1e6, 1e7]

    _funcs = {
        "asls": asls,
        "arpls": arpls,
        "iarpls": iarpls,
        "drpls": drpls,
        "aspls": aspls,
    }

    best_score = np.inf
    best_baseline = None
    best_info = None

    for algo_name in algorithms:
        func = _funcs[algo_name]
        for lam_val in lam_candidates:
            try:
                bl, params = func(y, lam=lam_val)
                w = params["weights"]
                residual = y - bl
                d2 = np.diff(bl, 2)
                score = float(np.sum(w * residual ** 2) + 0.01 * np.sum(d2 ** 2))
                if score < best_score:
                    best_score = score
                    best_baseline = bl
                    best_info = {
                        "algorithm": algo_name,
                        "lam": lam_val,
                        "score": score,
                    }
            except Exception:
                continue

    return best_baseline, best_info
