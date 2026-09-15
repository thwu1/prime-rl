
import sys
sys.path.insert(0, "/app")

import math
import pytest
import torch


# ===========================================================================
# 3D Rotary Position Embeddings
# ===========================================================================

class TestRotaryEmbeddings:
    def test_dimension_split_128(self):
        from video_wm.rotary_embed import get_dimension_split
        t, h, w = get_dimension_split(128)
        assert (t, h, w) == (44, 42, 42)
        assert t + h + w == 128

    def test_dimension_split_64(self):
        from video_wm.rotary_embed import get_dimension_split
        t, h, w = get_dimension_split(64)
        assert (t, h, w) == (24, 20, 20)
        assert t + h + w == 64

    def test_dimension_split_96(self):
        from video_wm.rotary_embed import get_dimension_split
        t, h, w = get_dimension_split(96)
        assert (t, h, w) == (32, 32, 32)
        assert t + h + w == 96

    def test_h_equals_w(self):
        """h_dim and w_dim must always be equal."""
        from video_wm.rotary_embed import get_dimension_split
        for d in [64, 96, 128, 192, 256]:
            _, h, w = get_dimension_split(d)
            assert h == w, f"h_dim != w_dim for head_dim={d}"

    def test_output_shape_small(self):
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, seq_len_t=2, seq_len_h=3, seq_len_w=4)
        assert cos.shape == (24, 64), f"Expected (24, 64), got {cos.shape}"
        assert sin.shape == (24, 64), f"Expected (24, 64), got {sin.shape}"

    def test_output_shape_real_config(self):
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, seq_len_t=9, seq_len_h=14, seq_len_w=42)
        assert cos.shape == (5292, 64)
        assert sin.shape == (5292, 64)

    def test_float32_output(self):
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        assert cos.dtype == torch.float32
        assert sin.dtype == torch.float32

    def test_unit_circle_property(self):
        """cos^2 + sin^2 = 1 for all positions and frequencies."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        result = cos ** 2 + sin ** 2
        assert torch.allclose(result, torch.ones_like(result), atol=1e-5)

    def test_origin_position(self):
        """Position (0,0,0) has zero angles: cos=1, sin=0."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        assert torch.allclose(cos[0], torch.ones(64), atol=1e-6)
        assert torch.allclose(sin[0], torch.zeros(64), atol=1e-6)

    def test_temporal_only_position(self):
        """Position (1,0,0): only temporal frequencies are non-trivial."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        # Index for (t=1, h=0, w=0) in (2,3,4) grid = 1*3*4 = 12
        # Temporal: first 22 values (t_dim/2=22)
        # Height: next 21 values (h_dim/2=21), all cos=1/sin=0 since h=0
        # Width: last 21 values (w_dim/2=21), all cos=1/sin=0 since w=0
        assert torch.allclose(cos[12, 22:43], torch.ones(21), atol=1e-6), \
            "Height cos should be 1.0 at h=0"
        assert torch.allclose(sin[12, 22:43], torch.zeros(21), atol=1e-6), \
            "Height sin should be 0.0 at h=0"
        assert torch.allclose(cos[12, 43:64], torch.ones(21), atol=1e-6), \
            "Width cos should be 1.0 at w=0"
        assert torch.allclose(sin[12, 43:64], torch.zeros(21), atol=1e-6), \
            "Width sin should be 0.0 at w=0"
        # First temporal frequency at t=1: angle = 1.0 * (1/theta^(0/44)) = 1.0
        assert abs(cos[12, 0].item() - math.cos(1.0)) < 1e-5
        assert abs(sin[12, 0].item() - math.sin(1.0)) < 1e-5

    def test_height_only_position(self):
        """Position (0,1,0): only height frequencies are non-trivial."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        # Index for (t=0, h=1, w=0) = 0*12 + 1*4 + 0 = 4
        # Temporal (first 22): all cos=1 sin=0
        assert torch.allclose(cos[4, 0:22], torch.ones(22), atol=1e-6)
        assert torch.allclose(sin[4, 0:22], torch.zeros(22), atol=1e-6)
        # Height (22:43): non-trivial, first freq = 1/theta^(0/42) = 1.0
        assert abs(cos[4, 22].item() - math.cos(1.0)) < 1e-5
        assert abs(sin[4, 22].item() - math.sin(1.0)) < 1e-5
        # Width (43:64): all cos=1 sin=0
        assert torch.allclose(cos[4, 43:64], torch.ones(21), atol=1e-6)
        assert torch.allclose(sin[4, 43:64], torch.zeros(21), atol=1e-6)

    def test_apply_identity_at_origin(self):
        """Rotation at position 0 should be identity (all angles are 0)."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings, apply_rotary_emb
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        torch.manual_seed(42)
        x = torch.randn(1, 2, 24, 128)
        result = apply_rotary_emb(x, cos, sin)
        assert result.shape == x.shape
        assert torch.allclose(result[0, :, 0, :], x[0, :, 0, :], atol=1e-5)

    def test_apply_preserves_norm(self):
        """Rotary embeddings preserve the per-position L2 norm."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings, apply_rotary_emb
        cos, sin = compute_3d_rotary_embeddings(128, 2, 3, 4)
        torch.manual_seed(123)
        x = torch.randn(2, 4, 24, 128)
        result = apply_rotary_emb(x, cos, sin)
        x_norms = x.norm(dim=-1)
        result_norms = result.norm(dim=-1)
        assert torch.allclose(x_norms, result_norms, atol=1e-4)

    def test_apply_output_shape(self):
        from video_wm.rotary_embed import compute_3d_rotary_embeddings, apply_rotary_emb
        cos, sin = compute_3d_rotary_embeddings(64, 3, 5, 7)
        x = torch.randn(2, 8, 105, 64)
        result = apply_rotary_emb(x, cos, sin)
        assert result.shape == (2, 8, 105, 64)


