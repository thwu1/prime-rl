
"""
Gaussian Mixture Model operations for flow matching and Bayesian inference.

This module provides core operations on Gaussian mixtures (GMs) with shared
isotropic covariance. All GMs are represented as dicts with keys:
  - 'means':      (bs, K, D)   component means
  - 'logstds':    (bs, 1, 1)   shared isotropic log standard deviation
  - 'logweights': (bs, K, 1)   log mixture weights (may or may not be normalized)

See /app/docs/equations.md for the mathematical specifications.
"""

import math
import torch


def gm_nll_loss(gm, sample, eps=1e-4):
    """
    Gaussian mixture negative log-likelihood (without the Gaussian normalization
    constant -D/2 * log(2*pi)).

    Args:
        gm (dict): means (bs,K,D), logstds (bs,1,1), logweights (bs,K,1).
        sample (torch.Tensor): (bs, D).
        eps (float): Clamp 1/sigma to at most 1/eps.

    Returns:
        torch.Tensor: (bs,)
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    inverse_stds = torch.exp(-logstds).clamp(max=1.0 / eps)
    diff_weighted = (sample.unsqueeze(-2) - means) * inverse_stds
    gaussian_ll = (-0.5 * diff_weighted.square() - logstds).sum(dim=-1)
    gm_nll = -torch.logsumexp(gaussian_ll + logweights.squeeze(-1), dim=-1)
    return gm_nll


def gm_to_iso_gaussian(gm):
    """
    Moment-match a Gaussian mixture to a single isotropic Gaussian.

    Args:
        gm (dict): means (bs,K,D), logstds (bs,1,1), logweights (bs,K,1).
                   logweights assumed log-softmaxed.

    Returns:
        dict: 'mean' (bs, D), 'var' (bs, 1).
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    weights = logweights.exp()
    gm_vars = (logstds * 2).exp()

    g_mean = (weights * means).sum(dim=1)
    diffs = means - g_mean.unsqueeze(1)
    between_var = (weights * diffs.square()).sum(dim=1)
    g_var = between_var.sum(dim=-1, keepdim=True) + gm_vars.squeeze(-1)

    return {'mean': g_mean, 'var': g_var}


def gm_mul_iso_gaussian(gm, gaussian, gm_power, gaussian_power, eps=1e-6):
    """
    Product of a GM^gm_power and an isotropic Gaussian^gaussian_power.

    Args:
        gm (dict): means (bs,K,D), logstds (bs,1,1), logweights (bs,K,1).
        gaussian (dict): 'mean' (bs,D), 'var' (bs,1).
        gm_power (float), gaussian_power (float), eps (float).

    Returns:
        dict: Updated GM with keys 'means', 'logstds', 'logweights'.
    """
    gm_means = gm['means']
    gm_logstds = gm['logstds']
    gm_logweights = gm['logweights']
    gm_vars = (gm_logstds * 2).exp()

    g_mean = gaussian['mean'].unsqueeze(1)
    g_var = gaussian['var'].unsqueeze(1)
    g_logstd = (torch.log(gaussian['var']) / 2).unsqueeze(1)

    power_ratio = gm_power / gaussian_power
    norm_factor = (g_var + power_ratio * gm_vars).clamp(min=eps)

    out_means = (
        g_var * gm_means + power_ratio * gm_vars * g_mean
    ) / norm_factor

    gm_diffs = gm_means - g_mean
    logweights_delta = (
        gm_diffs.square().sum(dim=-1, keepdim=True)
        * (-0.5 * power_ratio / norm_factor)
    )
    out_logweights = (
        gm_logweights + logweights_delta
    ).log_softmax(dim=1)

    out_logstds = (
        gm_logstds + g_logstd - 0.5 * torch.log(norm_factor)
    )

    return {
        'means': out_means,
        'logstds': out_logstds,
        'logweights': out_logweights,
    }


def gm_logprob(gm, samples):
    """
    Log probability of samples under a GM (with full normalization).

    Args:
        gm (dict): means (bs,K,D), logstds (bs,1,1), logweights (bs,K,1).
        samples (torch.Tensor): (bs, N, D).

    Returns:
        torch.Tensor: (bs, N).
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']
    D = means.shape[-1]

    const = -0.5 * D * math.log(2.0 * math.pi)

    logstds_4d = logstds.unsqueeze(1)
    inverse_stds = torch.exp(-logstds_4d)

    diff = samples.unsqueeze(2) - means.unsqueeze(1)
    diff_weighted = diff * inverse_stds

    gaussian_logprobs = (
        (-0.5 * diff_weighted.square() - logstds_4d).sum(dim=-1) + const
    )

    lw = logweights.squeeze(-1).unsqueeze(1)
    logprob = (gaussian_logprobs + lw).logsumexp(dim=-1)

    return logprob


def gm_mul_gm(gm1, gm2):
    """
    Product of two Gaussian mixtures, yielding a new GM with K1*K2 components.

    Args:
        gm1 (dict): means (bs,K1,D), logstds (bs,1,1), logweights (bs,K1,1).
        gm2 (dict): means (bs,K2,D), logstds (bs,1,1), logweights (bs,K2,1).

    Returns:
        dict: GM with K1*K2 components — keys 'means', 'logstds', 'logweights'.
    """
    raise NotImplementedError(
        "gm_mul_gm: product of two Gaussian mixtures is not yet implemented. "
        "See /app/docs/equations.md section 5 for the mathematical specification."
    )


def gm_kl_div(gm_p, gm_q, n_samples=256):
    """
    Monte Carlo estimate of KL(p || q) using samples from p.

    Args:
        gm_p (dict): means (bs,K_p,D), logstds (bs,1,1), logweights (bs,K_p,1).
        gm_q (dict): means (bs,K_q,D), logstds (bs,1,1), logweights (bs,K_q,1).
        n_samples (int): Number of Monte Carlo samples.

    Returns:
        torch.Tensor: (bs,) estimated KL divergence.
    """
    means = gm_p['means']
    logstds = gm_p['logstds']
    logweights = gm_p['logweights']
    bs, K, D = means.shape

    gen = torch.Generator().manual_seed(42)
    weights = logweights.squeeze(-1).softmax(dim=-1)
    component_indices = torch.multinomial(
        weights, n_samples, replacement=True, generator=gen
    )
    selected_means = means.gather(
        1, component_indices.unsqueeze(-1).expand(-1, -1, D)
    )
    noise = torch.randn(*selected_means.shape, generator=gen)
    std = logstds.exp()
    samples = selected_means + std * noise

    log_p = gm_logprob(gm_p, samples)
    log_q = gm_logprob(gm_q, samples)

    return (log_p - log_q).mean(dim=-1)


def gm_reduce(gm, target_k):
    """
    Reduce a Gaussian mixture from K components to target_k components
    while minimizing information loss.

    Args:
        gm (dict): means (bs,K,D), logstds (bs,1,1), logweights (bs,K,1).
        target_k (int): Target number of components (must be < K).

    Returns:
        dict: Reduced GM with target_k components —
              keys 'means', 'logstds', 'logweights'.

    Constraints (see /app/docs/equations.md section 7):
      - Output must have exactly target_k components
      - Weights must be properly normalized
      - The mixture mean must be preserved exactly
      - KL divergence from original to reduced must be bounded
    """
    raise NotImplementedError(
        "gm_reduce: component reduction is not yet implemented. "
        "See /app/docs/equations.md section 7 for the constraints. "
        "You must design a reduction algorithm — no specific algorithm is prescribed."
    )
