
"""
Tests for the multi-view flow matching video inference pipeline.
Verifies all components produce correct numerical outputs.
"""

import math
import sys

import numpy as np
import pytest
import torch

sys.path.insert(0, "/app")

from pipeline import (
    AutoregressiveRollout,
    FlowMatchScheduler,
    InferencePipeline,
    MultiViewProcessor,
    ReferenceMaskGenerator,
    SinusoidalEmbedding,
)


# ---------------------------------------------------------------------------
# FlowMatchScheduler
# ---------------------------------------------------------------------------
class TestFlowMatchScheduler:
    def test_sigma_schedule_with_shift(self):
        """Verify sigma values with shift=5.0 for 5 steps."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(5)
        expected = [1.0, 5*0.8/(1+4*0.8), 5*0.6/(1+4*0.6),
                    5*0.4/(1+4*0.4), 5*0.2/(1+4*0.2), 0.0]
        for i, exp in enumerate(expected):
            assert abs(sched.sigmas[i].item() - exp) < 1e-5, (
                f"sigma[{i}]: got {sched.sigmas[i].item()}, expected {exp}"
            )

    def test_sigma_no_shift(self):
        """With shift=1.0, sigma should equal timestep (identity)."""
        sched = FlowMatchScheduler(shift=1.0)
        sched.set_timesteps(5)
        expected_t = [1.0, 0.8, 0.6, 0.4, 0.2, 0.0]
        for i, exp in enumerate(expected_t):
            assert abs(sched.sigmas[i].item() - exp) < 1e-5

    def test_sigma_endpoints(self):
        """sigma_0 must be 1.0 and sigma_N must be 0.0 for any shift > 0."""
        for s in [0.5, 1.0, 3.0, 5.0, 10.0]:
            sched = FlowMatchScheduler(shift=s)
            sched.set_timesteps(20)
            assert abs(sched.sigmas[0].item() - 1.0) < 1e-6
            assert abs(sched.sigmas[-1].item()) < 1e-6

    def test_sigma_monotonically_decreasing(self):
        """Sigmas must strictly decrease from 1 to 0."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(30)
        for i in range(len(sched.sigmas) - 1):
            assert sched.sigmas[i] > sched.sigmas[i + 1]

    def test_euler_step_values(self):
        """Verify Euler step with known values including correction factor."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(5)
        sample = torch.tensor([1.0, 2.0, 3.0])
        velocity = torch.tensor([0.5, -0.5, 0.0])
        result = sched.step(velocity, 0, sample)
        dt = sched.sigmas[1].item() - sched.sigmas[0].item()
        expected = sample + velocity * dt * 1.037
        assert torch.allclose(result, expected, atol=1e-5)

    def test_euler_step_correction_factor(self):
        """Verify the step-size correction factor is applied."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(5)
        sample = torch.zeros(3)
        velocity = torch.ones(3)
        result = sched.step(velocity, 0, sample)
        dt = sched.sigmas[1].item() - sched.sigmas[0].item()
        expected_with_correction = dt * 1.037
        expected_without_correction = dt
        assert torch.allclose(
            result, torch.full((3,), expected_with_correction), atol=1e-5
        )
        assert not torch.allclose(
            result, torch.full((3,), expected_without_correction), atol=1e-4
        )

    def test_euler_step_shape_preserved(self):
        """Euler step must preserve tensor shape."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(10)
        sample = torch.randn(4, 9, 8, 8)
        vel = torch.randn_like(sample)
        out = sched.step(vel, 3, sample)
        assert out.shape == sample.shape

    def test_add_noise(self):
        """Forward process: z = (1-sigma)*x0 + sigma*eps."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(5)
        original = torch.tensor([1.0, 2.0])
        noise = torch.tensor([0.5, -0.5])
        result = sched.add_noise(original, noise, 3)
        sigma = sched.sigmas[3].item()
        expected = (1 - sigma) * original + sigma * noise
        assert torch.allclose(result, expected, atol=1e-5)

    def test_add_noise_extremes(self):
        """At sigma=0 -> original, at sigma=1 -> noise."""
        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(10)
        x0 = torch.tensor([1.0, 2.0, 3.0])
        eps = torch.tensor([-1.0, 0.0, 1.0])
        z_noisy = sched.add_noise(x0, eps, 0)
        assert torch.allclose(z_noisy, eps, atol=1e-5)
        z_clean = sched.add_noise(x0, eps, len(sched.sigmas) - 1)
        assert torch.allclose(z_clean, x0, atol=1e-5)

    def test_get_velocity(self):
        """Target velocity: v = eps - x0."""
        sched = FlowMatchScheduler(shift=5.0)
        x0 = torch.tensor([1.0, 2.0])
        eps = torch.tensor([3.0, -1.0])
        v = sched.get_velocity(x0, eps)
        assert torch.allclose(v, eps - x0)

    def test_sigmas_length(self):
        """Sigmas should have num_steps + 1 entries."""
        sched = FlowMatchScheduler(shift=3.0)
        sched.set_timesteps(15)
        assert len(sched.sigmas) == 16