# ===========================================================================
# Flow Matching Schedule
# ===========================================================================

class TestFlowSchedule:
    def test_mu_at_base(self):
        from video_wm.flow_schedule import compute_mu
        mu = compute_mu(256, base_shift=0.5, max_shift=1.15,
                        base_seq_len=256, max_seq_len=4096)
        assert abs(mu - 0.5) < 1e-6

    def test_mu_at_max(self):
        from video_wm.flow_schedule import compute_mu
        mu = compute_mu(4096, base_shift=0.5, max_shift=1.15,
                        base_seq_len=256, max_seq_len=4096)
        assert abs(mu - 1.15) < 1e-6

    def test_mu_midpoint(self):
        from video_wm.flow_schedule import compute_mu
        mid = (256 + 4096) / 2  # 2176
        mu = compute_mu(mid, base_shift=0.5, max_shift=1.15,
                        base_seq_len=256, max_seq_len=4096)
        expected = (0.5 + 1.15) / 2  # 0.825
        assert abs(mu - expected) < 1e-6

    def test_mu_extrapolates(self):
        """mu is NOT clamped; it can exceed max_shift for large seq_len."""
        from video_wm.flow_schedule import compute_mu
        mu = compute_mu(8000, base_shift=0.5, max_shift=1.15,
                        base_seq_len=256, max_seq_len=4096)
        assert mu > 1.15

    def test_image_seq_len(self):
        from video_wm.flow_schedule import compute_image_seq_len
        seq = compute_image_seq_len(9, 28, 84, patch_size_t=1, patch_size_hw=2)
        assert seq == 9 * 14 * 42
        assert seq == 5292

    def test_schedule_shape(self):
        from video_wm.flow_schedule import compute_flow_schedule
        ts = compute_flow_schedule(num_steps=50, image_seq_len=1000)
        assert ts.shape == (50,)

    def test_schedule_monotonic(self):
        from video_wm.flow_schedule import compute_flow_schedule
        ts = compute_flow_schedule(num_steps=50, image_seq_len=1000)
        for i in range(49):
            assert ts[i] > ts[i + 1], f"Not monotonically decreasing at index {i}"

    def test_schedule_range(self):
        from video_wm.flow_schedule import compute_flow_schedule
        ts = compute_flow_schedule(num_steps=50, image_seq_len=1000)
        assert ts[0].item() <= 1.0
        assert ts[-1].item() > 0.0

    def test_first_timestep_is_one(self):
        """First timestep (highest noise) should always be 1.0 regardless of shift."""
        from video_wm.flow_schedule import compute_flow_schedule
        ts = compute_flow_schedule(num_steps=50, image_seq_len=2000)
        assert abs(ts[0].item() - 1.0) < 1e-6

    def test_no_shift(self):
        """With mu=0 (base_shift=max_shift=0), timesteps = base timesteps."""
        from video_wm.flow_schedule import compute_flow_schedule
        ts = compute_flow_schedule(num_steps=10, image_seq_len=256,
                                   base_shift=0.0, max_shift=0.0)
        expected = torch.linspace(1.0, 0.1, 10)
        assert torch.allclose(ts, expected, atol=1e-5)

    def test_sigma_interpolation_extremes(self):
        from video_wm.flow_schedule import compute_sigma_interpolation
        latents = torch.ones(2, 4, 3, 3)
        noise = torch.zeros(2, 4, 3, 3)
        # sigma=0: pure latent
        result_0 = compute_sigma_interpolation(latents, noise, 0.0)
        assert torch.allclose(result_0, latents, atol=1e-6)
        # sigma=1: pure noise
        result_1 = compute_sigma_interpolation(latents, noise, 1.0)
        assert torch.allclose(result_1, noise, atol=1e-6)

    def test_sigma_interpolation_midpoint(self):
        from video_wm.flow_schedule import compute_sigma_interpolation
        latents = torch.ones(1, 1, 2, 2) * 2.0
        noise = torch.ones(1, 1, 2, 2) * 4.0
        result = compute_sigma_interpolation(latents, noise, 0.5)
        expected = torch.ones(1, 1, 2, 2) * 3.0  # 0.5*4 + 0.5*2
        assert torch.allclose(result, expected, atol=1e-6)


