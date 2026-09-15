
"""
Utility modules for MLA+DSA implementation.
These are provided as building blocks — do not modify.
"""

import torch
import torch.nn as nn


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, hidden_size, eps=1e-5):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.eps = eps

    def forward(self, x):
        input_dtype = x.dtype
        x = x.float()
        variance = x.pow(2).mean(-1, keepdim=True)
        x = x * torch.rsqrt(variance + self.eps)
        return (self.weight * x).to(input_dtype)


def _rotate_half(x):
    """Rotate the second half of the last dimension and negate."""
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(x, cos, sin):
    """
    Apply rotary position embedding to tensor x.

    Args:
        x: tensor with last dimension = rope_dim.
           Supports shapes [B, S, rope_dim] and [B, S, H, rope_dim].
        cos: [B, S, rope_dim] cosine embeddings
        sin: [B, S, rope_dim] sine embeddings

    Returns:
        Rotated tensor with same shape as x.
    """
    if x.dim() == 4 and cos.dim() == 3:
        cos = cos.unsqueeze(2)
        sin = sin.unsqueeze(2)
    return x * cos + _rotate_half(x) * sin


def compute_rope_embeddings(position_ids, config):
    """
    Compute RoPE cos/sin embeddings for given position IDs.

    Args:
        position_ids: [B, S] integer tensor of absolute positions
        config: model configuration dict

    Returns:
        cos: [B, S, qk_rope_head_dim] cosine embeddings
        sin: [B, S, qk_rope_head_dim] sine embeddings
    """
    dim = config["qk_rope_head_dim"]
    theta = config["rope_theta"]

    inv_freq = 1.0 / (theta ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    freqs = torch.einsum("bs,d->bsd", position_ids.float(), inv_freq)
    emb = torch.cat([freqs, freqs], dim=-1)
    return emb.cos(), emb.sin()


def make_causal_mask(seq_len, past_len, dtype, device):
    """
    Build a causal attention mask.

    Args:
        seq_len: number of new tokens being processed
        past_len: number of previously cached tokens
        dtype: tensor dtype (use float or the model dtype)
        device: tensor device

    Returns:
        mask: [1, 1, seq_len, past_len + seq_len]
              0.0 where attention is allowed, -inf where blocked.
    """
    total_len = past_len + seq_len
    rows = torch.arange(seq_len, device=device).unsqueeze(1) + past_len
    cols = torch.arange(total_len, device=device).unsqueeze(0)
    causal = cols <= rows
    mask = torch.where(
        causal,
        torch.tensor(0.0, dtype=dtype, device=device),
        torch.tensor(float("-inf"), dtype=dtype, device=device),
    )
    return mask.unsqueeze(0).unsqueeze(0)
