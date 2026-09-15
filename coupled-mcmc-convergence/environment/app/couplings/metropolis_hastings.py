"""Coupled Metropolis-Hastings implementation.

See spec.md Sections 4 and 5 for the algorithms.
"""
import numpy as np
import scipy.stats as st

from .maximal_couplings import ReflectionMaximalCoupling
from .coupled_data import CoupledData

__all__ = ["metropolis_hastings", "unbiased_estimator"]


def _metropolis_accept(log_prob, proposal, current, current_log_prob, log_unif=None):
    """Handle Metropolis acceptance step.

    This helper is provided complete. It accepts or rejects each proposal
    based on the log probability ratio, optionally using a pre-generated
    log-uniform for coupling.

    Parameters
    ----------
    log_prob : callable
        Log probability density.
    proposal : np.ndarray
        Proposed positions, shape (chains, dim).
    current : np.ndarray
        Current positions, shape (chains, dim).
    current_log_prob : np.ndarray
        Log prob at current positions, shape (chains,).
    log_unif : np.ndarray or None
        Pre-generated log(U) for coupling. If None, sample fresh.

    Returns
    -------
    new_position, new_log_prob, accepted
    """
    proposal_log_prob = np.atleast_1d(log_prob(proposal))
    unif_shape = proposal_log_prob.shape
    if log_unif is None:
        log_unif = np.log(np.random.rand(*unif_shape))
    else:
        log_unif = log_unif.reshape(unif_shape)

    return_val = current.copy()
    new_log_prob = current_log_prob.copy()

    accept = log_unif < proposal_log_prob - current_log_prob
    return_val[accept] = proposal[accept]
    new_log_prob[accept] = proposal_log_prob[accept]

    return return_val, new_log_prob, accept.squeeze()


def metropolis_hastings(
    *,
    log_prob,
    proposal_cov,
    init_x,
    init_y,
    lag=1,
    iters=1000,
    chains=128,
    short_circuit=False,
) -> CoupledData:
    """Sample from a density using coupled Metropolis-Hastings.

    See spec.md Section 4 for the full algorithm.

    Parameters
    ----------
    log_prob : callable
        Log probability density to sample from.
    proposal_cov : array-like
        Proposal covariance matrix.
    init_x, init_y : array-like
        Initial positions for the two coupled chains.
    lag : int
        Number of steps chain X runs alone before coupling begins.
    iters : int
        Total iterations for chain X. Chain Y has (iters - lag) iterations.
    chains : int
        Number of parallel coupled chain pairs.
    short_circuit : bool
        If True, return immediately after all chains have met.

    Returns
    -------
    CoupledData
    """
    raise NotImplementedError(
        "Implement coupled Metropolis-Hastings — see spec.md Section 4"
    )


def unbiased_estimator(data, func, burn_in):
    """Compute an unbiased estimator of E[h(X)] using coupled chains.

    Implements Equation 2.1 from Jacob, O'Leary, and Atchade (2017).
    See spec.md Section 5 for the formula.

    Parameters
    ----------
    data : CoupledData
        Results from a coupled MCMC experiment.
    func : callable
        Test function h. Should accept array of shape (C, d) and return
        array of the same shape.
    burn_in : int
        Number of initial samples to discard (k in the paper).

    Returns
    -------
    mcmc_average, bias_correction : np.ndarray, np.ndarray
        Both of shape (chains, dim). Their sum is the unbiased estimate.
    """
    raise NotImplementedError(
        "Implement unbiased estimator — see spec.md Section 5"
    )