# ===========================================================================
# Adaptive Layer Normalization
# ===========================================================================

class TestAdaLN:
    def test_rms_norm_known_value(self):
        from video_wm.adaln import rms_norm
        x = torch.tensor([[3.0, 4.0]])
        result = rms_norm(x)
        rms_val = math.sqrt((9.0 + 16.0) / 2.0 + 1e-6)
        expected = torch.tensor([[3.0 / rms_val, 4.0 / rms_val]])
        assert torch.allclose(result, expected, atol=1e-4)

    def test_rms_norm_unit_mean_sq(self):
        """After RMS norm, mean of squares should be approximately 1."""
        from video_wm.adaln import rms_norm
        torch.manual_seed(0)
        x = torch.randn(10, 256)
        normed = rms_norm(x)
        mean_sq = (normed ** 2).mean(dim=-1)
        assert torch.allclose(mean_sq, torch.ones(10), atol=1e-3)

    def test_modulation_shapes(self):
        from video_wm.adaln import compute_adaln_modulation
        sst = torch.zeros(1, 6, 64)
        temb = torch.zeros(2, 384)  # 6*64
        parts = compute_adaln_modulation(sst, temb)
        assert len(parts) == 6
        for p in parts:
            assert p.shape == (2, 1, 64), f"Expected (2, 1, 64), got {p.shape}"

    def test_modulation_values(self):
        """With zero table and ones temb, all parts should be ones."""
        from video_wm.adaln import compute_adaln_modulation
        dim = 32
        sst = torch.zeros(1, 6, dim)
        temb = torch.ones(1, 6 * dim)
        parts = compute_adaln_modulation(sst, temb)
        for p in parts:
            assert torch.allclose(p, torch.ones(1, 1, dim), atol=1e-6)

    def test_modulation_with_table(self):
        """Table values add to temb values."""
        from video_wm.adaln import compute_adaln_modulation
        dim = 16
        sst = torch.full((1, 6, dim), 0.5)
        temb = torch.full((1, 6 * dim), 0.3)
        parts = compute_adaln_modulation(sst, temb)
        for p in parts:
            assert torch.allclose(p, torch.full((1, 1, dim), 0.8), atol=1e-5)

    def test_apply_identity(self):
        """With scale=0 and shift=0, output equals rms_norm(x)."""
        from video_wm.adaln import apply_adaln_modulation, rms_norm
        torch.manual_seed(7)
        x = torch.randn(2, 10, 64)
        shift = torch.zeros(2, 1, 64)
        scale = torch.zeros(2, 1, 64)
        result = apply_adaln_modulation(x, shift, scale)
        expected = rms_norm(x)
        assert torch.allclose(result, expected, atol=1e-5)

    def test_apply_scale_shift(self):
        """Verify scale=1 doubles the norm, shift=0.5 adds offset."""
        from video_wm.adaln import apply_adaln_modulation, rms_norm
        torch.manual_seed(7)
        x = torch.randn(1, 5, 32)
        shift = torch.full((1, 1, 32), 0.5)
        scale = torch.full((1, 1, 32), 1.0)
        result = apply_adaln_modulation(x, shift, scale)
        expected = 2.0 * rms_norm(x) + 0.5
        assert torch.allclose(result, expected, atol=1e-5)


