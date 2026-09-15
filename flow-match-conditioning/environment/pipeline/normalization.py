"""Per-channel latent normalization utilities."""

import numpy as np


def normalize_latents(x, mean, std):
    """Normalize latents using per-channel mean and standard deviation.

    Args:
        x: Latent tensor.
        mean: Per-channel mean (broadcastable to x).
        std: Per-channel standard deviation (broadcastable to x).
    """
    return (x - mean) * std


def denormalize_latents(x, mean, std):
    """Reverse per-channel normalization.

    Args:
        x: Normalized latent tensor.
        mean: Per-channel mean used during normalization.
        std: Per-channel std used during normalization.
    """
    return x / std + mean
