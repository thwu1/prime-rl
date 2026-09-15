"""
GEV distribution fitting via Method of L-Moments.
Follows Hosking (1997) parametric approach with Brent root-finding
for the shape-to-L-skewness inversion.
"""
import numpy as np
from math import gamma, log
from scipy.optimize import brentq
from analysis.lmoments import sample_lmoments

_EULER = 0.5772156649015329


def _gev_tau3(kappa_h):
    """Theoretical L-skewness for GEV as function of Hosking shape kappa."""
    if abs(kappa_h) < 1e-10:
        return 2 * log(3) / log(2) - 3  # Gumbel limit
    return 2 * (1 - 3 ** (-kappa_h)) / (1 - 2 ** (-kappa_h)) - 3


def fit_gev(x):
    """Fit GEV distribution using method of L-moments.

    Returns
    -------
    tuple (loc, scale, shape)
        GEV location, scale, and shape (Hosking kappa convention).
    """
    x = np.asarray(x, dtype=float)
    lm = sample_lmoments(x, nmom=3)
    l1, l2, l3 = lm[0], lm[1], lm[2]
    tau3 = l3 / l2

    # Solve for Hosking shape parameter from L-skewness
    def objective(kh):
        return _gev_tau3(kh) - tau3

    try:
        kappa_h = brentq(objective, -0.99, 10.0, xtol=1e-12)
    except ValueError:
        c = 2 / (3 + tau3) - log(2) / log(3)
        kappa_h = 7.8590 * c + 2.9554 * c ** 2

    if abs(kappa_h) < 1e-8:
        # Gumbel limit (shape = 0)
        scale = l2 / log(2)
        loc = l1 - scale * _EULER
        shape = 0.0
    else:
        gk = gamma(1 + kappa_h)
        scale = l2 * kappa_h / ((1 - 2 ** (-kappa_h)) * gk)
        loc = l1 - scale * (1 - gk) / kappa_h
        shape = -kappa_h

    return loc, scale, shape


def return_level_gev(loc, scale, shape, T):
    """Compute the T-year return level for a fitted GEV distribution.

    Uses the Hosking quantile function:
        x_T = loc + scale/shape * (1 - (-log(1-1/T))^shape)
    """
    p = 1.0 - 1.0 / T
    if abs(shape) < 1e-10:
        return loc - scale * log(-log(p))
    return loc + scale / shape * (1 - (-log(p)) ** shape)