# ===========================================================================
# Multi-Step Rollout
# ===========================================================================

class TestRollout:
    def test_latent_frame_count_33(self):
        from video_wm.rollout import compute_num_latent_frames
        assert compute_num_latent_frames(33, 4) == 9

    def test_latent_frame_count_9(self):
        from video_wm.rollout import compute_num_latent_frames
        assert compute_num_latent_frames(9, 4) == 3

    def test_latent_frame_count_1(self):
        from video_wm.rollout import compute_num_latent_frames
        assert compute_num_latent_frames(1, 4) == 1

    def test_latent_frame_count_81(self):
        """Standard Wan config: 81 frames with temporal scale 4."""
        from video_wm.rollout import compute_num_latent_frames
        assert compute_num_latent_frames(81, 4) == 21

    def test_rollout_schedule(self):
        from video_wm.rollout import build_rollout_schedule
        sched = build_rollout_schedule(33, 8, 4)
        assert sched == [(0, 8), (8, 16), (16, 24), (24, 32)]

    def test_rollout_schedule_coverage(self):
        """Schedule should cover frames 0 through total_frames-1."""
        from video_wm.rollout import build_rollout_schedule
        sched = build_rollout_schedule(33, 8, 4)
        assert sched[0][0] == 0
        assert sched[-1][1] == 32  # total_frames - 1

    def test_reference_mask_single(self):
        from video_wm.rollout import compute_reference_mask
        mask = compute_reference_mask(9, max_ref=1)
        assert mask.shape == (9,)
        assert mask[0].item() == 1.0
        assert mask[1:].sum().item() == 0.0

    def test_reference_mask_multiple(self):
        from video_wm.rollout import compute_reference_mask
        mask = compute_reference_mask(9, max_ref=3)
        assert mask[:3].sum().item() == 3.0
        assert mask[3:].sum().item() == 0.0

    def test_loss_mask_first_step(self):
        from video_wm.rollout import compute_loss_mask
        mask = compute_loss_mask(3, rollout_step=0, ref_frames=1)
        assert mask[0].item() == 0.0  # Reference frame, no loss
        assert mask[1].item() == 1.0
        assert mask[2].item() == 1.0

    def test_loss_mask_later_step(self):
        from video_wm.rollout import compute_loss_mask
        mask = compute_loss_mask(3, rollout_step=1)
        assert mask[0].item() == 0.0  # Overlap from previous step
        assert mask[1].item() == 1.0
        assert mask[2].item() == 1.0

    def test_guidance_computation(self):
        from video_wm.rollout import compute_guidance
        uncond = torch.ones(1, 4) * 2.0
        cond = torch.ones(1, 4) * 3.0
        result = compute_guidance(uncond, cond, guidance_scale=5.0)
        expected = torch.ones(1, 4) * 7.0  # 2 + 5*(3-2) = 7
        assert torch.allclose(result, expected, atol=1e-6)

    def test_guidance_zero_scale(self):
        from video_wm.rollout import compute_guidance
        torch.manual_seed(0)
        uncond = torch.randn(2, 8)
        cond = torch.randn(2, 8)
        result = compute_guidance(uncond, cond, guidance_scale=0.0)
        assert torch.allclose(result, uncond, atol=1e-6)

    def test_guidance_unit_scale(self):
        from video_wm.rollout import compute_guidance
        torch.manual_seed(0)
        uncond = torch.randn(2, 8)
        cond = torch.randn(2, 8)
        result = compute_guidance(uncond, cond, guidance_scale=1.0)
        assert torch.allclose(result, cond, atol=1e-6)


