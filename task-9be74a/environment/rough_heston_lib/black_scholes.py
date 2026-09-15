"""Black-Scholes option pricing and implied volatility inversion."""
import numpy as np
from scipy import stats


def black_price(K, T, F, vol, opttype=1.0):
    """Compute Black option price."""
    s = vol * T**0.5
    d1 = np.log(F / K) / s + 0.5 * s
    d2 = d1 - s
    price = opttype * (F * stats.norm.cdf(opttype * d1) - K * stats.norm.cdf(opttype * d2))
    return price


def black_impvol(K, T, F, value, opttype=1, TOL=1e-5, MAX_ITER=1000):
    """Recover Black implied volatility by bisection."""
    K = np.atleast_1d(np.asarray(K, dtype=float))
    value = np.atleast_1d(np.asarray(value, dtype=float))
    opttype = np.full_like(K, opttype, dtype=float)

    IMPVOL_MIN = 1e-10
    IMPVOL_MAX = 5.0

    low = IMPVOL_MIN * np.ones_like(K)
    high = IMPVOL_MAX * np.ones_like(K)
    mid = 0.5 * (low + high)
    for _ in range(MAX_ITER):
        price = black_price(K, T, F, mid, opttype)
        diff = (price - value) / np.maximum(value, 1e-30)
        if np.all(np.abs(diff) < TOL):
            return mid
        mask = diff > 0
        high[mask] = mid[mask]
        low[~mask] = mid[~mask]
        mid = 0.5 * (low + high)
    mid = np.where(np.abs(diff) < TOL, mid, np.nan)
    return mid
