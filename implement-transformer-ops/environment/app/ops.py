"""
Primitive operations for the custom transformer model.

Every function raises NotImplementedError. Implement them using only
basic PyTorch tensor operations (no torch.nn, no torch.nn.functional).

"""
import torch


def log_softmax(x: torch.Tensor, dim: int = -1) -> torch.Tensor:
    """Numerically stable log-softmax along the given dimension."""
    raise NotImplementedError


def rms_norm(
    x: torch.Tensor, gain: torch.Tensor, eps: float = 1e-6
) -> torch.Tensor:
    """Root Mean Square Layer Normalization.

    Normalize by 1/RMS(x) then scale by gain.  No mean centering, no bias.
    """
    raise NotImplementedError


def scaled_dot_attention(
    Q: torch.Tensor,
    K: torch.Tensor,
    V: torch.Tensor,
    mask: torch.Tensor = None,
    tau: float = 1.0,
) -> torch.Tensor:
    """Scaled dot-product attention with explicit temperature *tau*.

    scores = (Q @ K^T) / tau   then masked-fill, softmax, @ V.
    Returns the attention output only (no weights).
    """
    raise NotImplementedError


def sinusoidal_pe(
    max_len: int, d_model: int, base: float = 10000.0
) -> torch.Tensor:
    """Sinusoidal positional encoding with configurable frequency base.

    PE(pos, 2i)   = sin(pos / base^(2i / d_model))
    PE(pos, 2i+1) = cos(pos / base^(2i / d_model))

    Returns a (max_len, d_model) tensor with no gradient.
    """
    raise NotImplementedError


def make_causal_mask(size: int, window: int = 0) -> torch.Tensor:
    """Causal attention mask with optional sliding window.

    window <= 0 : standard lower-triangular causal mask.
    window >  0 : each position attends only to the previous *window*
                  positions (including itself).

    Returns a bool tensor of shape (1, 1, size, size).
    """
    raise NotImplementedError


def compute_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
    pad_idx: int,
    smooth_eps: float,
) -> torch.Tensor:
    """Cross-entropy loss with label smoothing.

    Smoothing mass is distributed uniformly over non-pad classes only.
    Pad positions in *targets* are excluded from the loss.
    """
    raise NotImplementedError
