"""Stochastic simulator: maps 2D parameters to 2D observations.

This forward model has no tractable likelihood function.
The prior over parameters is Uniform([-1, 1]^2).

Usage:
    from simulator import simulate

    theta = np.array([[0.3, -0.2]])  # shape (n, 2)
    x = simulate(theta)              # shape (n, 2)
"""
import numpy as np


def simulate(theta, seed=None):
    """Run the stochastic forward model.

    Args:
        theta: Parameters, shape (n, 2). Each row must be in [-1, 1]^2.
        seed: Optional int seed for reproducibility.

    Returns:
        Simulated data, shape (n, 2).
    """
    rng = np.random.RandomState(seed) if seed is not None else np.random
    theta = np.atleast_2d(np.asarray(theta, dtype=np.float64))
    n = theta.shape[0]
    a = rng.uniform(-np.pi / 2, np.pi / 2, size=(n, 1))
    r = rng.normal(0.1, 0.01, size=(n, 1))
    p = np.hstack([np.cos(a) * r + 0.25, np.sin(a) * r])
    ang = -np.pi / 4.0
    c, s = np.cos(ang), np.sin(ang)
    z0 = (c * theta[:, 0] - s * theta[:, 1]).reshape(-1, 1)
    z1 = (s * theta[:, 0] + c * theta[:, 1]).reshape(-1, 1)
    return p + np.hstack([-np.abs(z0), z1])
