"""
Reference solution for transformer_ops.py

"""

import math
import torch
from typing import Optional, Tuple


def softmax(x: torch.Tensor, dim: int = -1) -> torch.Tensor:
    """Numerically stable softmax."""
    x_max = x.max(dim=dim, keepdim=True)[0]
    e_x = torch.exp(x - x_max)
    return e_x / e_x.sum(dim=dim, keepdim=True)


def attention(
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    mask: Optional[torch.Tensor] = None,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """Scaled Dot-Product Attention."""
    d_k = query.size(-1)
    scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(d_k)
    if mask is not None:
        scores = scores.masked_fill(mask == 0, -1e9)
    p_attn = softmax(scores, dim=-1)
    return torch.matmul(p_attn, value), p_attn


def layer_norm(
    x: torch.Tensor,
    weight: torch.Tensor,
    bias: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Layer Normalization (population variance, no Bessel correction)."""
    mean = x.mean(-1, keepdim=True)
    var = ((x - mean) ** 2).mean(-1, keepdim=True)
    return weight * (x - mean) / torch.sqrt(var + eps) + bias


def positional_encoding(d_model: int, max_len: int) -> torch.Tensor:
    """Sinusoidal positional encoding."""
    pe = torch.zeros(max_len, d_model)
    position = torch.arange(0, max_len).unsqueeze(1).float()
    div_term = torch.exp(
        torch.arange(0, d_model, 2).float() * -(math.log(10000.0) / d_model)
    )
    pe[:, 0::2] = torch.sin(position * div_term)
    pe[:, 1::2] = torch.cos(position * div_term)
    return pe


def subsequent_mask(size: int) -> torch.Tensor:
    """Causal (lower-triangular) attention mask."""
    mask = torch.triu(torch.ones(size, size), diagonal=1) == 0
    return mask.unsqueeze(0)


def label_smoothing_loss(
    x: torch.Tensor,
    target: torch.LongTensor,
    smoothing: float,
    pad_idx: int,
) -> torch.Tensor:
    """Label-smoothed cross-entropy via KL divergence."""
    vocab_size = x.size(-1)

    # Numerically stable log-softmax
    log_probs = x - x.max(dim=-1, keepdim=True)[0]
    log_probs = log_probs - torch.log(
        torch.exp(log_probs).sum(dim=-1, keepdim=True)
    )

    # Build smooth target distribution (detached from graph)
    with torch.no_grad():
        true_dist = torch.full_like(x, smoothing / (vocab_size - 2))
        true_dist.scatter_(1, target.unsqueeze(1), 1.0 - smoothing)
        true_dist[:, pad_idx] = 0
        pad_mask = target == pad_idx
        true_dist[pad_mask] = 0

    # Per-position KL-divergence loss
    loss = -(true_dist * log_probs).sum(dim=-1)

    # Normalise by non-padding token count
    n_tokens = (~pad_mask).sum()
    if n_tokens == 0:
        return (loss * 0).sum()
    return loss.sum() / n_tokens


def lr_rate(step: int, d_model: int, factor: float, warmup: int) -> float:
    """Noam learning rate schedule."""
    if step == 0:
        step = 1
    return factor * (
        d_model ** (-0.5) * min(step ** (-0.5), step * warmup ** (-1.5))
    )