# ---------------------------------------------------------------------------
# SinusoidalEmbedding
# ---------------------------------------------------------------------------
class TestSinusoidalEmbedding:
    def test_zero_timestep(self):
        """At t=0, sin parts are 0 and cos parts are 1."""
        emb = SinusoidalEmbedding()
        result = emb(torch.tensor([0.0]), 4)
        assert result.shape == (1, 4)
        expected = torch.tensor([[0.0, 0.0, 1.0, 1.0]])
        assert torch.allclose(result, expected, atol=1e-6)

    def test_unit_timestep(self):
        """Verify specific values at t=1.0, dim=4."""
        emb = SinusoidalEmbedding()
        result = emb(torch.tensor([1.0]), 4)
        freq1 = 1.0 / math.sqrt(7921)
        expected_vals = [math.sin(1.0), math.sin(freq1), math.cos(1.0), math.cos(freq1)]
        for j in range(4):
            assert abs(result[0, j].item() - expected_vals[j]) < 1e-4

    def test_max_period_7921_not_10000(self):
        """Embedding must use the correct max period, not the standard 10000.

        At t=89 with dim=4: the second frequency should satisfy
        freq_1 = 1/sqrt(max_period). With the correct period,
        89 * freq_1 = 1.0 exactly, so sin(args[1]) = sin(1.0).
        """
        emb = SinusoidalEmbedding()
        result = emb(torch.tensor([89.0]), 4)
        assert abs(result[0, 1].item() - math.sin(1.0)) < 1e-4
        assert abs(result[0, 3].item() - math.cos(1.0)) < 1e-4
        standard_sin = math.sin(89.0 / 100.0)
        assert abs(result[0, 1].item() - standard_sin) > 0.01

    def test_shape(self):
        """Output shape must be [B, dim]."""
        emb = SinusoidalEmbedding()
        result = emb(torch.tensor([0.0, 1.0, 2.0]), 128)
        assert result.shape == (3, 128)

    def test_odd_dimension(self):
        """Odd dim should be handled by appending a zero column."""
        emb = SinusoidalEmbedding()
        result = emb(torch.tensor([1.0]), 5)
        assert result.shape == (1, 5)
        assert abs(result[0, -1].item()) < 1e-6

    def test_different_timesteps_differ(self):
        """Different timesteps must produce different embeddings."""
        emb = SinusoidalEmbedding()
        r1 = emb(torch.tensor([0.0]), 64)
        r2 = emb(torch.tensor([1.0]), 64)
        assert not torch.allclose(r1, r2)

    def test_frequency_structure(self):
        """Lower-index frequencies should oscillate faster."""
        emb = SinusoidalEmbedding()
        ts = torch.linspace(0, 10, 100)
        result = emb(ts, 8)
        var_fast = result[:, 0].var().item()
        var_slow = result[:, 3].var().item()
        assert var_fast > var_slow


