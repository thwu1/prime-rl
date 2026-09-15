"""Maximal coupling implementations.

See spec.md Sections 2 and 3 for the algorithms.
"""
import numpy as np

__all__ = [
    "maximal_coupling_reference",
    "maximal_coupling",
    "ReflectionMaximalCoupling",
]


def maximal_coupling_reference(rv1, rv2):
    """Sample a single draw from a maximal coupling between rv1 and rv2.

    This is a reference (slow) implementation that processes one sample
    at a time. It is provided as a working example; you must implement
    the vectorized version below.

    Returns
    -------
    x, y, cost : float, float, int
    """
    rv1_draw = rv1.rvs()
    cost = 1
    if np.random.uniform(0, rv1.pdf(rv1_draw)) < rv2.pdf(rv1_draw):
        return rv1_draw, rv1_draw, cost
    rv2_draw = rv2.rvs()
    cost += 1
    while np.random.uniform(0, rv2.pdf(rv2_draw)) < rv1.pdf(rv2_draw):
        rv2_draw = rv2.rvs()
        cost += 1
    return rv1_draw, rv2_draw, cost


def maximal_coupling(rv1, rv2, size=1000):
    """Vectorized maximal coupling between rv1 and rv2.

    Parameters
    ----------
    rv1, rv2 : scipy.stats distribution objects
        Must have .rvs(size=...) and .pdf(...) methods.
    size : int
        Number of coupled samples to draw.

    Returns
    -------
    samples : np.ndarray of shape (size, 2)
        Column 0 from rv1, column 1 from rv2 (equal if coupled).
    cost : np.ndarray of shape (size,)
        Number of draws needed for each sample.
    """
    raise NotImplementedError(
        "Implement vectorized maximal coupling — see spec.md Section 2"
    )


class ReflectionMaximalCoupling:
    """Reflection maximal coupling for multivariate normals.

    Given a base distribution s (typically N(0, I)) and proposal covariance
    Sigma, produces coupled samples X ~ N(mu1, Sigma) and Y ~ N(mu2, Sigma)
    that are correlated even when not equal.

    See spec.md Section 3 for the algorithm.
    """

    def __init__(self, base_distribution, proposal_cov):
        """Initialise with base distribution and proposal covariance.

        Parameters
        ----------
        base_distribution : scipy.stats distribution
            Typically multivariate_normal(0, I) or norm(0, 1).
        proposal_cov : array-like
            Covariance matrix Sigma.
        """
        raise NotImplementedError(
            "Initialise ReflectionMaximalCoupling — see spec.md Section 3"
        )

    def __call__(self, mu1, mu2, chains):
        """Produce coupled samples.

        Parameters
        ----------
        mu1, mu2 : array-like
            Mean vectors for the two distributions.
        chains : int
            Number of coupled samples to produce.

        Returns
        -------
        X, Y : np.ndarray of shape (chains, dim)
        """
        raise NotImplementedError(
            "Implement reflection maximal coupling — see spec.md Section 3"
        )
