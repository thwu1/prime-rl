
"""
L-Moment Analysis Toolkit — reference implementation.

Implements unbiased sample L-moments via PWM, trimmed L-moments (Elamir-Seheult),
GEV/GPD fitting via method of L-moments, return levels, L-comoment matrices,
and L-moment ratio diagram classification.

All L-moment formulas follow Hosking (1990, 1997) internally; returned shape
parameters match scipy conventions (genextreme c and genpareto c respectively).
"""

import numpy as np
from math import comb, gamma, log, pi, sin

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_EULER_MASCHERONI = 0.5772156649015329


def _safe_comb(n, k):
    """Binomial coefficient that returns 0 for out-of-range arguments."""
    if n < 0 or k < 0 or k > n:
        return 0
    return comb(n, k)


# ---------------------------------------------------------------------------
# sample_lmoments
# ---------------------------------------------------------------------------

def sample_lmoments(x, nmom=4):
    """Unbiased sample L-moments using probability weighted moment estimators.

    Parameters
    ----------
    x : array_like
        Sample observations (any order).
    nmom : int
        Number of L-moments to compute (default 4).

    Returns
    -------
    ndarray of shape (nmom,)
        L-moments lambda_1, lambda_2, ..., lambda_nmom.
    """
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)

    # Probability weighted moments: beta_r = (1/n) sum_{i=r}^{n-1} C(i,r)/C(n-1,r) * x[i]
    betas = np.zeros(nmom)
    for r in range(nmom):
        s = 0.0
        cn1r = comb(n - 1, r)
        for i in range(r, n):
            s += comb(i, r) / cn1r * x[i]
        betas[r] = s / n

    # Convert PWMs to L-moments:
    # lambda_r = sum_{k=0}^{r-1} p_{r-1,k} * beta_k
    # p_{r-1,k} = (-1)^{r-1-k} C(r-1,k) C(r-1+k,k)
    lmoms = np.zeros(nmom)
    for r in range(1, nmom + 1):
        val = 0.0
        for k in range(r):
            p = (-1) ** (r - 1 - k) * comb(r - 1, k) * comb(r - 1 + k, k)
            val += p * betas[k]
        lmoms[r - 1] = val

    return lmoms


# ---------------------------------------------------------------------------
# sample_tlmoments
# ---------------------------------------------------------------------------

def sample_tlmoments(x, trim=(1, 1), nmom=4):
    """Trimmed L-moments with asymmetric trimming (Elamir & Seheult 2003).

    Parameters
    ----------
    x : array_like
        Sample observations.
    trim : tuple (s, t)
        Number of lower (s) and upper (t) order statistics to trim.
    nmom : int
        Number of TL-moments to compute.

    Returns
    -------
    ndarray of shape (nmom,)
    """
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    s, t = int(trim[0]), int(trim[1])

    lmoms = np.zeros(nmom)
    for r in range(1, nmom + 1):
        total_order = r + s + t
        denom = r * comb(n, total_order)
        if denom == 0:
            continue
        val = 0.0
        for j in range(1, n + 1):  # 1-indexed position
            w = 0.0
            for k in range(r):
                c1 = comb(r - 1, k)
                c2 = _safe_comb(j - 1, r + s - k - 1)
                c3 = _safe_comb(n - j, t + k)
                w += (-1) ** k * c1 * c2 * c3
            val += x[j - 1] * w
        lmoms[r - 1] = val / denom

    return lmoms


# ---------------------------------------------------------------------------
# lratios
# ---------------------------------------------------------------------------

