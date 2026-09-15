"""
Score Function Engine for Gaussian Mixtures — Corrected Implementation.

"""
import torch
import math
from gm_ops import gm_log_prob, gm_sample


def gm_score_naive(gm, x, eps=1e-4):
    """Compute the score function of a GM distribution.

    WARNING: This implementation has a numerical stability defect.
    It produces NaN when x is far from all component means because the
    Gaussian densities underflow to zero in floating-point arithmetic,
    causing a 0/0 division in the responsibility computation.

    Args:
        gm: dict with 'means' (B,K,D), 'logstds' (B,1,1), 'logweights' (B,K)
        x: (B, D) evaluation points

    Returns:
        (B, D) score vectors
    """
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    sigma_sq = (2 * logstds.squeeze(-1)).exp()  # (B, 1)
    weights = torch.softmax(logweights, dim=-1)  # (B, K)

    diff = x.unsqueeze(1) - means  # (B, K, D)

    stds = logstds.squeeze(-1).exp()  # (B, 1)
    gauss = torch.exp(-0.5 * (diff / stds.unsqueeze(-1)).square().sum(dim=-1))  # (B, K)

    unnorm = weights * gauss  # (B, K)
    resp = unnorm / unnorm.sum(dim=-1, keepdim=True)

    comp_scores = -diff / sigma_sq.unsqueeze(-1)  # (B, K, D)
    score = (resp.unsqueeze(-1) * comp_scores).sum(dim=1)  # (B, D)
    return score


def _compute_responsibilities(gm, x):
    """Compute responsibilities and intermediate quantities in log space.

    Returns responsibilities (B, K), diffs (B, K, D), and sigma_sq (B, 1),
    all computed stably in log space to avoid underflow.
    """
    means = gm['means']        # (B, K, D)
    logstds = gm['logstds']    # (B, 1, 1)
    logweights = gm['logweights']  # (B, K)

    sigma_sq = (2 * logstds.squeeze(-1)).exp()  # (B, 1)
    diff = x.unsqueeze(1) - means  # (B, K, D)

    # Log Gaussian densities (unnormalized — constants cancel in responsibilities)
    log_gauss = -0.5 * (diff ** 2).sum(dim=-1) / sigma_sq  # (B, K)

    # Log responsibilities via log-sum-exp
    log_w = logweights - torch.logsumexp(logweights, dim=-1, keepdim=True)  # (B, K)
    log_resp = log_w + log_gauss  # (B, K)
    log_resp = log_resp - torch.logsumexp(log_resp, dim=-1, keepdim=True)  # (B, K)

    resp = log_resp.exp()  # (B, K) — safe because log-normalized via logsumexp

    return resp, diff, sigma_sq


def gm_score(gm, x, eps=1e-8):
    """Compute the score function of a GM distribution — numerically stable version.

    Uses log-space computation for responsibilities to avoid underflow in tails.

    s(x) = sum_k psi_k(x) * s_k(x)
    where s_k(x) = -(x - mu_k) / sigma^2

    Args:
        gm: dict with 'means' (B,K,D), 'logstds' (B,1,1), 'logweights' (B,K)
        x: (B, D) evaluation points

    Returns:
        (B, D) score vectors — always finite for valid inputs
    """
    resp, diff, sigma_sq = _compute_responsibilities(gm, x)

    # Per-component scores: s_k = -(x - mu_k) / sigma^2
    comp_scores = -diff / sigma_sq.unsqueeze(-1)  # (B, K, D)

    # Responsibility-weighted sum
    score = (resp.unsqueeze(-1) * comp_scores).sum(dim=1)  # (B, D)
    return score


def gm_score_divergence(gm, x, eps=1e-8):
    """Compute the divergence of the score: div(s) = Tr(Hessian of log p).

    div(s) = sum_k psi_k ||s_k||^2 - ||s||^2 - D / sigma^2

    Args:
        gm: dict with 'means' (B,K,D), 'logstds' (B,1,1), 'logweights' (B,K)
        x: (B, D) evaluation points

    Returns:
        (B,) divergence values
    """
    resp, diff, sigma_sq = _compute_responsibilities(gm, x)
    D = diff.shape[-1]

    # Per-component scores
    comp_scores = -diff / sigma_sq.unsqueeze(-1)  # (B, K, D)

    # E_psi[||s_k||^2] = sum_k psi_k * ||s_k||^2
    comp_score_sq_norms = (comp_scores ** 2).sum(dim=-1)  # (B, K)
    E_sq = (resp * comp_score_sq_norms).sum(dim=-1)  # (B,)

    # ||score||^2
    score = (resp.unsqueeze(-1) * comp_scores).sum(dim=1)  # (B, D)
    score_sq_norm = (score ** 2).sum(dim=-1)  # (B,)

    # div(s) = E[||s_k||^2] - ||s||^2 - D/sigma^2
    div_s = E_sq - score_sq_norm - (D / sigma_sq).squeeze(-1)  # (B,)
    return div_s