# ===========================================================================
# Multi-View Assembly
# ===========================================================================

class TestMultiView:
    def test_resize_pad_landscape(self):
        """320x240 -> 224x224: scale 0.7, pad top/bottom 28px each."""
        from video_wm.multiview import resize_with_pad
        img = torch.ones(3, 240, 320)
        result = resize_with_pad(img, 224, 224)
        assert result.shape == (3, 224, 224)
        # Top 28 rows should be zero padding
        assert result[:, :28, :].abs().max() < 1e-5
        # Bottom 28 rows should be zero padding
        assert result[:, -28:, :].abs().max() < 1e-5

    def test_resize_pad_portrait(self):
        """320x160 -> 224x224: scale 0.7, pad left/right 56px each."""
        from video_wm.multiview import resize_with_pad
        img = torch.ones(3, 320, 160)
        result = resize_with_pad(img, 224, 224)
        assert result.shape == (3, 224, 224)
        assert result[:, :, :56].abs().max() < 1e-5
        assert result[:, :, -56:].abs().max() < 1e-5

    def test_resize_pad_square_no_padding(self):
        """Square input to same-size square: no padding needed."""
        from video_wm.multiview import resize_with_pad
        img = torch.ones(3, 224, 224) * 0.5
        result = resize_with_pad(img, 224, 224)
        assert result.shape == (3, 224, 224)
        assert result.mean().item() > 0.4  # Content should be preserved

    def test_resize_pad_content_region(self):
        """The non-padded region should contain non-zero values."""
        from video_wm.multiview import resize_with_pad
        img = torch.ones(3, 240, 320) * 0.7
        result = resize_with_pad(img, 224, 224)
        # Content region: rows 28..196, cols 0..224
        content = result[:, 28:196, :]
        assert content.mean().item() > 0.5

    def test_concatenate_views(self):
        from video_wm.multiview import concatenate_views
        h = torch.ones(3, 224, 224) * 1.0
        l = torch.ones(3, 224, 224) * 2.0
        r = torch.ones(3, 224, 224) * 3.0
        result = concatenate_views(h, l, r)
        assert result.shape == (3, 224, 672)
        assert torch.allclose(result[:, :, :224], h)
        assert torch.allclose(result[:, :, 224:448], l)
        assert torch.allclose(result[:, :, 448:672], r)

    def test_normalize_black(self):
        from video_wm.multiview import normalize_image
        img = torch.zeros(3, 4, 4)
        result = normalize_image(img)
        assert torch.allclose(result, torch.full_like(result, -1.0), atol=1e-5)

    def test_normalize_white(self):
        from video_wm.multiview import normalize_image
        img = torch.full((3, 4, 4), 255.0)
        result = normalize_image(img)
        assert torch.allclose(result, torch.full_like(result, 1.0), atol=1e-5)

    def test_normalize_mid_gray(self):
        from video_wm.multiview import normalize_image
        img = torch.full((3, 4, 4), 127.5)
        result = normalize_image(img)
        assert torch.allclose(result, torch.full_like(result, 0.0), atol=1e-5)


