"""
Transformer Language Model — Implementation Skeleton

Implement all functions and classes below using only:
- torch.Tensor operations
- torch.nn.Parameter, torch.nn.Module, torch.nn.ModuleList
- torch.optim.Optimizer (base class only)

Forbidden: torch.nn.functional, torch.nn.Linear, torch.nn.Embedding,
torch.nn.LayerNorm, torch.nn.RMSNorm, any pre-built optimizer class.
"""

import math
from typing import Iterable

import torch
import torch.nn as nn
from torch import Tensor


def softmax(x: Tensor, dim: int) -> Tensor:
    """Compute softmax along the given dimension."""
    raise NotImplementedError


def cross_entropy(logits: Tensor, targets: Tensor) -> Tensor:
    """Compute mean cross-entropy loss.

    Args:
        logits: (N, C) unnormalized scores.
        targets: (N,) integer class labels in [0, C).
    Returns:
        Scalar mean loss.
    """
    raise NotImplementedError


def silu(x: Tensor) -> Tensor:
    """SiLU activation function."""
    raise NotImplementedError


def rms_norm(x: Tensor, weight: Tensor, eps: float = 1e-5) -> Tensor:
    """Root mean square layer normalization along the last dimension."""
    raise NotImplementedError


def rope(x: Tensor, positions: Tensor, theta: float, d_k: int) -> Tensor:
    """Apply rotary position embeddings.

    Args:
        x: (..., d_k) input tensor.
        positions: Integer positions, broadcastable with x's leading dims.
        theta: Base frequency parameter.
        d_k: Head dimension (must be even).
    """
    raise NotImplementedError


def scaled_dot_product_attention(
    Q: Tensor, K: Tensor, V: Tensor, mask: Tensor | None = None
) -> Tensor:
    """Scaled dot-product attention.

    Supports 3D and 4D inputs.
    If mask is a boolean tensor, True entries are masked before softmax.
    """
    raise NotImplementedError


class TransformerLM(nn.Module):
    """Decoder-only Transformer Language Model."""

    def __init__(
        self,
        vocab_size: int,
        context_length: int,
        d_model: int,
        num_layers: int,
        num_heads: int,
        d_ff: int,
        theta: float = 10000.0,
        eps: float = 1e-5,
    ):
        super().__init__()
        raise NotImplementedError

    def forward(self, token_ids: Tensor) -> Tensor:
        """
        Args:
            token_ids: (batch_size, seq_len) integer token indices.
        Returns:
            (batch_size, seq_len, vocab_size) logits.
        """
        raise NotImplementedError


class AdamW(torch.optim.Optimizer):
    """AdamW optimizer with decoupled weight decay."""

    def __init__(
        self,
        params,
        lr: float = 1e-3,
        betas: tuple = (0.9, 0.999),
        eps: float = 1e-8,
        weight_decay: float = 0.01,
    ):
        defaults = dict(lr=lr, betas=betas, eps=eps, weight_decay=weight_decay)
        super().__init__(params, defaults)

    def step(self, closure=None):
        """Perform a single optimization step."""
        raise NotImplementedError


def get_cosine_schedule(
    it: int,
    max_learning_rate: float,
    min_learning_rate: float,
    warmup_iters: int,
    cosine_cycle_iters: int,
) -> float:
    """Compute learning rate for the given iteration."""
    raise NotImplementedError


def gradient_clipping(
    parameters: Iterable[torch.nn.Parameter], max_l2_norm: float
) -> None:
    """Clip parameter gradients. Skip parameters without gradients."""
    raise NotImplementedError
