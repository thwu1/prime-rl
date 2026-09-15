"""
3D Rotary Position Embeddings - Implementation.
"""

import torch
import math


def get_dimension_split(attention_head_dim: int) -> tuple[int, int, int]:
    h_dim = 2 * (attention_head_dim // 6)
    w_dim = 2 * (attention_head_dim // 6)
    t_dim = attention_head_dim - h_dim - w_dim
    return t_dim, h_dim, w_dim


def compute_3d_rotary_embeddings(
    attention_head_dim: int,
    seq_len_t: int,
    seq_len_h: int,
    seq_len_w: int,
    theta: float = 10000.0,
) -> tuple[torch.Tensor, torch.Tensor]:
    t_dim, h_dim, w_dim = get_dimension_split(attention_head_dim)

    # Compute frequency bands using float64 for precision
    freqs_t = 1.0 / (theta ** (torch.arange(0, t_dim, 2, dtype=torch.float64) / t_dim))
    freqs_h = 1.0 / (theta ** (torch.arange(0, h_dim, 2, dtype=torch.float64) / h_dim))
    freqs_w = 1.0 / (theta ** (torch.arange(0, w_dim, 2, dtype=torch.float64) / w_dim))

    # Compute position grids
    grid_t = torch.arange(seq_len_t, dtype=torch.float64)
    grid_h = torch.arange(seq_len_h, dtype=torch.float64)
    grid_w = torch.arange(seq_len_w, dtype=torch.float64)

    # Outer products: position x frequency
    angles_t = torch.outer(grid_t, freqs_t)  # (T, t_dim//2)
    angles_h = torch.outer(grid_h, freqs_h)  # (H, h_dim//2)
    angles_w = torch.outer(grid_w, freqs_w)  # (W, w_dim//2)

    # Expand each to full 3D grid
    angles_t = angles_t[:, None, None, :].expand(-1, seq_len_h, seq_len_w, -1)
    angles_h = angles_h[None, :, None, :].expand(seq_len_t, -1, seq_len_w, -1)
    angles_w = angles_w[None, None, :, :].expand(seq_len_t, seq_len_h, -1, -1)

    # Concatenate [temporal, height, width] and flatten spatial dims
    angles = torch.cat([angles_t, angles_h, angles_w], dim=-1)
    angles = angles.reshape(-1, angles.shape[-1])

    return angles.cos().float(), angles.sin().float()


def apply_rotary_emb(
    x: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
) -> torch.Tensor:
    seq_len = x.shape[2]

    # Slice to match sequence length
    cos = cos[:seq_len]  # (seq_len, head_dim//2)
    sin = sin[:seq_len]

    # Split into interleaved even/odd pairs
    x1 = x[..., 0::2]  # (batch, heads, seq_len, head_dim//2)
    x2 = x[..., 1::2]

    # Broadcast cos/sin: (1, 1, seq_len, head_dim//2)
    cos_bc = cos.unsqueeze(0).unsqueeze(0)
    sin_bc = sin.unsqueeze(0).unsqueeze(0)

    # Apply rotation
    out = torch.empty_like(x)
    out[..., 0::2] = x1 * cos_bc - x2 * sin_bc
    out[..., 1::2] = x1 * sin_bc + x2 * cos_bc

    return out
