
"""
Gaussian Mixture Model operations — complete fixed implementation.

Fixes applied:
1. gm_to_iso_gaussian: between_var.mean(dim=-1) instead of .sum(dim=-1)
2. gm_mul_iso_gaussian: power_ratio = gaussian_power / gm_power (was inverted)
3. gm_mul_gm: fully implemented (product of two GMs with K1*K2 components)
4. gm_reduce: implemented via greedy pairwise merging minimizing
   weighted squared distance at each step
"""

import math
import torch


def gm_nll_loss(gm, sample, eps=1e-4):
    """GM NLL loss (without normalization constant)."""
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    inverse_stds = torch.exp(-logstds).clamp(max=1.0 / eps)
    diff_weighted = (sample.unsqueeze(-2) - means) * inverse_stds
    gaussian_ll = (-0.5 * diff_weighted.square() - logstds).sum(dim=-1)
    gm_nll = -torch.logsumexp(gaussian_ll + logweights.squeeze(-1), dim=-1)
    return gm_nll


def gm_to_iso_gaussian(gm):
    """Moment-match a GM to a single isotropic Gaussian."""
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    weights = logweights.exp()
    gm_vars = (logstds * 2).exp()

    g_mean = (weights * means).sum(dim=1)
    diffs = means - g_mean.unsqueeze(1)
    between_var = (weights * diffs.square()).sum(dim=1)
    # FIX: .mean(dim=-1) averages over dimensions D (was .sum)
    g_var = between_var.mean(dim=-1, keepdim=True) + gm_vars.squeeze(-1)

    return {'mean': g_mean, 'var': g_var}


def gm_mul_iso_gaussian(gm, gaussian, gm_power, gaussian_power, eps=1e-6):
    """Product of GM^gm_power and isotropic Gaussian^gaussian_power."""
    gm_means = gm['means']
    gm_logstds = gm['logstds']
    gm_logweights = gm['logweights']
    gm_vars = (gm_logstds * 2).exp()

    g_mean = gaussian['mean'].unsqueeze(1)
    g_var = gaussian['var'].unsqueeze(1)
    g_logstd = (torch.log(gaussian['var']) / 2).unsqueeze(1)

    # FIX: power_ratio = gaussian_power / gm_power (was inverted)
    power_ratio = gaussian_power / gm_power
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
    """Log probability of samples under a GM (with normalization)."""
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
    """Product of two Gaussian mixtures, yielding K1*K2 components."""
    means1 = gm1['means']       # (bs, K1, D)
    logstds1 = gm1['logstds']   # (bs, 1, 1)
    logweights1 = gm1['logweights']  # (bs, K1, 1)

    means2 = gm2['means']       # (bs, K2, D)
    logstds2 = gm2['logstds']   # (bs, 1, 1)
    logweights2 = gm2['logweights']  # (bs, K2, 1)

    bs, K1, D = means1.shape
    K2 = means2.shape[1]

    vars1 = (logstds1 * 2).exp()  # (bs, 1, 1)
    vars2 = (logstds2 * 2).exp()  # (bs, 1, 1)
    norm_factor = vars1 + vars2   # (bs, 1, 1)

    # New shared log-std
    out_logstds = logstds1 + logstds2 - 0.5 * torch.log(norm_factor)

    # Expand means for all K1*K2 pairs
    m1 = means1.unsqueeze(2)  # (bs, K1, 1, D)
    m2 = means2.unsqueeze(1)  # (bs, 1, K2, D)

    # New means: weighted average by partner variance
    out_means = (
        vars2.unsqueeze(-1) * m1 + vars1.unsqueeze(-1) * m2
    ) / norm_factor.unsqueeze(-1)
    out_means = out_means.reshape(bs, K1 * K2, D)

    # Weight deltas from Gaussian overlap
    diffs = m1 - m2  # (bs, K1, K2, D)
    sq_dists = diffs.square().sum(dim=-1, keepdim=True)  # (bs, K1, K2, 1)
    deltas = -sq_dists / (2 * norm_factor.unsqueeze(-1))  # (bs, K1, K2, 1)

    # Combine log-weights and normalize
    lw1 = logweights1.unsqueeze(2)  # (bs, K1, 1, 1)
    lw2 = logweights2.unsqueeze(1)  # (bs, 1, K2, 1)
    raw_lw = (lw1 + lw2 + deltas).reshape(bs, K1 * K2, 1)
    out_logweights = raw_lw.log_softmax(dim=1)

    return {
        'means': out_means,
        'logstds': out_logstds,
        'logweights': out_logweights,
    }


def gm_kl_div(gm_p, gm_q, n_samples=256):
    """Monte Carlo KL(p || q) using samples from p."""
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
    Reduce a Gaussian mixture from K to target_k components via greedy
    pairwise merging that minimizes information loss at each step.

    Merge cost for pair (i,j): w_i * w_j / (w_i + w_j) * ||mu_i - mu_j||^2
    This is proportional to the increase in moment-matching error from the merge
    and approximates the KL divergence increase for isotropic Gaussians.

    The merge operation preserves the mixture mean exactly:
      w' = w_i + w_j
      mu' = (w_i * mu_i + w_j * mu_j) / (w_i + w_j)
    """
    means = gm['means']       # (bs, K, D)
    logstds = gm['logstds']   # (bs, 1, 1)
    logweights = gm['logweights']  # (bs, K, 1)

    bs, K, D = means.shape

    if K <= target_k:
        return {
            'means': means.clone(),
            'logstds': logstds.clone(),
            'logweights': logweights.clone(),
        }

    all_means = []
    all_logweights = []

    for b in range(bs):
        m = means[b].clone()  # (K, D)
        w = logweights[b, :, 0].softmax(dim=0).clone()  # (K,)

        n = K
        while n > target_k:
            # Pairwise squared distances
            diff = m.unsqueeze(0) - m.unsqueeze(1)  # (n, n, D)
            dist_sq = diff.square().sum(dim=-1)  # (n, n)

            # Merge cost: w_i * w_j / (w_i + w_j) * ||m_i - m_j||^2
            wi = w.unsqueeze(1)  # (n, 1)
            wj = w.unsqueeze(0)  # (1, n)
            costs = (wi * wj / (wi + wj)) * dist_sq  # (n, n)
            costs.fill_diagonal_(float('inf'))

            # Find minimum cost pair
            idx = costs.argmin().item()
            i = idx // n
            j = idx % n

            # Ensure i < j for consistent removal
            if i > j:
                i, j = j, i

            # Merge: weighted average mean, summed weight
            new_w = w[i] + w[j]
            new_m = (w[i] * m[i] + w[j] * m[j]) / new_w

            m[i] = new_m
            w[i] = new_w

            # Remove component j
            keep = torch.ones(n, dtype=torch.bool)
            keep[j] = False
            m = m[keep]
            w = w[keep]
            n -= 1

        all_means.append(m)
        all_logweights.append(w.log())

    out_means = torch.stack(all_means)  # (bs, target_k, D)
    out_lw = torch.stack(all_logweights).unsqueeze(-1)  # (bs, target_k, 1)
    out_lw = out_lw.log_softmax(dim=1)  # normalize

    return {
        'means': out_means,
        'logstds': logstds,
        'logweights': out_lw,
    }
