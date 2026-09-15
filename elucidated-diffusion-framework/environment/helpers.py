"""
Helper utility functions for the Elucidated Diffusion framework.
Do not modify this file.
"""

import torch


def exists(val):
    """Check if a value is not None."""
    return val is not None


def default(val, d):
    """Return val if it exists, otherwise return d (or d() if callable)."""
    if exists(val):
        return val
    return d() if callable(d) else d


def log(t, eps=1e-20):
    """Numerically stable logarithm with epsilon clamping."""
    return torch.log(t.clamp(min=eps))


def normalize_to_neg_one_to_one(img):
    """Map [0, 1] images to [-1, 1]."""
    return img * 2 - 1


def unnormalize_to_zero_to_one(t):
    """Map [-1, 1] images to [0, 1]."""
    return (t + 1) * 0.5
