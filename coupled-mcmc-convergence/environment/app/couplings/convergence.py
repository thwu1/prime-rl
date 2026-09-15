"""Convergence diagnostics from coupled MCMC meeting times.

See spec.md Section 6 for the formulas.
"""
import numpy as np

__all__ = ["total_variation", "wasserstein"]


def total_variation(data):
    """Compute total variation distance upper bound from meeting times.

    Uses the pointwise TV indicator averaged over chains.
    See spec.md Section 6.

    Parameters
    ----------
    data : CoupledData
        Results from a coupled MCMC experiment.

    Returns
    -------
    np.ndarray of shape (n,)
        TV distance bound at each iteration.
    """
    raise NotImplementedError(
        "Implement total variation distance — see spec.md Section 6"
    )


def wasserstein(data):
    """Compute Wasserstein-1 distance upper bound from meeting times.

    Uses the coupled samples at lag-spaced intervals.
    See spec.md Section 6.

    Parameters
    ----------
    data : CoupledData
        Results from a coupled MCMC experiment.

    Returns
    -------
    np.ndarray of shape (n,)
        Wasserstein distance bound at each iteration.
    """
    raise NotImplementedError(
        "Implement Wasserstein distance — see spec.md Section 6"
    )