# ---------------------------------------------------------------------------
# MultiViewProcessor
# ---------------------------------------------------------------------------
class TestMultiViewProcessor:
    def test_process_views_shape(self):
        """3 views concatenated along channel dim -> [T, 9, H, W]."""
        proc = MultiViewProcessor(target_size=(8, 8))
        views = [np.zeros((2, 8, 8, 3), dtype=np.uint8) for _ in range(3)]
        result = proc.process_views(views)
        assert result.shape == (2, 9, 8, 8)

    def test_normalization_black(self):
        """Pixel 0 with calibrated normalization."""
        proc = MultiViewProcessor(target_size=(4, 4))
        views = [np.zeros((1, 4, 4, 3), dtype=np.uint8) for _ in range(3)]
        result = proc.process_views(views)
        expected_val = (0.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(
            result, torch.full_like(result, expected_val), atol=1e-5
        )

    def test_normalization_white(self):
        """Pixel 255 with calibrated normalization."""
        proc = MultiViewProcessor(target_size=(4, 4))
        views = [np.full((1, 4, 4, 3), 255, dtype=np.uint8) for _ in range(3)]
        result = proc.process_views(views)
        expected_val = (255.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(
            result, torch.full_like(result, expected_val), atol=1e-3
        )

    def test_normalization_midpoint(self):
        """Pixel 128 with calibrated normalization."""
        proc = MultiViewProcessor(target_size=(4, 4))
        views = [np.full((1, 4, 4, 3), 128, dtype=np.uint8) for _ in range(3)]
        result = proc.process_views(views)
        expected = (128.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(
            result, torch.full_like(result, expected), atol=1e-3
        )

    def test_normalization_not_standard(self):
        """Normalization must NOT use standard 0.5/0.5 or ImageNet values."""
        proc = MultiViewProcessor(target_size=(4, 4))
        views = [np.full((1, 4, 4, 3), 110, dtype=np.uint8) for _ in range(3)]
        result = proc.process_views(views)
        calibrated = (110.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(
            result, torch.full_like(result, calibrated), atol=1e-3
        )
        standard = (110.0 / 255.0 - 0.5) / 0.5
        assert not torch.allclose(
            result, torch.full_like(result, standard), atol=0.01
        )
        imagenet = (110.0 / 255.0 - 0.485) / 0.229
        assert not torch.allclose(
            result, torch.full_like(result, imagenet), atol=0.01
        )

    def test_resize_with_pad_identity(self):
        """Image already at target size -> no change."""
        proc = MultiViewProcessor(target_size=(8, 8))
        img = np.full((8, 8, 3), 100, dtype=np.uint8)
        out = proc.resize_with_pad(img)
        assert out.shape == (8, 8, 3)
        assert np.all(out == 100)

    def test_resize_with_pad_padding(self):
        """Narrower image gets zero-padded at top and bottom."""
        proc = MultiViewProcessor(target_size=(8, 8))
        img = np.full((6, 8, 3), 150, dtype=np.uint8)
        out = proc.resize_with_pad(img)
        assert out.shape == (8, 8, 3)
        assert np.all(out[0, :, :] == 0), "Top row should be zero-padded"
        assert np.all(out[7, :, :] == 0), "Bottom row should be zero-padded"
        assert np.all(out[1:7, :, :] == 150), "Middle rows should be image data"

    def test_resize_with_pad_downscale_shape(self):
        """Landscape image gets downscaled and padded."""
        proc = MultiViewProcessor(target_size=(8, 8))
        img = np.full((8, 16, 3), 200, dtype=np.uint8)
        out = proc.resize_with_pad(img)
        assert out.shape == (8, 8, 3)
        assert np.all(out[:2, :, :] == 0)
        assert np.all(out[6:, :, :] == 0)
        assert out[2:6, :, :].mean() > 0

    def test_channel_order(self):
        """Channels from 3 views appear in order."""
        proc = MultiViewProcessor(target_size=(4, 4))
        v0 = np.full((1, 4, 4, 3), 50, dtype=np.uint8)
        v1 = np.full((1, 4, 4, 3), 100, dtype=np.uint8)
        v2 = np.full((1, 4, 4, 3), 200, dtype=np.uint8)
        result = proc.process_views([v0, v1, v2])
        n0 = (50.0 / 255.0 - 0.4314) / 0.2353
        n1 = (100.0 / 255.0 - 0.4314) / 0.2353
        n2 = (200.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(result[0, :3], torch.full((3, 4, 4), n0), atol=1e-3)
        assert torch.allclose(result[0, 3:6], torch.full((3, 4, 4), n1), atol=1e-3)
        assert torch.allclose(result[0, 6:9], torch.full((3, 4, 4), n2), atol=1e-3)


# ---------------------------------------------------------------------------
# ReferenceMaskGenerator
# ---------------------------------------------------------------------------
class TestReferenceMaskGenerator:
    def test_single_ref_frame(self):
        gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        ref_mask, latent_mask = gen.generate_masks(9)
        assert ref_mask.shape == (9,)
        assert ref_mask[0].item() == 1.0
        assert ref_mask[1:].sum().item() == 0.0

    def test_latent_mask_shape(self):
        gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        _, lm = gen.generate_masks(9)
        assert lm.shape == (1, 3, 1, 1)
        assert lm[0, 0, 0, 0].item() == 1.0
        assert lm[0, 1:, 0, 0].sum().item() == 0.0

    def test_multiple_ref_frames(self):
        gen = ReferenceMaskGenerator(max_ref_frames=5, temporal_compression_factor=4)
        ref_mask, latent_mask = gen.generate_masks(17)
        assert ref_mask[:5].sum().item() == 5.0
        assert ref_mask[5:].sum().item() == 0.0
        assert latent_mask.shape == (1, 5, 1, 1)
        assert latent_mask[0, 0, 0, 0].item() == 1.0
        assert latent_mask[0, 1, 0, 0].item() == 1.0
        assert latent_mask[0, 2:, 0, 0].sum().item() == 0.0

    def test_ref_exceeds_frames(self):
        gen = ReferenceMaskGenerator(max_ref_frames=10, temporal_compression_factor=4)
        ref_mask, _ = gen.generate_masks(3)
        assert ref_mask.sum().item() == 3.0

    def test_apply_mask(self):
        gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        frames = torch.ones(5, 3, 4, 4)
        ref_mask = torch.tensor([1.0, 0.0, 0.0, 0.0, 0.0])
        result = gen.apply_mask(frames, ref_mask)
        assert torch.allclose(result[0], torch.ones(3, 4, 4))
        assert torch.allclose(result[1:], torch.zeros(4, 3, 4, 4))

    def test_latent_mask_factor2(self):
        gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=2)
        _, lm = gen.generate_masks(5)
        assert lm.shape == (1, 3, 1, 1)
        assert lm[0, 0, 0, 0].item() == 1.0


# ---------------------------------------------------------------------------
# AutoregressiveRollout
# ---------------------------------------------------------------------------
class TestAutoregressiveRollout:
    def test_chunk_planning_exact(self):
        rollout = AutoregressiveRollout(chunk_size=8)
        chunks = rollout.plan_chunks(33)
        assert chunks == [(0, 9), (8, 17), (16, 25), (24, 33)]

    def test_chunk_planning_remainder(self):
        rollout = AutoregressiveRollout(chunk_size=4)
        chunks = rollout.plan_chunks(10)
        assert chunks == [(0, 5), (4, 9), (8, 10)]

    def test_chunk_planning_single(self):
        rollout = AutoregressiveRollout(chunk_size=4)
        chunks = rollout.plan_chunks(5)
        assert chunks == [(0, 5)]

    def test_chunk_planning_minimal(self):
        rollout = AutoregressiveRollout(chunk_size=8)
        chunks = rollout.plan_chunks(2)
        assert chunks == [(0, 2)]

    def test_total_frames_consistency(self):
        for total in [5, 10, 17, 25, 33, 50]:
            for cs in [4, 8, 16]:
                rollout = AutoregressiveRollout(chunk_size=cs)
                chunks = rollout.plan_chunks(total)
                count = 1
                for i, (s, e) in enumerate(chunks):
                    num_gen = e - s - 1
                    if num_gen > 0:
                        count += num_gen
                assert count >= total, (
                    f"total={total}, cs={cs}: only {count} frames from {chunks}"
                )

    def test_execute_rollout_shape(self):
        from mock_model import mock_denoise

        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(3)
        mask_gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        rollout = AutoregressiveRollout(chunk_size=4)

        ref = torch.zeros(1, 9, 4, 4)
        result = rollout.execute_rollout(ref, 5, mock_denoise, sched, mask_gen)
        assert result.shape == (5, 9, 4, 4)

    def test_execute_rollout_reference_preserved(self):
        from mock_model import mock_denoise

        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(3)
        mask_gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        rollout = AutoregressiveRollout(chunk_size=4)

        ref = torch.full((1, 9, 4, 4), -1.0)
        result = rollout.execute_rollout(ref, 5, mock_denoise, sched, mask_gen)
        assert torch.allclose(result[0], ref.squeeze(0))

    def test_execute_rollout_deterministic(self):
        from mock_model import mock_denoise

        sched = FlowMatchScheduler(shift=5.0)
        mask_gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        rollout = AutoregressiveRollout(chunk_size=4)
        ref = torch.ones(1, 3, 4, 4) * 0.5

        sched.set_timesteps(5)
        r1 = rollout.execute_rollout(ref, 10, mock_denoise, sched, mask_gen)
        sched.set_timesteps(5)
        r2 = rollout.execute_rollout(ref, 10, mock_denoise, sched, mask_gen)
        assert torch.allclose(r1, r2)

    def test_execute_rollout_finite(self):
        from mock_model import mock_denoise

        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(10)
        mask_gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        rollout = AutoregressiveRollout(chunk_size=8)

        ref = torch.randn(1, 9, 8, 8)
        result = rollout.execute_rollout(ref, 17, mock_denoise, sched, mask_gen)
        assert torch.isfinite(result).all()

    def test_execute_rollout_multi_chunk_values(self):
        from mock_model import mock_denoise

        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(5)
        mask_gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        rollout = AutoregressiveRollout(chunk_size=4)

        ref = torch.zeros(1, 3, 4, 4)
        result = rollout.execute_rollout(ref, 10, mock_denoise, sched, mask_gen)
        chunk1_frame = result[4]
        chunk2_last = result[9]
        assert not torch.allclose(chunk1_frame, chunk2_last, atol=1e-3)

    def test_noise_seed_formula(self):
        """Verify the noise seeding produces correct output values.

        Manually replicate the first chunk's denoising with seed=42
        (from the formula chunk_idx*1337+42) and verify the pipeline
        matches this exact computation.
        """
        from mock_model import mock_denoise

        sched = FlowMatchScheduler(shift=5.0)
        sched.set_timesteps(2)
        mask_gen = ReferenceMaskGenerator(max_ref_frames=1, temporal_compression_factor=4)
        rollout = AutoregressiveRollout(chunk_size=4)

        ref = torch.zeros(1, 3, 2, 2)
        result = rollout.execute_rollout(ref, 3, mock_denoise, sched, mask_gen)

        # Manually compute expected output with correct seed (42 for chunk 0)
        gen = torch.Generator().manual_seed(0 * 1337 + 42)
        noise = torch.randn(2, 3, 2, 2, generator=gen)
        latents = noise.clone()

        num_steps = len(sched.sigmas) - 1
        for step_idx in range(num_steps):
            model_input = torch.cat([ref, latents], dim=0)
            velocity = mock_denoise(model_input, step_idx, ref)
            latents = sched.step(velocity[1:], step_idx, latents)

        assert torch.allclose(result[1], latents[0], atol=1e-5), \
            "First generated frame does not match expected noise seed computation"


# ---------------------------------------------------------------------------
# InferencePipeline (end-to-end)
# ---------------------------------------------------------------------------
class TestInferencePipeline:
    def test_output_shape(self):
        from mock_model import mock_denoise

        pipeline = InferencePipeline(
            denoise_fn=mock_denoise,
            shift=5.0,
            target_size=(8, 8),
            chunk_size=4,
            temporal_compression_factor=4,
        )
        views = [np.zeros((1, 8, 8, 3), dtype=np.uint8) for _ in range(3)]
        result = pipeline(views, num_inference_steps=3, total_frames=5)
        assert result.shape == (5, 9, 8, 8)

    def test_reference_frame_preserved(self):
        from mock_model import mock_denoise

        pipeline = InferencePipeline(
            denoise_fn=mock_denoise,
            shift=5.0,
            target_size=(4, 4),
            chunk_size=4,
            temporal_compression_factor=4,
        )
        views = [np.full((1, 4, 4, 3), 128, dtype=np.uint8) for _ in range(3)]
        result = pipeline(views, num_inference_steps=3, total_frames=5)
        expected_val = (128.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(
            result[0], torch.full((9, 4, 4), expected_val), atol=1e-3
        )

    def test_all_values_finite(self):
        from mock_model import mock_denoise

        pipeline = InferencePipeline(
            denoise_fn=mock_denoise,
            shift=5.0,
            target_size=(8, 8),
            chunk_size=8,
            temporal_compression_factor=4,
        )
        views = [
            np.random.RandomState(42 + i).randint(0, 256, (1, 12, 16, 3)).astype(
                np.uint8
            )
            for i in range(3)
        ]
        result = pipeline(views, num_inference_steps=10, total_frames=17)
        assert result.shape == (17, 9, 8, 8)
        assert torch.isfinite(result).all()

    def test_deterministic(self):
        from mock_model import mock_denoise

        def run():
            p = InferencePipeline(
                denoise_fn=mock_denoise,
                shift=5.0,
                target_size=(4, 4),
                chunk_size=4,
                temporal_compression_factor=4,
            )
            views = [np.full((1, 4, 4, 3), 64, dtype=np.uint8) for _ in range(3)]
            return p(views, num_inference_steps=5, total_frames=9)

        r1 = run()
        r2 = run()
        assert torch.allclose(r1, r2)

    def test_with_conditioning(self):
        from mock_model import mock_denoise

        pipeline = InferencePipeline(
            denoise_fn=mock_denoise,
            shift=5.0,
            target_size=(4, 4),
            chunk_size=4,
            temporal_compression_factor=4,
        )
        ref_views = [np.zeros((1, 4, 4, 3), dtype=np.uint8) for _ in range(3)]
        depth_views = [
            np.full((5, 4, 4, 3), 128, dtype=np.uint8) for _ in range(3)
        ]
        replay_views = [
            np.full((5, 4, 4, 3), 200, dtype=np.uint8) for _ in range(3)
        ]
        result = pipeline(
            ref_views, num_inference_steps=3, total_frames=5,
            depth_views=depth_views, replay_views=replay_views,
        )
        assert result.shape == (5, 9, 4, 4)
        assert torch.isfinite(result).all()

    def test_conditioning_affects_output(self):
        from mock_model import mock_denoise

        def make_pipeline():
            return InferencePipeline(
                denoise_fn=mock_denoise,
                shift=5.0,
                target_size=(4, 4),
                chunk_size=4,
                temporal_compression_factor=4,
            )

        ref_views = [np.zeros((1, 4, 4, 3), dtype=np.uint8) for _ in range(3)]
        depth_views = [
            np.full((5, 4, 4, 3), 200, dtype=np.uint8) for _ in range(3)
        ]

        p1 = make_pipeline()
        r_no_cond = p1(ref_views, num_inference_steps=3, total_frames=5)

        p2 = make_pipeline()
        r_with_cond = p2(
            ref_views, num_inference_steps=3, total_frames=5,
            depth_views=depth_views,
        )

        assert not torch.allclose(r_no_cond[1:], r_with_cond[1:], atol=1e-4)

    def test_different_shifts(self):
        from mock_model import mock_denoise

        ref_views = [np.full((1, 4, 4, 3), 100, dtype=np.uint8) for _ in range(3)]

        p1 = InferencePipeline(
            denoise_fn=mock_denoise, shift=1.0,
            target_size=(4, 4), chunk_size=4, temporal_compression_factor=4,
        )
        r1 = p1(ref_views, num_inference_steps=5, total_frames=5)

        p2 = InferencePipeline(
            denoise_fn=mock_denoise, shift=5.0,
            target_size=(4, 4), chunk_size=4, temporal_compression_factor=4,
        )
        r2 = p2(ref_views, num_inference_steps=5, total_frames=5)

        assert torch.allclose(r1[0], r2[0], atol=1e-5)
        assert not torch.allclose(r1[1:], r2[1:], atol=1e-4)

    def test_reference_normalization_value(self):
        """End-to-end check that calibrated normalization is applied."""
        from mock_model import mock_denoise

        pipeline = InferencePipeline(
            denoise_fn=mock_denoise,
            shift=5.0,
            target_size=(4, 4),
            chunk_size=4,
            temporal_compression_factor=4,
        )
        views = [np.zeros((1, 4, 4, 3), dtype=np.uint8) for _ in range(3)]
        result = pipeline(views, num_inference_steps=3, total_frames=2)

        expected_val = (0.0 / 255.0 - 0.4314) / 0.2353
        assert torch.allclose(
            result[0], torch.full((9, 4, 4), expected_val), atol=1e-3
        )
        assert not torch.allclose(
            result[0], torch.full((9, 4, 4), -1.0), atol=0.01
        )
