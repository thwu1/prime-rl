"""Rank-1 lattice rule integration.

A rank-1 lattice rule with n points and generating vector z in Z^d
produces points:
    x_k = {k * z / n},  k = 0, 1, ..., n-1
where {.} denotes the component-wise fractional part.

For randomized QMC (RQMC), a uniform random shift Delta in [0,1)^d
is added:
    x_k = {k * z / n + Delta}
and multiple independent shifts are averaged to obtain an unbiased
estimator with reduced variance.
"""
import numpy as np


def generate_lattice_points(z, n, d):
    """Generate n rank-1 lattice points in [0,1)^d.

    Points are x_k = {k * z / n} for k = 0, ..., n-1,
    where {.} denotes the component-wise fractional part.
    """
    k = np.arange(n, dtype=np.int64).reshape(-1, 1)
    z_arr = np.array(z[:d], dtype=np.int64).reshape(1, -1)
    points = (k * z_arr) / n
    return points


def lattice_estimate(func, z, n, d):
    """Estimate integral using an unshifted rank-1 lattice rule."""
    pts = generate_lattice_points(z, n, d)
    return float(np.mean(func(pts)))


def shifted_lattice_estimate(func, z, n, d, n_shifts=30, seed=42):
    """Randomized QMC via shift-averaging.

    Computes n_shifts independent randomly-shifted lattice estimates
    and returns their average. Each shift is drawn uniformly from [0,1)^d.
    """
    raise NotImplementedError("Shift-averaging not yet implemented")
