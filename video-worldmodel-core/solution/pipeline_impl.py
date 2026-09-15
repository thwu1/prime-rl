"""
Pipeline Orchestrator - Implementation.
"""

import torch


def compute_latent_dimensions(
    frame_height, frame_width, num_views, vae_spatial_scale, vae_temporal_scale, total_frames
):
    view_width = frame_width * num_views
    latent_height = frame_height // vae_spatial_scale
    latent_width = view_width // vae_spatial_scale
    num_latent_frames = (total_frames - 1) // vae_temporal_scale + 1
    return {
        'latent_height': latent_height,
        'latent_width': latent_width,
        'num_latent_frames': num_latent_frames,
        'view_width': view_width,
    }


def compute_patch_sequence(
    latent_height, latent_width, num_latent_frames, patch_size_t, patch_size_hw
):
    seq_t = num_latent_frames // patch_size_t
    seq_h = latent_height // patch_size_hw
    seq_w = latent_width // patch_size_hw
    return {
        'seq_t': seq_t,
        'seq_h': seq_h,
        'seq_w': seq_w,
        'total_seq_len': seq_t * seq_h * seq_w,
    }


def build_pipeline_config(
    frame_height=224, frame_width=224, num_views=3,
    total_frames=33, frames_per_step=8, rollout_steps=4,
    attention_head_dim=128,
    vae_spatial_scale=8, vae_temporal_scale=4,
    patch_size_t=1, patch_size_hw=2,
    num_inference_steps=50, guidance_scale=5.0,
    max_ref_frames=1,
    base_shift=0.5, max_shift=1.15,
    base_seq_len=256, max_seq_len=4096,
):
    from video_wm.rotary_embed import compute_3d_rotary_embeddings
    from video_wm.flow_schedule import compute_flow_schedule, compute_mu
    from video_wm.rollout import build_rollout_schedule, compute_reference_mask

    lat_dims = compute_latent_dimensions(
        frame_height, frame_width, num_views,
        vae_spatial_scale, vae_temporal_scale, total_frames
    )

    seq_dims = compute_patch_sequence(
        lat_dims['latent_height'], lat_dims['latent_width'],
        lat_dims['num_latent_frames'], patch_size_t, patch_size_hw
    )

    cos, sin = compute_3d_rotary_embeddings(
        attention_head_dim, seq_dims['seq_t'], seq_dims['seq_h'], seq_dims['seq_w']
    )

    schedule = compute_flow_schedule(
        num_inference_steps, seq_dims['total_seq_len'],
        base_shift, max_shift, base_seq_len, max_seq_len
    )

    mu = compute_mu(
        seq_dims['total_seq_len'], base_shift, max_shift, base_seq_len, max_seq_len
    )

    rollout = build_rollout_schedule(total_frames, frames_per_step, rollout_steps)

    ref_mask = compute_reference_mask(lat_dims['num_latent_frames'], max_ref_frames)

    return {
        'latent_dims': lat_dims,
        'sequence_dims': seq_dims,
        'rotary_cos': cos,
        'rotary_sin': sin,
        'denoising_schedule': schedule,
        'rollout_schedule': rollout,
        'reference_mask': ref_mask,
        'schedule_mu': mu,
    }
