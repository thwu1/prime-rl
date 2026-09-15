"""
Gaussian Mixture Distribution Operations Library.

Provides core operations on Gaussian mixture distributions represented as:
    means:      (B, K, D)  component means
    logstds:    (B, 1, 1)  shared isotropic log-standard-deviation
    logweights: (B, K)     unnormalized log-mixture-weights
"""
import torch
import math


def gm_nll_loss(gm, sample, eps=1e-4):
    """Gaussian mixture negative log-likelihood (without normalization constant)."""
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    inverse_stds = torch.exp(-logstds).clamp(max=1 / eps)
    diff_weighted = (sample.unsqueeze(1) - means) * inverse_stds
    gaussian_ll = (-0.5 * diff_weighted.square() - logstds).sum(dim=-1)
    log_mix_weights = logweights - torch.logsumexp(logweights, dim=-1, keepdim=True)
    nll = -torch.logsumexp(gaussian_ll + log_mix_weights, dim=-1)
    return nll


def gm_log_prob(gm, samples, eps=1e-4):
    """Full log-probability of samples under the Gaussian mixture.

    Includes complete normalization: -D*logstd and -(D/2)*log(2*pi).

    Args:
        gm: dict with means (B,K,D), logstds (B,1,1), logweights (B,K)
        samples: (B, N, D) sample points

    Returns:
        (B, N) log-probabilities
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']
    D = means.shape[-1]

    inverse_stds = torch.exp(-logstds).clamp(max=1 / eps)

    diff = samples.unsqueeze(2) - means.unsqueeze(1)
    diff_weighted = diff * inverse_stds.unsqueeze(1)

    gaussian_ll = (-0.5 * diff_weighted.square() - logstds.unsqueeze(1)).sum(dim=-1)
    gaussian_ll = gaussian_ll - 0.5 * D * math.log(2 * math.pi)

    log_mix_weights = logweights - torch.logsumexp(logweights, dim=-1, keepdim=True)
    log_prob = torch.logsumexp(gaussian_ll + log_mix_weights.unsqueeze(1), dim=-1)
    return log_prob


def gm_moment_match(gm):
    """Moment-match a Gaussian mixture to a single isotropic Gaussian.

    Uses the law of total variance: Var = within_var + between_var.
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    weights = torch.softmax(logweights, dim=-1)
    mean = (weights.unsqueeze(-1) * means).sum(dim=1)

    within_var = (logstds.squeeze(-1).squeeze(-1) * 2).exp()

    diffs = means - mean.unsqueeze(1)
    between_var = (weights.unsqueeze(-1) * diffs.square()).sum(dim=1).mean(dim=-1)

    var = within_var + between_var
    return {'mean': mean, 'var': var}


def gm_bayesian_update(gm, obs, obs_logvar):
    """Compute the posterior Gaussian mixture after a Gaussian observation.

    posterior proportional to N(y; x, tau^2 I) * sum_k w_k N(x; mu_k, sigma^2 I)
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    prior_var = (logstds.squeeze(-1).squeeze(-1) * 2).exp()
    obs_var = obs_logvar.exp()

    post_var = prior_var * obs_var / (prior_var + obs_var)
    post_logstd = 0.5 * torch.log(post_var)

    post_means = post_var[:, None, None] * (
        means / prior_var[:, None, None] + obs.unsqueeze(1) / obs_var[:, None, None]
    )

    diff = means - obs.unsqueeze(1)
    logweight_delta = -0.5 * diff.square().sum(dim=-1) / (prior_var + obs_var)[:, None]
    post_logweights = logweights + logweight_delta

    return {
        'means': post_means,
        'logstds': post_logstd[:, None, None],
        'logweights': post_logweights,
    }


def gm_sample(gm, n_samples):
    """Draw samples from the Gaussian mixture.

    Args:
        gm: dict with means (B,K,D), logstds (B,1,1), logweights (B,K)
        n_samples: number of samples to draw

    Returns:
        (B, n_samples, D) samples
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']
    B, K, D = means.shape

    weights = torch.softmax(logweights, dim=-1)
    indices = torch.multinomial(weights.float(), n_samples, replacement=True)

    selected_means = torch.gather(
        means, 1, indices.unsqueeze(-1).expand(B, n_samples, D)
    )

    stds = logstds.squeeze(-1).squeeze(-1).exp()
    noise = torch.randn(B, n_samples, D, device=means.device, dtype=means.dtype)
    samples = selected_means + stds[:, None, None] * noise

    return samples


def gm_kl_div(gm_p, gm_q, n_samples=1000):
    """Monte Carlo estimate of KL(p || q) between two Gaussian mixtures."""
    samples = gm_sample(gm_p, n_samples)
    log_p = gm_log_prob(gm_p, samples)
    log_q = gm_log_prob(gm_q, samples)
    kl = (log_p - log_q).mean(dim=-1)
    return kl
