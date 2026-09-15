"""High-level inference utilities: guidance, stage splitting, and pipeline integration."""

import numpy as np

from .scheduler import compute_sigmas
from .geometry import compute_latent_shape
from .conditioning import build_conditioning_mask, expand_mask_to_frames
from .actions import parse_dual_arm_action, denormalize_gripper, sample_frame_indices


def apply_cfg(uncond, cond, scale):
    """Apply classifier-free guidance to combine conditional and unconditional predictions.

    Args:
        uncond: Unconditional model output.
        cond: Conditional model output.
        scale: Guidance scale (w >= 1 amplifies conditional signal).
    """
    return cond + scale * (cond - uncond)


def split_two_stage(sigmas, ratio):
    """Split a sigma schedule into high-noise and low-noise stages.

    Args:
        sigmas: Full sigma array (descending).
        ratio: Fraction of steps allocated to the first (high-noise) stage.

    Returns:
        (stage1_sigmas, stage2_sigmas) tuple.
    """
    boundary = int(len(sigmas) * ratio) + 1
    return sigmas[:boundary], sigmas[boundary:]


def run_pipeline(episode_data, config):
    """Run the full conditioning pipeline on a robot episode.

    Computes all quantities needed to set up a flow-matching denoising pass:
    sigma schedule, latent geometry, conditioning masks, frame sampling,
    action parsing, and stage splitting.
    """
    cfg_pipe = config['pipeline']
    cfg_vae = config['vae']
    cfg_vid = config['video']
    cfg_cond = config['conditioning']
    cfg_robot = config['robot']

    sigmas = compute_sigmas(cfg_pipe['num_inference_steps'], cfg_pipe['flow_shift'])

    latent_shape = compute_latent_shape(
        cfg_vid['num_frames'], cfg_vid['height'], cfg_vid['width'],
        cfg_vae['temporal_factor'], cfg_vae['spatial_factor'],
    )

    latent_mask = build_conditioning_mask(latent_shape[0], cfg_cond['ref_indices'])
    frame_mask = expand_mask_to_frames(
        latent_mask, cfg_vae['temporal_factor'], cfg_vid['num_frames'],
    )

    stage1, stage2 = split_two_stage(sigmas, cfg_pipe['boundary_ratio'])

    frame_indices = sample_frame_indices(
        episode_data['num_video_frames'],
        cfg_vid['num_frames'], cfg_vid['stride'], cfg_vid['start'],
    )

    parsed_actions = []
    norm_left = []
    norm_right = []
    grip_lo, grip_hi = cfg_robot['gripper_range']

    for fi in frame_indices:
        act = parse_dual_arm_action(episode_data['trajectory'][fi])
        parsed_actions.append(act)
        norm_left.append(denormalize_gripper(act['left_gripper'], grip_lo, grip_hi))
        norm_right.append(denormalize_gripper(act['right_gripper'], grip_lo, grip_hi))

    return {
        'sigmas': sigmas,
        'latent_shape': latent_shape,
        'latent_conditioning_mask': latent_mask,
        'frame_conditioning_mask': frame_mask,
        'stage1_sigmas': stage1,
        'stage2_sigmas': stage2,
        'frame_indices': frame_indices,
        'parsed_actions': parsed_actions,
        'normalized_grippers_left': norm_left,
        'normalized_grippers_right': norm_right,
    }
