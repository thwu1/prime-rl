"""
Flow Matching Timestep Schedule for Video Diffusion.

Implements the flow matching denoising schedule with dynamic time-shifting
based on the transformer's sequence length.

See SPEC.md Section 4 for mathematical specification and constraints.
"""

import math
import torch


def compute_mu(
    image_seq_len: float,
    base_shift: float = 0.5,
    max_shift: float = 1.15,
    base_seq_len: int = 256,
    max_seq_len: int = 4096,
) -> float:
    """Compute the dynamic shift parameter mu.

    mu is a linear function of image_seq_len, anchored at two reference points:
      - mu(base_seq_len) = base_shift
      - mu(max_seq_len) = max_shift

    The value is NOT clamped.

    Args:
        image_seq_len: Number of image/video tokens after patch embedding.
        base_shift: Shift value at base_seq_len.
        max_shift: Shift value at max_seq_len.
        base_seq_len: Sequence length corresponding to base_shift.
        max_seq_len: Sequence length corresponding to max_shift.

    Returns:
        The mu parameter (float, not clamped).
    """
    raise NotImplementedError("Implement compute_mu")


def compute_image_seq_len(
    num_latent_frames: int,
    latent_height: int,
    latent_width: int,
    patch_size_t: int = 1,
    patch_size_hw: int = 2,
) -> int:
    """Compute the transformer sequence length after patch embedding.

    Args:
        num_latent_frames: Number of frames in latent space.
        latent_height: Height of latent representation.
        latent_width: Width of latent representation.
        patch_size_t: Temporal patch size.
        patch_size_hw: Spatial (height/width) patch size.

    Returns:
        Total number of tokens in the transformer sequence.
    """
    raise NotImplementedError("Implement compute_image_seq_len")


def _time_shift(mu: float, sigma: float, t: torch.Tensor) -> torch.Tensor:
    """Apply the exponential time-shift transformation.

    t_shifted = exp(mu) / (exp(mu) + (1/t - 1)^sigma)
    """
    raise NotImplementedError("Implement _time_shift")


def compute_flow_schedule(
    num_steps: int,
    image_seq_len: int,
    base_shift: float = 0.5,
    max_shift: float = 1.15,
    base_seq_len: int = 256,
    max_seq_len: int = 4096,
) -> torch.Tensor:
    """Generate the flow matching timestep schedule with dynamic shift.

    Args:
        num_steps: Number of denoising steps.
        image_seq_len: Transformer sequence length (for computing shift).
        base_shift: Shift at base_seq_len.
        max_shift: Shift at max_seq_len.
        base_seq_len: Reference sequence length for base_shift.
        max_seq_len: Reference sequence length for max_shift.

    Returns:
        Tensor of shape (num_steps,) with shifted timestep values,
        monotonically decreasing from 1.0 toward 0.
    """
    raise NotImplementedError("Implement compute_flow_schedule")


def compute_sigma_interpolation(
    latents: torch.Tensor,
    noise: torch.Tensor,
    sigma: float,
) -> torch.Tensor:
    """Compute noisy latents via flow matching linear interpolation.

    sigma=0 yields clean latents, sigma=1 yields pure noise.

    Args:
        latents: Clean latent tensor.
        noise: Gaussian noise tensor (same shape as latents).
        sigma: Noise level in [0, 1].

    Returns:
        Noisy latent tensor of same shape.
    """
    raise NotImplementedError("Implement compute_sigma_interpolation")
