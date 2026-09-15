"""
Flow-Matching Video World Model Conditioning Pipeline

Implements all functions for the CPU-side data conditioning pipeline
used in a flow-matching video diffusion model for dual-arm robotic manipulation.
"""

import numpy as np


def compute_flow_match_sigmas(num_steps: int, shift: float) -> np.ndarray:
    """Compute shifted flow-matching sigma schedule."""
    timesteps = np.linspace(1.0, 1.0 / num_steps, num_steps)
    sigmas = shift * timesteps / (1.0 + (shift - 1.0) * timesteps)
    return sigmas


def flow_match_euler_step(
    sample: np.ndarray, velocity: np.ndarray, sigma_t: float, sigma_next: float
) -> np.ndarray:
    """Single Euler integration step for flow-matching ODE."""
    dt = sigma_next - sigma_t
    return sample + velocity * dt


def compute_latent_shape(
    num_frames: int,
    height: int,
    width: int,
    temporal_factor: int,
    spatial_factor: int,
) -> tuple:
    """Compute VAE latent space dimensions from pixel-space dimensions."""
    latent_frames = (num_frames - 1) // temporal_factor + 1
    latent_height = height // spatial_factor
    latent_width = width // spatial_factor
    return (latent_frames, latent_height, latent_width)


def build_conditioning_mask(num_latents: int, ref_indices: list) -> np.ndarray:
    """Build binary conditioning mask. 0=reference, 1=generate."""
    mask = np.ones(num_latents, dtype=np.float64)
    for idx in ref_indices:
        mask[idx] = 0.0
    return mask


def expand_mask_to_frames(
    latent_mask: np.ndarray, factor: int, num_frames: int
) -> np.ndarray:
    """Expand latent-space mask to frame-space resolution."""
    frame_mask = np.zeros(num_frames, dtype=np.float64)
    for i in range(len(latent_mask)):
        frame_start = i * factor
        frame_end = min((i + 1) * factor, num_frames)
        frame_mask[frame_start:frame_end] = latent_mask[i]
    return frame_mask


def blend_conditioning(
    noise_latents: np.ndarray, cond_latents: np.ndarray, mask: np.ndarray
) -> np.ndarray:
    """Blend noise and conditioning latents according to mask."""
    return (1.0 - mask) * cond_latents + mask * noise_latents


def apply_cfg(
    uncond_pred: np.ndarray, cond_pred: np.ndarray, scale: float
) -> np.ndarray:
    """Apply classifier-free guidance."""
    return uncond_pred + scale * (cond_pred - uncond_pred)


def split_timesteps_two_stage(
    sigmas: np.ndarray, boundary_ratio: float
) -> tuple:
    """Split sigma schedule into two stages for two-transformer architecture."""
    boundary_index = int(len(sigmas) * boundary_ratio)
    return sigmas[:boundary_index], sigmas[boundary_index:]


def parse_dual_arm_action(action: np.ndarray) -> dict:
    """Parse 14-dim action vector into dual-arm components."""
    return {
        "left_arm": action[0:6].copy(),
        "left_gripper": float(action[6]),
        "right_arm": action[7:13].copy(),
        "right_gripper": float(action[13]),
    }


def denormalize_gripper(value: float, low: float, high: float) -> float:
    """Map raw gripper value from [low, high] to [0, 1] with clipping."""
    normalized = (value - low) / (high - low)
    return float(np.clip(normalized, 0.0, 1.0))


def sample_frame_indices(
    total_frames: int, num_sample: int, stride: int, start: int = 0
) -> np.ndarray:
    """Sample strided frame indices with clipping."""
    indices = start + np.arange(num_sample) * stride
    indices = np.clip(indices, 0, total_frames - 1)
    return indices.astype(np.int64)


def normalize_latents(
    latents: np.ndarray, mean: np.ndarray, std: np.ndarray
) -> np.ndarray:
    """Per-channel latent normalization."""
    return (latents - mean) / std


def denormalize_latents(
    latents: np.ndarray, mean: np.ndarray, std: np.ndarray
) -> np.ndarray:
    """Inverse of per-channel latent normalization."""
    return latents * std + mean


def prepare_training_sample(episode_data: dict, config: dict) -> dict:
    """End-to-end training sample preparation integrating all pipeline components."""
    # 1. Compute latent shape
    latent_shape = compute_latent_shape(
        num_frames=config["video"]["num_frames"],
        height=config["video"]["height"],
        width=config["video"]["width"],
        temporal_factor=config["vae"]["temporal_factor"],
        spatial_factor=config["vae"]["spatial_factor"],
    )

    # 2. Sample frame indices
    frame_indices = sample_frame_indices(
        total_frames=episode_data["num_video_frames"],
        num_sample=config["video"]["num_frames"],
        stride=config["video"]["stride"],
        start=config["video"]["start"],
    )

    # 3. Build conditioning mask
    latent_conditioning_mask = build_conditioning_mask(
        num_latents=latent_shape[0],
        ref_indices=config["conditioning"]["ref_indices"],
    )

    # 4. Expand mask to frame space
    frame_conditioning_mask = expand_mask_to_frames(
        latent_mask=latent_conditioning_mask,
        factor=config["vae"]["temporal_factor"],
        num_frames=config["video"]["num_frames"],
    )

    # 5. Compute sigma schedule
    sigmas = compute_flow_match_sigmas(
        num_steps=config["pipeline"]["num_inference_steps"],
        shift=config["pipeline"]["flow_shift"],
    )

    # 6. Split into two stages
    stage1_sigmas, stage2_sigmas = split_timesteps_two_stage(
        sigmas=sigmas,
        boundary_ratio=config["pipeline"]["boundary_ratio"],
    )

    # 7. Parse actions for each sampled frame
    trajectory = episode_data["trajectory"]
    parsed_actions = []
    for idx in frame_indices:
        action = trajectory[idx]
        parsed = parse_dual_arm_action(action)
        parsed_actions.append(parsed)

    # 8. Denormalize grippers
    grip_low, grip_high = config["robot"]["gripper_range"]
    normalized_grippers_left = [
        denormalize_gripper(a["left_gripper"], grip_low, grip_high)
        for a in parsed_actions
    ]
    normalized_grippers_right = [
        denormalize_gripper(a["right_gripper"], grip_low, grip_high)
        for a in parsed_actions
    ]

    return {
        "latent_shape": latent_shape,
        "frame_indices": frame_indices,
        "latent_conditioning_mask": latent_conditioning_mask,
        "frame_conditioning_mask": frame_conditioning_mask,
        "sigmas": sigmas,
        "stage1_sigmas": stage1_sigmas,
        "stage2_sigmas": stage2_sigmas,
        "parsed_actions": parsed_actions,
        "normalized_grippers_left": normalized_grippers_left,
        "normalized_grippers_right": normalized_grippers_right,
    }
