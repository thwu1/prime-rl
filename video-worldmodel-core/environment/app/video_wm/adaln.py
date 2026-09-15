"""
Adaptive Layer Normalization (AdaLN) for Diffusion Transformers.

Implements RMS normalization and the 6-way modulation scheme used in
Wan-style transformer blocks.

See SPEC.md Section 5 for mathematical specification and invariants.
"""

import torch


def rms_norm(x: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """Apply RMS (Root Mean Square) normalization.

    RMSNorm(x) = x / sqrt(mean(x^2, dim=-1) + eps)

    Args:
        x: Input tensor. Normalization is applied over the last dimension.
        eps: Small constant for numerical stability.

    Returns:
        Normalized tensor of same shape.
    """
    raise NotImplementedError("Implement rms_norm")


def compute_adaln_modulation(
    scale_shift_table: torch.Tensor,
    temb: torch.Tensor,
) -> tuple:
    """Compute AdaLN modulation vectors from scale-shift table and timestep embedding.

    Args:
        scale_shift_table: Learnable table of shape (1, 6, dim).
        temb: Timestep embedding of shape (batch, 6 * dim).

    Returns:
        Tuple of 6 tensors (shift, scale, gate, c_shift, c_scale, c_gate),
        each of shape (batch, 1, dim).
    """
    raise NotImplementedError("Implement compute_adaln_modulation")


def apply_adaln_modulation(
    x: torch.Tensor,
    shift: torch.Tensor,
    scale: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Apply AdaLN modulation to input tensor.

    Three sequential operations:
    1. RMS normalization
    2. Multiplicative scaling (with identity offset: zero scale = no change)
    3. Additive shifting (added after scaling)

    Derive the formula from the invariants in SPEC.md Section 5.3.

    Args:
        x: Input tensor of shape (batch, seq_len, dim).
        shift: Shift vector of shape (batch, 1, dim).
        scale: Scale vector of shape (batch, 1, dim).
        eps: Epsilon for RMS normalization.

    Returns:
        Modulated tensor of shape (batch, seq_len, dim).
    """
    raise NotImplementedError("Implement apply_adaln_modulation")
