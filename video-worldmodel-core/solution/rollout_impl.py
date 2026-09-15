"""
Multi-Step Rollout Scheduling - Implementation.
"""

import torch


def compute_num_latent_frames(num_frames: int, vae_temporal_scale: int) -> int:
    return (num_frames - 1) // vae_temporal_scale + 1


def build_rollout_schedule(
    total_frames: int,
    frames_per_step: int,
    rollout_steps: int,
) -> list[tuple[int, int]]:
    schedule = []
    for i in range(rollout_steps):
        start = i * frames_per_step
        end = (i + 1) * frames_per_step
        schedule.append((start, end))
    return schedule


def compute_reference_mask(
    num_latent_frames: int,
    max_ref: int = 1,
) -> torch.Tensor:
    mask = torch.zeros(num_latent_frames)
    mask[:max_ref] = 1.0
    return mask


def compute_loss_mask(
    num_latent_frames: int,
    rollout_step: int,
    ref_frames: int = 1,
) -> torch.Tensor:
    mask = torch.ones(num_latent_frames)
    if rollout_step == 0:
        mask[:ref_frames] = 0.0
    else:
        mask[0] = 0.0
    return mask


def compute_guidance(
    noise_pred_uncond: torch.Tensor,
    noise_pred_cond: torch.Tensor,
    guidance_scale: float,
) -> torch.Tensor:
    return noise_pred_uncond + guidance_scale * (noise_pred_cond - noise_pred_uncond)