def gm_kernel_stein_discrepancy(gm, samples, bandwidth=None, score_fn=None):
    """Compute the kernel Stein discrepancy (KSD) between a GM density and samples.

    Uses the IMQ kernel: k(x,y) = (c^2 + ||x-y||^2)^{-1/2}.
    If bandwidth is None, c^2 is set via the median heuristic.

    KSD^2(p, q_n) = (1/n^2) sum_{i,j} u_p(x_i, x_j)

    Args:
        gm: dict defining the GM distribution p
        samples: (B, N, D) samples from distribution q
        bandwidth: float or None (median heuristic if None)
        score_fn: callable (defaults to gm_score)

    Returns:
        (B,) KSD^2 values
    """
    if score_fn is None:
        score_fn = gm_score

    B, N, D = samples.shape
    K = gm['means'].shape[1]

    # Compute scores at all sample points by flattening B*N into batch dim
    gm_flat = {
        'means': gm['means'].unsqueeze(1).expand(B, N, K, D).reshape(B * N, K, D),
        'logstds': gm['logstds'].unsqueeze(1).expand(B, N, 1, 1).reshape(B * N, 1, 1),
        'logweights': gm['logweights'].unsqueeze(1).expand(B, N, K).reshape(B * N, K),
    }
    x_flat = samples.reshape(B * N, D)
    scores = score_fn(gm_flat, x_flat).reshape(B, N, D)  # (B, N, D)

    # Pairwise differences and squared distances
    diff = samples.unsqueeze(2) - samples.unsqueeze(1)  # (B, N, N, D)
    r_sq = (diff ** 2).sum(dim=-1)  # (B, N, N)

    # Bandwidth via median heuristic
    if bandwidth is None:
        triu_mask = torch.triu(torch.ones(N, N, dtype=torch.bool, device=samples.device),
                               diagonal=1)
        pairwise_sq = r_sq[:, triu_mask]  # (B, N*(N-1)/2)
        c_sq = pairwise_sq.median(dim=-1)[0]  # (B,)
        c_sq = c_sq.reshape(B, 1, 1).clamp(min=1e-8)
    else:
        c_sq = torch.tensor(bandwidth ** 2, dtype=samples.dtype, device=samples.device)

    # IMQ kernel: k(x,y) = (c^2 + r^2)^{-1/2}
    base = c_sq + r_sq  # (B, N, N)
    k_val = base.pow(-0.5)  # (B, N, N)

    # Kernel gradients
    # grad_x k = -(c^2+r^2)^{-3/2} (x-y)
    coeff_grad = -base.pow(-1.5)  # (B, N, N)
    grad_k_x = coeff_grad.unsqueeze(-1) * diff  # (B, N, N, D)
    grad_k_y = -grad_k_x  # (B, N, N, D)

    # Trace of Hessian: Tr(grad_x grad_y k) = D(c^2+r^2)^{-3/2} - 3 r^2 (c^2+r^2)^{-5/2}
    trace_hess = D * base.pow(-1.5) - 3 * r_sq * base.pow(-2.5)  # (B, N, N)

    # Build the Stein kernel u_p(x_i, x_j)
    s_x = scores.unsqueeze(2)  # (B, N, 1, D)
    s_y = scores.unsqueeze(1)  # (B, 1, N, D)

    # Term 1: s(x)^T s(y) k(x,y)
    term1 = (s_x * s_y).sum(dim=-1) * k_val  # (B, N, N)

    # Term 2: s(x)^T grad_y k(x,y)
    term2 = (s_x * grad_k_y).sum(dim=-1)  # (B, N, N)

    # Term 3: s(y)^T grad_x k(x,y)
    term3 = (s_y * grad_k_x).sum(dim=-1)  # (B, N, N)

    # u_p = term1 + term2 + term3 + trace_hess
    u_p = term1 + term2 + term3 + trace_hess  # (B, N, N)

    # KSD^2 = mean over (i, j) pairs
    ksd_sq = u_p.mean(dim=(-2, -1))  # (B,)

    return ksd_sq