def lratios(x):
    """Compute L-moment ratios.

    Returns
    -------
    dict with keys 'l_cv', 'l_skew', 'l_kurt'.
    """
    lm = sample_lmoments(x, nmom=4)
    l1, l2, l3, l4 = lm
    return {
        "l_cv": l2 / l1 if l1 != 0 else float("inf"),
        "l_skew": l3 / l2 if l2 != 0 else 0.0,
        "l_kurt": l4 / l2 if l2 != 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# GEV fitting
# ---------------------------------------------------------------------------

def _gev_tau3(kappa_h):
    """Theoretical GEV tau_3 as a function of Hosking shape kappa_H."""
    if abs(kappa_h) < 1e-10:
        return 2 * log(3) / log(2) - 3  # Gumbel: ~0.1699
    return 2 * (1 - 3 ** (-kappa_h)) / (1 - 2 ** (-kappa_h)) - 3


def fit_gev(x):
    """Fit GEV via method of L-moments (Hosking 1997).

    Returns (loc, scale, shape) matching scipy.stats.genextreme convention:
    shape = Hosking kappa directly (c > 0 = Weibull/short-tail, c < 0 = Frechet/heavy-tail).
    """
    from scipy.optimize import brentq

    lm = sample_lmoments(x, nmom=3)
    l1, l2, l3 = lm[0], lm[1], lm[2]
    t3 = l3 / l2

    # Solve for Hosking kappa from tau_3
    def objective(kh):
        return _gev_tau3(kh) - t3

    try:
        kappa_h = brentq(objective, -0.99, 10.0, xtol=1e-12)
    except ValueError:
        # Fallback: rational initial approximation (Hosking 1997)
        c = 2 / (3 + t3) - log(2) / log(3)
        kappa_h = 7.8590 * c + 2.9554 * c ** 2

    if abs(kappa_h) < 1e-8:
        # Gumbel limit
        scale = l2 / log(2)
        loc = l1 - scale * _EULER_MASCHERONI
        shape = 0.0
    else:
        gk = gamma(1 + kappa_h)
        scale = l2 * kappa_h / ((1 - 2 ** (-kappa_h)) * gk)
        loc = l1 - scale * (1 - gk) / kappa_h
        shape = kappa_h  # scipy genextreme c = Hosking kappa

    return (loc, scale, shape)


# ---------------------------------------------------------------------------
# GPD fitting
# ---------------------------------------------------------------------------

def fit_gpd(x):
    """Fit GPD via method of L-moments, location fixed at 0.

    Returns (scale, shape) with scipy convention (positive = heavy-tailed).
    """
    lm = sample_lmoments(x, nmom=3)
    l1, l2, l3 = lm[0], lm[1], lm[2]
    t3 = l3 / l2

    # Hosking shape
    kappa_h = (1 - 3 * t3) / (1 + t3)
    alpha = l2 * (1 + kappa_h) * (2 + kappa_h)

    shape = -kappa_h  # scipy convention
    return (alpha, shape)


# ---------------------------------------------------------------------------
# return_level
# ---------------------------------------------------------------------------

def return_level(params, dist, T):
    """T-year return level.

    For GEV: params = (loc, scale, shape) — shape = scipy genextreme c.
    For GPD: params = (scale, shape) — shape = scipy genpareto c, exceedances.
    """
    dist = dist.lower()

    if dist == "gev":
        loc, scale, shape = params
        p = 1 - 1.0 / T
        if abs(shape) < 1e-10:
            return loc - scale * log(-log(p))
        return loc + scale / shape * (1 - (-log(p)) ** shape)

    elif dist == "gpd":
        scale, shape = params
        if abs(shape) < 1e-10:
            return scale * log(T)
        return scale / shape * (T ** shape - 1)

    raise ValueError(f"Unknown distribution: {dist}")


# ---------------------------------------------------------------------------
# lcomoment_matrix
# ---------------------------------------------------------------------------

def lcomoment_matrix(X, r=2):
    """L-comoment matrix of order r using concomitants of order statistics.

    Parameters
    ----------
    X : ndarray of shape (n_samples, n_variables)
    r : int
        L-comoment order (default 2).

    Returns
    -------
    ndarray of shape (n_variables, n_variables)
        Entry (i, j) is the L-moment of variable i computed on concomitants
        from the ordering of variable j.
    """
    X = np.asarray(X, dtype=float)
    n, m = X.shape

    result = np.zeros((m, m))
    for i in range(m):
        for j in range(m):
            # Sort by variable j; take variable i in that order
            order = np.argsort(X[:, j], kind="stable")
            xi_sorted = X[order, i]

            if r == 1:
                result[i, j] = np.mean(xi_sorted)
            else:
                # PWM-based L-moment of xi_sorted
                betas = np.zeros(r)
                for rr in range(r):
                    cn1r = comb(n - 1, rr)
                    s = 0.0
                    for idx in range(rr, n):
                        s += comb(idx, rr) / cn1r * xi_sorted[idx]
                    betas[rr] = s / n

                val = 0.0
                for k in range(r):
                    p = (
                        (-1) ** (r - 1 - k)
                        * comb(r - 1, k)
                        * comb(r - 1 + k, k)
                    )
                    val += p * betas[k]
                result[i, j] = val

    return result


# ---------------------------------------------------------------------------
# best_distribution (L-moment ratio diagram)
# ---------------------------------------------------------------------------

def _gev_tau4_from_tau3(t3):
    """Theoretical GEV tau_4 given a sample tau_3, via inverting tau_3(kappa)."""
    from scipy.optimize import brentq

    def objective(kh):
        return _gev_tau3(kh) - t3

    try:
        kh = brentq(objective, -0.99, 10.0, xtol=1e-12)
    except ValueError:
        return None

    if abs(kh) < 1e-10:
        return 16 - 10 * log(3) / log(2)  # Gumbel ~0.1504

    d = 1 - 2 ** (-kh)
    return (5 * (1 - 4 ** (-kh)) - 10 * (1 - 3 ** (-kh)) + 6 * d) / d


def _gpd_tau4_from_tau3(t3):
    """Theoretical GPD tau_4 given tau_3."""
    return t3 * (1 + 5 * t3) / (5 + t3)


def _glo_tau4_from_tau3(t3):
    """Theoretical GLO tau_4 given tau_3."""
    return (1 + 5 * t3 ** 2) / 6


_TAU4_FUNCS = {
    "gev": _gev_tau4_from_tau3,
    "gpd": _gpd_tau4_from_tau3,
    "glo": _glo_tau4_from_tau3,
}


def best_distribution(x, candidates=None):
    """Classify the best-fitting distribution using the L-moment ratio diagram.

    Compares sample (tau_3, tau_4) against theoretical tau_4(tau_3) curves.

    Parameters
    ----------
    x : array_like
    candidates : list of str or None
        Distribution names from {'gev', 'gpd', 'glo'}. Default: all three.

    Returns
    -------
    str — lowercase name of the best-fitting distribution.
    """
    if candidates is None:
        candidates = ["gev", "gpd", "glo"]

    lm = sample_lmoments(x, nmom=4)
    t3 = lm[2] / lm[1]
    t4 = lm[3] / lm[1]

    best_name = candidates[0]
    best_dist = float("inf")

    for name in candidates:
        func = _TAU4_FUNCS.get(name.lower())
        if func is None:
            continue
        t4_theo = func(t3)
        if t4_theo is None:
            continue
        d = abs(t4 - t4_theo)
        if d < best_dist:
            best_dist = d
            best_name = name.lower()

    return best_name
