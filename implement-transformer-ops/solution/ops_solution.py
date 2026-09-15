"""
Reference implementation of ops.py for the custom transformer.

"""

import math
import torch


def log_softmax(x, dim=-1):
    """Numerically stable log-softmax."""
    max_val = x.max(dim=dim, keepdim=True).values
    shifted = x - max_val
    return shifted - torch.log(torch.exp(shifted).sum(dim=dim, keepdim=True))


def rms_norm(x, gain, eps=1e-6):
    """RMS normalization: x / sqrt(mean(x^2) + eps) * gain.

    No mean centering, no bias.
    """
    rms = torch.sqrt((x * x).mean(dim=-1, keepdim=True) + eps)
    return (x / rms) * gain


def scaled_dot_attention(Q, K, V, mask=None, tau=1.0):
    """Scaled dot-product attention with explicit temperature tau."""
    scores = torch.matmul(Q, K.transpose(-2, -1)) / tau
    if mask is not None:
        scores = scores.masked_fill(~mask, -1e9)
    weights = torch.exp(scores - scores.max(dim=-1, keepdim=True).values)
    weights = weights / weights.sum(dim=-1, keepdim=True)
    return torch.matmul(weights, V)


def sinusoidal_pe(max_len, d_model, base=10000.0):
    """Sinusoidal positional encoding with configurable frequency base."""
    pe = torch.zeros(max_len, d_model)
    pos = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
    div = torch.exp(
        torch.arange(0, d_model, 2, dtype=torch.float)
        * -(math.log(base) / d_model)
    )
    pe[:, 0::2] = torch.sin(pos * div)
    pe[:, 1::2] = torch.cos(pos * div)
    return pe


def make_causal_mask(size, window=0):
    """Causal mask with optional sliding window.

    window <= 0: full lower-triangular.
    window >  0: each position attends only to the previous *window*
                 positions (including itself).

    Returns bool tensor of shape (1, 1, size, size).
    """
    rows = torch.arange(size).unsqueeze(1)
    cols = torch.arange(size).unsqueeze(0)
    if window <= 0:
        mask = cols <= rows
    else:
        mask = (cols <= rows) & (cols >= rows - window + 1)
    return mask.unsqueeze(0).unsqueeze(0)


def compute_loss(logits, targets, pad_idx, smooth_eps):
    """Cross-entropy with label smoothing (pad-excluded distribution).

    Smoothing mass is spread uniformly over non-pad classes only.
    Pad positions in *targets* are excluded from the loss.
    """
    vocab_size = logits.size(-1)
    lp = log_softmax(logits, dim=-1)

    non_pad = (targets != pad_idx).float()
    n_tokens = non_pad.sum().clamp(min=1)

    nll = -lp.gather(-1, targets.clamp(min=0).unsqueeze(-1)).squeeze(-1)

    # smooth component: average −log p over non-pad classes
    smooth_lp = lp.clone()
    smooth_lp[..., pad_idx] = 0
    smooth = -smooth_lp.sum(-1) / (vocab_size - 1)

    per_token = (1.0 - smooth_eps) * nll + smooth_eps * smooth
    return (per_token * non_pad).sum() / n_tokens
