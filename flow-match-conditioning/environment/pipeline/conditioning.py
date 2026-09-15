"""Reference frame conditioning for video diffusion models."""

import numpy as np


def build_conditioning_mask(num_latent_frames, ref_indices):
    """Build a binary mask over latent frames indicating reference vs. generated.

    Args:
        num_latent_frames: Total number of latent temporal positions.
        ref_indices: List of latent frame indices that serve as reference.

    Returns:
        1-D float64 array of length num_latent_frames.
    """
    mask = np.zeros(num_latent_frames, dtype=np.float64)
    for idx in ref_indices:
        mask[idx] = 1.0
    return mask


def expand_mask_to_frames(latent_mask, factor, num_frames):
    """Expand a latent-space mask to pixel-space frame count.

    Each latent position maps to `factor` consecutive frames; the result
    is truncated to `num_frames`.
    """
    expanded = np.repeat(latent_mask, factor)[:num_frames]
    return expanded.astype(np.float64)


def blend_conditioning(noise, condition, mask):
    """Blend noise and conditioning using a binary mask.

    Where mask is 0 the condition is kept; where mask is 1 the noise is kept.
    """
    return (1.0 - mask) * condition + mask * noise
