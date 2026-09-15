"""
Gaussian Mixture Operations Library

Core operations for Gaussian Mixture (GM) models used in flow matching
generative models, based on the GMFlow framework (arXiv 2504.05304).

Convention - All GMs use the following tensor representation:
    gm = {
        'means':      Tensor(bs, K, D)   - component means
        'logstds':    Tensor(bs, 1, 1)   - shared log standard deviation (isotropic)
        'logweights': Tensor(bs, K, 1)   - log mixing weights (unnormalized)
    }

Where:
    bs = batch size
    K  = number of Gaussian components
    D  = data dimensionality

The log-weights are UNNORMALIZED. Normalization is handled implicitly via
log-sum-exp in loss computations and via softmax when explicit weights
are needed.
"""

import ctypes
import math
import os

import numpy as np
import torch


def gm_nll_loss(gm, samples, eps=1e-4):
    """
    Gaussian Mixture negative log-likelihood loss (without the
    normalization constant, which is irrelevant for gradient-based
    optimization).

    Args:
        gm: dict with 'means' (bs, K, D), 'logstds' (bs, 1, 1),
            'logweights' (bs, K, 1)
        samples: Tensor(bs, D) - target samples
        eps: float - stability constant for inverse std clamping

    Returns:
        Tensor(bs,) - per-sample NLL values
    """
    raise NotImplementedError("gm_nll_loss")


def gm_to_iso_gaussian(gm):
    """
    Approximate a GM as a single isotropic Gaussian by matching
    the first two moments of the mixture.

    Args:
        gm: dict with 'means' (bs, K, D), 'logstds' (bs, 1, 1),
            'logweights' (bs, K, 1)

    Returns:
        dict with:
            'mean': Tensor(bs, D) - matched mean
            'var':  Tensor(bs, 1) - matched isotropic variance
    """
    raise NotImplementedError("gm_to_iso_gaussian")


def gm_mul_iso_gaussian(gm, gaussian, gm_power, gaussian_power, eps=1e-6):
    """
    Compute the product of a powered GM with a powered isotropic Gaussian,
    yielding a new GM (Bayesian posterior update for SDE sampling).

    Args:
        gm: dict with 'means' (bs, K, D), 'logstds' (bs, 1, 1),
            'logweights' (bs, K, 1)
        gaussian: dict with 'mean' (bs, D), 'var' (bs, 1)
        gm_power: float
        gaussian_power: float
        eps: float - clamp for normalization factor

    Returns:
        tuple: (new_gm dict, output_power = gm_power)
    """
    raise NotImplementedError("gm_mul_iso_gaussian")


def gm_logprob(gm, samples):
    """
    Full log-probability of samples under a GM, including the
    normalization constant. Also returns per-component Gaussian
    log-probabilities for diagnostics.

    Args:
        gm: dict with 'means' (bs, K, D), 'logstds' (bs, 1, 1),
            'logweights' (bs, K, 1)
        samples: Tensor(bs, N, D) - N query points per batch element

    Returns:
        logprob: Tensor(bs, N) - total log-probability
        gaussian_logprobs: Tensor(bs, N, K) - per-component log-probs
    """
    raise NotImplementedError("gm_logprob")


def gm_logpdf_c(means_np, logstd, logweights_np, samples_np):
    """
    Compute GM log-probabilities using the compiled C extension.

    The shared library at /app/libgm_logpdf.so must be compiled from
    /app/gm_logpdf.c before calling this function. Use ctypes to load
    the library and call the gm_logpdf_batch function.

    Args:
        means_np: numpy float64 array of shape (K, D) - component means
        logstd: float - shared log standard deviation
        logweights_np: numpy float64 array of shape (K,) - unnormalized
            log mixing weights
        samples_np: numpy float64 array of shape (N, D) - query points

    Returns:
        numpy float64 array of shape (N,) - log-probabilities
    """
    raise NotImplementedError("gm_logpdf_c")


# ---------------------------------------------------------------------------
# The following helper functions are provided and fully implemented.
# They are correct and should not be modified.
# ---------------------------------------------------------------------------


def gm_to_sample(gm, n_samples=1):
    """
    Draw samples from a Gaussian Mixture.

    Args:
        gm: dict with 'means' (bs, K, D), 'logstds' (bs, 1, 1),
            'logweights' (bs, K, 1)
        n_samples: int

    Returns:
        Tensor(bs, n_samples, D)
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    bs, K, D = means.shape
    weights = logweights.squeeze(-1).softmax(dim=-1)
    indices = torch.multinomial(weights, n_samples, replacement=True)
    selected_means = means.gather(
        1, indices.unsqueeze(-1).expand(-1, -1, D)
    )
    stds = logstds.exp()
    noise = torch.randn_like(selected_means)
    samples = selected_means + stds * noise
    return samples


def gm_to_mean(gm, gm_power=1.0):
    """
    Weighted mean of a Gaussian Mixture.

    Args:
        gm: dict with 'means' (bs, K, D), 'logweights' (bs, K, 1)
        gm_power: float

    Returns:
        Tensor(bs, D)
    """
    means = gm['means']
    logweights = gm['logweights']
    weights = (logweights * gm_power).softmax(dim=1)
    mean = (weights * means).sum(dim=1)
    return mean


def gm_kl_div(gm_p, gm_q, n_samples=32):
    """
    Estimate the KL divergence KL(p || q) between two Gaussian Mixtures
    using Monte Carlo sampling.

    Args:
        gm_p: dict - the reference distribution
        gm_q: dict - the comparison distribution
        n_samples: int

    Returns:
        Tensor(bs,) - estimated KL divergence
    """
    raise NotImplementedError("gm_kl_div")
