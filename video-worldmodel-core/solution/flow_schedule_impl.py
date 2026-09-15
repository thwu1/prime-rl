"""
Flow Matching Timestep Schedule - Implementation.
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
    m = (max_shift - base_shift) / (max_seq_len - base_seq_len)
    b = base_shift - m * base_seq_len
    return m * image_seq_len + b


def compute_image_seq_len(
    num_latent_frames: int,
    latent_height: int,
    latent_width: int,
    patch_size_t: int = 1,
    patch_size_hw: int = 2,
) -> int:
    return (num_latent_frames // patch_size_t) * \
           (latent_height // patch_size_hw) * \
           (latent_width // patch_size_hw)


def _time_shift(mu: float, sigma: float, t: torch.Tensor) -> torch.Tensor:
    return math.exp(mu) / (math.exp(mu) + (1.0 / t - 1.0) ** sigma)


def compute_flow_schedule(
    num_steps: int,
    image_seq_len: int,
    base_shift: float = 0.5,
    max_shift: float = 1.15,
    base_seq_len: int = 256,
    max_seq_len: int = 4096,
) -> torch.Tensor:
    mu = compute_mu(image_seq_len, base_shift, max_shift, base_seq_len, max_seq_len)
    timesteps = torch.linspace(1.0, 1.0 / num_steps, num_steps)
    shifted = _time_shift(mu, 1.0, timesteps)
    return shifted


def compute_sigma_interpolation(
    latents: torch.Tensor,
    noise: torch.Tensor,
    sigma: float,
) -> torch.Tensor:
    return noise * sigma + latents * (1.0 - sigma)