# ===========================================================================
# Pipeline Orchestration
# ===========================================================================

class TestPipeline:
    def test_latent_dimensions_standard(self):
        """Standard config: 224x224 frames, 3 views, VAE 8x spatial, 4x temporal."""
        from video_wm.pipeline import compute_latent_dimensions
        dims = compute_latent_dimensions(
            frame_height=224, frame_width=224, num_views=3,
            vae_spatial_scale=8, vae_temporal_scale=4, total_frames=33
        )
        assert dims['view_width'] == 672
        assert dims['latent_height'] == 28
        assert dims['latent_width'] == 84
        assert dims['num_latent_frames'] == 9

    def test_latent_dimensions_different_resolution(self):
        """Non-standard resolution: 128x192 frames."""
        from video_wm.pipeline import compute_latent_dimensions
        dims = compute_latent_dimensions(
            frame_height=128, frame_width=192, num_views=3,
            vae_spatial_scale=8, vae_temporal_scale=4, total_frames=33
        )
        assert dims['view_width'] == 576
        assert dims['latent_height'] == 16
        assert dims['latent_width'] == 72
        assert dims['num_latent_frames'] == 9

    def test_latent_dimensions_81_frames(self):
        """81 frames (standard Wan) with temporal scale 4."""
        from video_wm.pipeline import compute_latent_dimensions
        dims = compute_latent_dimensions(
            frame_height=224, frame_width=224, num_views=3,
            vae_spatial_scale=8, vae_temporal_scale=4, total_frames=81
        )
        assert dims['num_latent_frames'] == 21

    def test_patch_sequence_standard(self):
        from video_wm.pipeline import compute_patch_sequence
        seq = compute_patch_sequence(
            latent_height=28, latent_width=84, num_latent_frames=9,
            patch_size_t=1, patch_size_hw=2
        )
        assert seq['seq_t'] == 9
        assert seq['seq_h'] == 14
        assert seq['seq_w'] == 42
        assert seq['total_seq_len'] == 5292

    def test_patch_sequence_different_dims(self):
        from video_wm.pipeline import compute_patch_sequence
        seq = compute_patch_sequence(
            latent_height=16, latent_width=72, num_latent_frames=9,
            patch_size_t=1, patch_size_hw=2
        )
        assert seq['seq_t'] == 9
        assert seq['seq_h'] == 8
        assert seq['seq_w'] == 36
        assert seq['total_seq_len'] == 2592

    def test_build_pipeline_config_standard(self):
        """Full pipeline config with standard parameters."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config()
        assert config['latent_dims']['num_latent_frames'] == 9
        assert config['latent_dims']['latent_height'] == 28
        assert config['latent_dims']['latent_width'] == 84
        assert config['sequence_dims']['total_seq_len'] == 5292
        assert config['rotary_cos'].shape == (5292, 64)
        assert config['rotary_sin'].shape == (5292, 64)
        assert config['denoising_schedule'].shape == (50,)
        assert len(config['rollout_schedule']) == 4
        assert config['reference_mask'].shape == (9,)
        assert isinstance(config['schedule_mu'], float)

    def test_pipeline_config_rotary_unit_circle(self):
        """Rotary embeddings from pipeline satisfy cos^2 + sin^2 = 1."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config()
        result = config['rotary_cos'] ** 2 + config['rotary_sin'] ** 2
        assert torch.allclose(result, torch.ones_like(result), atol=1e-5)

    def test_pipeline_config_schedule_monotonic(self):
        """Denoising schedule from pipeline is monotonically decreasing."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config()
        ts = config['denoising_schedule']
        assert abs(ts[0].item() - 1.0) < 1e-6
        for i in range(len(ts) - 1):
            assert ts[i] > ts[i + 1]

    def test_pipeline_config_mu_extrapolates(self):
        """mu should exceed base_shift since total_seq_len > base_seq_len."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config()
        assert config['schedule_mu'] > 0.5

    def test_pipeline_config_different_resolution(self):
        """Pipeline correctly handles non-standard frame dimensions."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config(frame_height=128, frame_width=192)
        assert config['latent_dims']['view_width'] == 576
        assert config['latent_dims']['latent_height'] == 16
        assert config['latent_dims']['latent_width'] == 72
        assert config['sequence_dims']['total_seq_len'] == 2592
        assert config['rotary_cos'].shape == (2592, 64)

    def test_pipeline_config_rollout_schedule(self):
        """Rollout schedule from pipeline matches expected structure."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config()
        sched = config['rollout_schedule']
        assert sched == [(0, 8), (8, 16), (16, 24), (24, 32)]

    def test_pipeline_config_reference_mask(self):
        """Reference mask has correct structure."""
        from video_wm.pipeline import build_pipeline_config
        config = build_pipeline_config()
        mask = config['reference_mask']
        assert mask[0].item() == 1.0
        assert mask[1:].sum().item() == 0.0


