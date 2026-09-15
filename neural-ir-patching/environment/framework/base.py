"""Base loss infrastructure for neural IR ranking.

Provides the abstract BaseLoss class, reduction utilities, and a loss
registry with decorator for registering concrete loss implementations.
"""

import torch
import torch.nn as nn


LOSS_REGISTRY = {}


def register_loss(key):
    """Decorator to register a loss class in the global registry.

    Usage:
        @register_loss("my_loss")
        class MyLoss(BaseLoss):
            ...
    """
    def decorator(cls):
        LOSS_REGISTRY[key] = cls
        return cls
    return decorator


def reduce(a: torch.Tensor, reduction: str) -> torch.Tensor:
    """Apply reduction strategy to a tensor.

    Args:
        a: Input tensor.
        reduction: One of "mean", "sum", "none", "batchmean".

    Returns:
        Reduced tensor.
    """
    if reduction == "none":
        return a
    if reduction == "mean":
        return a.mean()
    if reduction == "sum":
        return a.sum()
    if reduction == "batchmean":
        return a.mean(dim=0).sum()
    raise ValueError(f"Unknown reduction type: {reduction}")


class BaseLoss(nn.Module):
    """Abstract base class for ranking loss functions.

    All loss implementations must inherit from this class and implement
    the forward() method.

    Args:
        reduction: Reduction method ("mean", "sum", "none", "batchmean").
    """

    name = "base"

    def __init__(self, reduction: str = "mean") -> None:
        super().__init__()
        self.reduction = reduction

    def _reduce(self, a: torch.Tensor) -> torch.Tensor:
        """Apply the configured reduction to a tensor."""
        return reduce(a, self.reduction)

    def forward(self, *args, **kwargs):
        raise NotImplementedError

    def __repr__(self):
        return self.name
