"""Ground motion model evaluation with truncated exceedance."""

import math
from scipy.stats import norm


def evaluate_gmm(mag, rjb, vs30, branch, mref, vref):
    """Evaluate a GMM branch for given magnitude, distance, and site.

    Computes the mean and sigma of ln(Y) using the parametric form
    specified in the GMM configuration.

    Returns (mu, sigma) of ln(ground motion).
    """
    c = branch["coefficients"]
    sig = branch["sigma"]

    R = math.sqrt(rjb ** 2 + c["h"] ** 2)
    dm = mag - mref

    mu = (
        c["e1"]
        + c["e2"] * dm
        + c["e3"] * dm ** 2
        + (c["c1"] + c["c2"] * dm) * math.log(R)
        + c["s"] * math.log(vref / vs30)
    )
    return mu, sig


def compute_exceedance(y, mu, sigma, trunc_level):
    """Exceedance probability P(Y > y) with upper-only truncation.

    Uses the truncated standard normal distribution with the
    specified truncation level applied to the upper tail.
    """
    z = (math.log(y) - mu) / sigma
    if z >= trunc_level:
        return 0.0
    return (norm.cdf(trunc_level) - norm.cdf(z)) / norm.cdf(trunc_level)