# ===========================================================================
# Cross-Module Integration Tests
# ===========================================================================

class TestIntegration:
    def test_pipeline_dimensions_consistency(self):
        """All components produce consistent dimensions with real config."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings
        from video_wm.flow_schedule import compute_flow_schedule, compute_image_seq_len
        from video_wm.rollout import compute_num_latent_frames, build_rollout_schedule
        from video_wm.rollout import compute_reference_mask

        total_frames = 33
        vae_t = 4
        vae_s = 8
        dst_h, dst_w = 224, 224
        patch_t, patch_hw = 1, 2

        view_w = dst_w * 3  # 672

        n_latent = compute_num_latent_frames(total_frames, vae_t)
        assert n_latent == 9

        lat_h = dst_h // vae_s  # 28
        lat_w = view_w // vae_s  # 84

        seq_t = n_latent // patch_t  # 9
        seq_h = lat_h // patch_hw   # 14
        seq_w = lat_w // patch_hw   # 42

        image_seq_len = compute_image_seq_len(n_latent, lat_h, lat_w, patch_t, patch_hw)
        assert image_seq_len == seq_t * seq_h * seq_w
        assert image_seq_len == 5292

        cos, sin = compute_3d_rotary_embeddings(128, seq_t, seq_h, seq_w)
        assert cos.shape == (5292, 64)

        ts = compute_flow_schedule(50, image_seq_len)
        assert ts.shape == (50,)
        assert abs(ts[0].item() - 1.0) < 1e-6

        sched = build_rollout_schedule(total_frames, 8, 4)
        assert len(sched) == 4

        mask = compute_reference_mask(n_latent, max_ref=1)
        assert mask.shape == (9,)

    def test_rotary_consistency_multiple_dims(self):
        """Rotary embeddings maintain invariants across head dims."""
        from video_wm.rotary_embed import compute_3d_rotary_embeddings, get_dimension_split

        for head_dim in [64, 96, 128, 192]:
            t_dim, h_dim, w_dim = get_dimension_split(head_dim)
            assert t_dim + h_dim + w_dim == head_dim
            assert h_dim == w_dim
            assert h_dim == 2 * (head_dim // 6)

            cos, sin = compute_3d_rotary_embeddings(head_dim, 3, 5, 7)
            expected_len = 3 * 5 * 7
            assert cos.shape == (expected_len, head_dim // 2)
            assert torch.allclose(cos ** 2 + sin ** 2,
                                  torch.ones_like(cos), atol=1e-5)

    def test_multiview_to_latent_dimensions(self):
        """Multi-view assembly produces correct latent space dimensions."""
        from video_wm.multiview import concatenate_views, resize_with_pad
        from video_wm.rollout import compute_num_latent_frames

        cam = resize_with_pad(torch.randn(3, 480, 640), 224, 224)
        assert cam.shape == (3, 224, 224)

        multi = concatenate_views(cam, cam, cam)
        assert multi.shape == (3, 224, 672)

        # Latent dimensions
        vae_s = 8
        lat_h = 224 // vae_s   # 28
        lat_w = 672 // vae_s   # 84
        assert lat_h == 28
        assert lat_w == 84
