"""
Utility modules for the GLM-5 MLA implementation.

Provides RMSNorm, RotaryEmbedding, and causal mask construction.

"""

import torch
import torch.nn as nn


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, hidden_size: int, eps: float = 1e-5):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        variance = x.float().pow(2).mean(-1, keepdim=True)
        x = x * torch.rsqrt(variance + self.eps)
        return self.weight * x.to(self.weight.dtype)


class RotaryEmbedding(nn.Module):
    """Rotary Position Embedding (RoPE)."""

    def __init__(self, dim: int, base: float = 10000.0):
        super().__init__()
        inv_freq = 1.0 / (
            base ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim)
        )
        self.register_buffer("inv_freq", inv_freq, persistent=False)

    def forward(
        self, x: torch.Tensor, position_ids: torch.Tensor = None
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            x: [B, S, ...] tensor (used only for device/dtype inference)
            position_ids: [B, S] integer positions (auto-generated if None)

        Returns:
            (cos, sin) each of shape [B, S, dim]
        """
        if position_ids is None:
            seq_len = x.shape[1]
            position_ids = torch.arange(seq_len, device=x.device).unsqueeze(0)

        # [B, S, dim/2]
        freqs = torch.einsum(
            "bi,j->bij", position_ids.float(), self.inv_freq.to(x.device)
        )
        # [B, S, dim]  — duplicate for rotation formula
        emb = torch.cat([freqs, freqs], dim=-1)
        return emb.cos(), emb.sin()


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    """Swap and negate the two halves of the last dimension."""
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(
    x: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
    unsqueeze_dim: int = 2,
) -> torch.Tensor:
    """
    Apply rotary position embeddings.

    Args:
        x: tensor whose last dim matches the RoPE dimension
        cos: [B, S, dim] cosine embeddings
        sin: [B, S, dim] sine embeddings
        unsqueeze_dim: axis to insert a size-1 dimension in cos/sin for
                       broadcasting (typically 2 to broadcast over heads)
    """
    cos = cos.unsqueeze(unsqueeze_dim)
    sin = sin.unsqueeze(unsqueeze_dim)
    return (x * cos) + (rotate_half(x) * sin)


def make_causal_mask(
    seq_len: int, total_len: int, dtype: torch.dtype, device: torch.device
) -> torch.Tensor:
    """
    Build a causal attention mask.

    Returns:
        [1, 1, seq_len, total_len] where 0 = attend, -inf = masked
    """
    rows = torch.arange(seq_len, device=device).unsqueeze(1)
    cols = torch.arange(total_len, device=device).unsqueeze(0)
    past_len = total_len - seq_len
    causal = cols <= (rows + past_len)
    mask = torch.where(causal, 0.0, torch.finfo(dtype).min)
    return mask.unsqueeze(0).unsqueeze(0).to(dtype)
