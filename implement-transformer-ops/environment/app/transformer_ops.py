"""
Core transformer operations.

All functions must be implemented from elementary tensor operations
(arithmetic, exp, log, matmul, indexing, etc.). Do not delegate to
prebuilt activation functions, normalization layers, attention modules,
or loss functions from PyTorch's neural network libraries.
"""

import math
import torch
from typing import Optional, Tuple


def softmax(x: torch.Tensor, dim: int = -1) -> torch.Tensor:
    """Softmax activation."""
    raise NotImplementedError


def attention(
    query: torch.Tensor,
    key: torch.Tensor,
    value: torch.Tensor,
    mask: Optional[torch.Tensor] = None,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """Scaled dot-product attention. Returns (output, attention_weights)."""
    raise NotImplementedError


def layer_norm(
    x: torch.Tensor,
    weight: torch.Tensor,
    bias: torch.Tensor,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Layer normalization over the last dimension."""
    raise NotImplementedError


def positional_encoding(d_model: int, max_len: int) -> torch.Tensor:
    """Sinusoidal positional encoding table of shape (max_len, d_model)."""
    raise NotImplementedError


def subsequent_mask(size: int) -> torch.Tensor:
    """Causal mask for autoregressive decoding."""
    raise NotImplementedError


def label_smoothing_loss(
    x: torch.Tensor,
    target: torch.LongTensor,
    smoothing: float,
    pad_idx: int,
) -> torch.Tensor:
    """Cross-entropy loss with label smoothing."""
    raise NotImplementedError


def lr_rate(step: int, d_model: int, factor: float, warmup: int) -> float:
    """Learning rate for the given training step."""
    raise NotImplementedError
