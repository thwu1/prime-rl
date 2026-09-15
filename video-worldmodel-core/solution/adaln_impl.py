"""
Adaptive Layer Normalization (AdaLN) - Implementation.
"""

import torch


def rms_norm(x: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    rms = torch.sqrt(torch.mean(x ** 2, dim=-1, keepdim=True) + eps)
    return x / rms


def compute_adaln_modulation(
    scale_shift_table: torch.Tensor,
    temb: torch.Tensor,
) -> tuple:
    batch = temb.shape[0]
    dim = scale_shift_table.shape[2]

    # Reshape temb: (batch, 6*dim) -> (batch, 6, dim)
    temb_reshaped = temb.reshape(batch, 6, dim)

    # Add scale_shift_table (broadcasts over batch): (batch, 6, dim)
    combined = scale_shift_table + temb_reshaped

    # Split into 6 parts along dim 1, each (batch, 1, dim)
    parts = combined.chunk(6, dim=1)

    return parts


def apply_adaln_modulation(
    x: torch.Tensor,
    shift: torch.Tensor,
    scale: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    x_normed = rms_norm(x, eps)
    return x_normed * (1.0 + scale) + shift
