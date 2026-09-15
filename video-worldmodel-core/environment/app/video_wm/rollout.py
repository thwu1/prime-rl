"""
Multi-Step Rollout Scheduling and Frame Masking.

Implements the autoregressive rollout strategy with reference frame masking,
loss masking, and classifier-free guidance.

See SPEC.md Section 6 for mathematical specification and constraints.
"""

import torch


def compute_num_latent_frames(num_frames: int, vae_temporal_scale: int) -> int:
    """Compute the number of latent frames after VAE temporal compression.

    N_latent = floor((N_frames - 1) / s_t) + 1

    Args:
        num_frames: Number of video frames.
        vae_temporal_scale: VAE temporal downsampling factor.

    Returns:
        Number of frames in latent space.
    """
    raise NotImplementedError("Implement compute_num_latent_frames")


def build_rollout_schedule(
    total_frames: int,
    frames_per_step: int,
    rollout_steps: int,
) -> list[tuple[int, int]]:
    """Build the multi-step rollout frame schedule.

    Args:
        total_frames: Total number of video frames.
        frames_per_step: Number of new frames predicted per rollout step.
        rollout_steps: Number of rollout steps.

    Returns:
        List of (start_frame, end_frame) tuples for each rollout step.
    """
    raise NotImplementedError("Implement build_rollout_schedule")


def compute_reference_mask(
    num_latent_frames: int,
    max_ref: int = 1,
) -> torch.Tensor:
    """Generate binary mask indicating reference (ground truth) latent frames.

    Args:
        num_latent_frames: Total number of latent frames.
        max_ref: Number of reference frames at the beginning.

    Returns:
        Float tensor of shape (num_latent_frames,) with 1.0 for reference frames.
    """
    raise NotImplementedError("Implement compute_reference_mask")


def compute_loss_mask(
    num_latent_frames: int,
    rollout_step: int,
    ref_frames: int = 1,
) -> torch.Tensor:
    """Generate loss mask for a single rollout step.

    Args:
        num_latent_frames: Number of latent frames in this rollout step.
        rollout_step: Index of current rollout step (0-based).
        ref_frames: Number of reference frames (only used for step 0).

    Returns:
        Float tensor of shape (num_latent_frames,) with 1.0 where loss is computed.
    """
    raise NotImplementedError("Implement compute_loss_mask")


def compute_guidance(
    noise_pred_uncond: torch.Tensor,
    noise_pred_cond: torch.Tensor,
    guidance_scale: float,
) -> torch.Tensor:
    """Apply classifier-free guidance.

    The formula must satisfy:
    - guidance_scale=0 -> output = noise_pred_uncond
    - guidance_scale=1 -> output = noise_pred_cond
    - guidance_scale>1 -> extrapolation beyond cond in the cond-uncond direction

    Derive the linear combination from these constraints.

    Args:
        noise_pred_uncond: Unconditional noise prediction.
        noise_pred_cond: Conditional noise prediction.
        guidance_scale: Guidance scale factor.

    Returns:
        Guided noise prediction (same shape as inputs).
    """
    raise NotImplementedError("Implement compute_guidance")
