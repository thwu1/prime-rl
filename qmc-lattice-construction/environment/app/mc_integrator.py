"""Standard Monte Carlo integration."""
import numpy as np


def mc_estimate(func, d, n, seed=42):
    """Estimate integral of func over [0,1]^d using n random points."""
    rng = np.random.default_rng(seed)
    x = rng.random((n, d))
    return float(np.mean(func(x)))
