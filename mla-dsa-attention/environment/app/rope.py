"""Rotary Position Embedding (RoPE) utilities."""

import torch
import torch.nn as nn


def rotate_half(x):
    """Rotates half the hidden dims of the input."""
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(x, cos, sin, unsqueeze_dim=1):
    """Apply rotary position embedding to a single tensor.

    unsqueeze_dim=1 for [B, H, S, D] layout, =2 for [B, S, H, D] layout.
    """
    cos = cos.unsqueeze(unsqueeze_dim)
    sin = sin.unsqueeze(unsqueeze_dim)
    return (x * cos) + (rotate_half(x) * sin)


class RotaryEmbedding(nn.Module):
    """Precomputes inverse frequencies; returns (cos, sin) per forward call."""

    def __init__(self, dim, max_position_embeddings=131072, theta=10000.0):
        super().__init__()
        inv_freq = 1.0 / (
            theta ** (torch.arange(0, dim, 2).float() / dim)
        )
        self.register_buffer("inv_freq", inv_freq, persistent=False)

    def forward(self, position_ids):
        """
        Args:
            position_ids: [B, S] — integer position indices

        Returns:
            cos: [B, S, dim]
            sin: [B, S, dim]
        """
        inv_freq_expanded = self.inv_freq[None, :, None].expand(
            position_ids.shape[0], -1, 1
        )
        position_ids_expanded = position_ids[:, None, :].float()
        freqs = (
            inv_freq_expanded.float() @ position_ids_expanded.float()
        ).transpose(1, 2)
        emb = torch.cat((freqs, freqs), dim=-1)
        return emb.cos(), emb.sin()
