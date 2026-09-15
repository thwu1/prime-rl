
"""
Verification tests for the world model inference pipeline.

Tests cover: pipeline module correctness, WME binary parsing, multi-view
geometry, chunk scheduling, adaptive parameter computation, SQLite plan
database, pipeline validation harness, and ZMQ server integration.
"""

import sys
import os
import shutil
import tempfile
import sqlite3
import struct
import zlib
import math
import json
import subprocess
import time

import numpy as np
import pytest
import yaml
import zmq

sys.path.insert(0, "/app")


# ═══════════════════════════════════════════════════════════════════════
# 1. Pipeline Module Verification
# ═══════════════════════════════════════════════════════════════════════

class TestPipelineScheduler:
    """Verify shifted sigma schedule computation."""

    def test_sigma_values_shift5(self):
        from pipeline.scheduler import compute_sigmas
        sigmas = compute_sigmas(10, 5.0)
        expected = [
            1.0, 0.9782608695652174, 0.9523809523809524,
            0.9210526315789474, 0.8823529411764706,
            0.8333333333333334, 0.7692307692307693,
            0.6818181818181818, 0.5555555555555556,
            0.35714285714285715,
        ]
        np.testing.assert_allclose(sigmas, expected, atol=1e-12)

    def test_shift1_is_linear(self):
        """When shift=1, schedule reduces to linear sigma = t."""
        from pipeline.scheduler import compute_sigmas
        sigmas = compute_sigmas(5, 1.0)
        expected = np.linspace(1.0, 0.2, 5)
        np.testing.assert_allclose(sigmas, expected, atol=1e-12)

    def test_shift_increases_sigmas(self):
        """Higher shift pushes sigma values toward 1."""
        from pipeline.scheduler import compute_sigmas
        s1 = compute_sigmas(10, 1.0)
        s5 = compute_sigmas(10, 5.0)
        for a, b in zip(s5, s1):
            assert a >= b - 1e-10


class TestPipelineLatentGeometry:
    """Verify VAE latent dimension computation."""

    def test_standard_shape(self):
        from pipeline.geometry import compute_latent_shape
        assert compute_latent_shape(9, 224, 224, 4, 8) == (3, 28, 28)

    def test_temporal_ceiling_division(self):
        """Temporal dim uses ceiling: (F-1)//f_t + 1, not floor F//f_t."""
        from pipeline.geometry import compute_latent_shape
        assert compute_latent_shape(10, 224, 224, 4, 8)[0] == 3
        assert compute_latent_shape(5, 224, 224, 4, 8)[0] == 2
        assert compute_latent_shape(1, 224, 224, 4, 8)[0] == 1

    def test_single_frame(self):
        """One frame must produce one latent temporal position."""
        from pipeline.geometry import compute_latent_shape
        assert compute_latent_shape(1, 64, 64, 4, 8)[0] == 1


class TestPipelineConditioning:
    """Verify reference-frame conditioning mask convention."""

    def test_ref_frame_is_zero(self):
        """Reference indices produce mask=0 (condition kept)."""
        from pipeline.conditioning import build_conditioning_mask
        mask = build_conditioning_mask(3, [0])
        assert mask[0] == 0.0

    def test_generated_frames_are_one(self):
        """Non-reference positions produce mask=1 (noise/generate)."""
        from pipeline.conditioning import build_conditioning_mask
        mask = build_conditioning_mask(3, [0])
        np.testing.assert_array_equal(mask, [0.0, 1.0, 1.0])

    def test_blend_preserves_condition_at_ref(self):
        """mask=0 keeps condition, mask=1 keeps noise."""
        from pipeline.conditioning import blend_conditioning
        result = blend_conditioning(
            np.array([1.0, 2.0, 3.0]),
            np.array([10.0, 20.0, 30.0]),
            np.array([0.0, 1.0, 0.0]),
        )
        np.testing.assert_allclose(result, [10.0, 2.0, 30.0])


class TestPipelineNormalization:
    """Verify per-channel latent normalization."""

    def test_normalize_divides_by_std(self):
        from pipeline.normalization import normalize_latents
        result = normalize_latents(
            np.array([1.0, 2.0, 3.0]),
            np.array([0.5, 1.0, 1.5]),
            np.array([2.0, 3.0, 4.0]),
        )
        expected = [0.25, 1.0 / 3.0, 0.375]
        np.testing.assert_allclose(result, expected, atol=1e-12)

    def test_roundtrip_identity(self):
        from pipeline.normalization import normalize_latents, denormalize_latents
        x = np.array([1.0, 2.0, 3.0])
        mean = np.array([0.5, 1.0, 1.5])
        std = np.array([2.0, 3.0, 4.0])
        recovered = denormalize_latents(normalize_latents(x, mean, std), mean, std)
        np.testing.assert_allclose(recovered, x, atol=1e-12)

    def test_denormalize_values(self):
        from pipeline.normalization import denormalize_latents
        result = denormalize_latents(
            np.array([0.25, 1.0 / 3.0, 0.375]),
            np.array([0.5, 1.0, 1.5]),
            np.array([2.0, 3.0, 4.0]),
        )
        np.testing.assert_allclose(result, [1.0, 2.0, 3.0], atol=1e-12)


class TestPipelineCFG:
    """Verify classifier-free guidance formula."""

    def test_cfg_formula_exact(self):
        from pipeline.inference import apply_cfg
        result = apply_cfg(np.array([1.0, 2.0]), np.array([3.0, 4.0]), 7.5)
        np.testing.assert_allclose(result, [16.0, 17.0], atol=1e-12)

    def test_cfg_scale_one_recovers_cond(self):
        """w=1 should give the conditional prediction."""
        from pipeline.inference import apply_cfg
        result = apply_cfg(np.array([1.0, 2.0]), np.array([3.0, 4.0]), 1.0)
        np.testing.assert_allclose(result, [3.0, 4.0], atol=1e-12)

    def test_cfg_scale_zero_recovers_uncond(self):
        """w=0 should give the unconditional prediction."""
        from pipeline.inference import apply_cfg
        result = apply_cfg(np.array([1.0, 2.0]), np.array([3.0, 4.0]), 0.0)
        np.testing.assert_allclose(result, [1.0, 2.0], atol=1e-12)


class TestPipelineTwoStage:
    """Verify two-stage schedule splitting."""

    def test_boundary_position(self):
        from pipeline.inference import split_two_stage
        sigmas = np.linspace(1.0, 0.1, 10)
        s1, s2 = split_two_stage(sigmas, 0.3)
        assert len(s1) == 3
        assert len(s2) == 7

    def test_stages_concatenate_to_full(self):
        from pipeline.inference import split_two_stage
        sigmas = np.linspace(1.0, 0.1, 10)
        s1, s2 = split_two_stage(sigmas, 0.3)
        np.testing.assert_allclose(np.concatenate([s1, s2]), sigmas, atol=1e-12)

    def test_boundary_not_off_by_one(self):
        """Boundary = floor(N*ratio), not floor(N*ratio)+1."""
        from pipeline.inference import split_two_stage
        sigmas = np.arange(10, dtype=float)
        s1, _ = split_two_stage(sigmas, 0.3)
        assert len(s1) == 3


class TestPipelineEndToEnd:
    """Verify the full pipeline integration with all modules."""

    def test_full_pipeline_run(self):
        from pipeline.inference import run_pipeline
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        with open("/app/reference/expected.json") as f:
            ref = json.load(f)
        traj = np.zeros((50, 14))
        traj[:, 6] = 0.035
        traj[:, 13] = 0.069
        traj[0, 0] = 0.1
        traj[2, 0] = 0.3
        episode = {"trajectory": traj, "num_video_frames": 50}
        out = run_pipeline(episode, config)
        np.testing.assert_allclose(out["sigmas"], ref["sigmas"], atol=1e-6)
        assert list(out["latent_shape"]) == ref["latent_shape"]
        np.testing.assert_allclose(
            out["latent_conditioning_mask"], ref["latent_mask"], atol=1e-8
        )
        np.testing.assert_allclose(
            out["frame_conditioning_mask"], ref["frame_mask"], atol=1e-8
        )
        assert len(out["stage1_sigmas"]) == ref["stage_boundary"]
        np.testing.assert_array_equal(out["frame_indices"], ref["frame_indices"])


class TestValidateHarness:
    """Run the standalone validation harness and verify all checks pass."""

    def test_all_13_checks_pass(self):
        result = subprocess.run(
            ["python3", "/app/validate.py"],
            capture_output=True, text=True, cwd="/app",
        )
        assert result.returncode == 0, (
            f"Pipeline validation failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "13/13" in result.stdout


# ═══════════════════════════════════════════════════════════════════════
# 2. WME Binary Parser
# ═══════════════════════════════════════════════════════════════════════

class TestWMEParserEpisode1:
    """Parse episode_001.wme and verify header, views, and trajectory."""

    def test_header_fields(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert ep["version"] == 1
        assert ep["num_frames"] == 100
        assert ep["num_views"] == 3
        assert ep["trajectory_dim"] == 14
        assert ep["fps"] == 30

    def test_view_count(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert len(ep["views"]) == 3

    def test_view_names(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert ep["views"][0]["name"] == "cam_high"
        assert ep["views"][1]["name"] == "cam_left_wrist"
        assert ep["views"][2]["name"] == "cam_right_wrist"

    def test_view_dimensions(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert ep["views"][0]["width"] == 640
        assert ep["views"][0]["height"] == 480
        assert ep["views"][1]["width"] == 224
        assert ep["views"][1]["height"] == 224
        assert ep["views"][2]["width"] == 224
        assert ep["views"][2]["height"] == 224

    def test_view_intrinsics(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        v0 = ep["views"][0]
        assert abs(v0["fx"] - 500.0) < 1e-4
        assert abs(v0["fy"] - 500.0) < 1e-4
        assert abs(v0["cx"] - 320.0) < 1e-4
        assert abs(v0["cy"] - 240.0) < 1e-4

    def test_trajectory_shape(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert ep["trajectory"].shape == (100, 14)

    def test_trajectory_dtype(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert ep["trajectory"].dtype in (np.float32, np.float64)

    def test_trajectory_gripper_columns(self):
        """Gripper columns (6, 13) should be constant."""
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        traj = ep["trajectory"]
        np.testing.assert_allclose(traj[:, 6], 0.035, atol=1e-6)
        np.testing.assert_allclose(traj[:, 13], 0.069, atol=1e-6)

    def test_trajectory_first_row(self):
        """First frame: columns 0-5 are sine values, column 0 = sin(0) = 0."""
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_001.wme")
        assert abs(ep["trajectory"][0, 0]) < 1e-6


class TestWMEParserEpisode2:
    """Parse episode_002.wme and verify header and views."""

    def test_header_fields(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_002.wme")
        assert ep["version"] == 1
        assert ep["num_frames"] == 37
        assert ep["num_views"] == 2
        assert ep["trajectory_dim"] == 14
        assert ep["fps"] == 15

    def test_view_names(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_002.wme")
        assert ep["views"][0]["name"] == "cam_high"
        assert ep["views"][1]["name"] == "cam_front"

    def test_view_dimensions(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_002.wme")
        assert ep["views"][1]["width"] == 480
        assert ep["views"][1]["height"] == 360

    def test_trajectory_shape(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_002.wme")
        assert ep["trajectory"].shape == (37, 14)

    def test_trajectory_gripper_columns(self):
        from orchestrator import parse_wme
        ep = parse_wme("/app/episodes/episode_002.wme")
        np.testing.assert_allclose(ep["trajectory"][:, 6], 0.04, atol=1e-6)
        np.testing.assert_allclose(ep["trajectory"][:, 13], 0.05, atol=1e-6)


class TestWMECRC:
    """CRC32 validation must reject corrupted files."""

    def test_corrupt_byte_raises(self):
        from orchestrator import parse_wme
        tmp = tempfile.mktemp(suffix=".wme")
        try:
            shutil.copy("/app/episodes/episode_001.wme", tmp)
            with open(tmp, "r+b") as f:
                f.seek(10)
                original = f.read(1)
                f.seek(10)
                f.write(bytes([original[0] ^ 0xFF]))
            with pytest.raises((ValueError, Exception)):
                parse_wme(tmp)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_truncated_file_raises(self):
        from orchestrator import parse_wme
        tmp = tempfile.mktemp(suffix=".wme")
        try:
            with open("/app/episodes/episode_001.wme", "rb") as f:
                data = f.read()
            with open(tmp, "wb") as f:
                f.write(data[:32])
            with pytest.raises(Exception):
                parse_wme(tmp)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


# ═══════════════════════════════════════════════════════════════════════
# 3. Multi-View Geometry
# ═══════════════════════════════════════════════════════════════════════

class TestMultiviewGeometryEpisode1:
    """3 views: 480x640, 224x224, 224x224."""

    @pytest.fixture
    def geometry(self):
        from orchestrator import parse_wme, compute_multiview_geometry
        ep = parse_wme("/app/episodes/episode_001.wme")
        return compute_multiview_geometry(ep["views"], 4, 8)

    def test_padded_height(self, geometry):
        assert geometry["padded_height"] == 480

    def test_total_width(self, geometry):
        assert geometry["total_width"] == 1088

    def test_view_crop_count(self, geometry):
        assert len(geometry["view_crops"]) == 3

    def test_view0_pixel_crops(self, geometry):
        v0 = geometry["view_crops"][0]
        assert v0["pixel_w_start"] == 0
        assert v0["pixel_w_end"] == 640
        assert v0["pixel_h_content"] == 480

    def test_view1_pixel_crops(self, geometry):
        v1 = geometry["view_crops"][1]
        assert v1["pixel_w_start"] == 640
        assert v1["pixel_w_end"] == 864
        assert v1["pixel_h_content"] == 224

    def test_view2_pixel_crops(self, geometry):
        v2 = geometry["view_crops"][2]
        assert v2["pixel_w_start"] == 864
        assert v2["pixel_w_end"] == 1088
        assert v2["pixel_h_content"] == 224

    def test_view0_latent_crops(self, geometry):
        v0 = geometry["view_crops"][0]
        assert v0["latent_w_start"] == 0
        assert v0["latent_w_end"] == 80
        assert v0["latent_h_content"] == 60

    def test_view1_latent_crops(self, geometry):
        v1 = geometry["view_crops"][1]
        assert v1["latent_w_start"] == 80
        assert v1["latent_w_end"] == 108
        assert v1["latent_h_content"] == 28

    def test_view2_latent_crops(self, geometry):
        v2 = geometry["view_crops"][2]
        assert v2["latent_w_start"] == 108
        assert v2["latent_w_end"] == 136
        assert v2["latent_h_content"] == 28


class TestMultiviewGeometryEpisode2:
    """2 views: 480x640, 360x480."""

    @pytest.fixture
    def geometry(self):
        from orchestrator import parse_wme, compute_multiview_geometry
        ep = parse_wme("/app/episodes/episode_002.wme")
        return compute_multiview_geometry(ep["views"], 4, 8)

    def test_padded_height(self, geometry):
        assert geometry["padded_height"] == 480

    def test_total_width(self, geometry):
        assert geometry["total_width"] == 1120

    def test_view1_latent_crops(self, geometry):
        v1 = geometry["view_crops"][1]
        assert v1["latent_w_start"] == 80
        assert v1["latent_w_end"] == 140
        assert v1["latent_h_content"] == 45


class TestMultiviewGeometryNonMultiple:
    """Views with dimensions not divisible by spatial_factor."""

    def test_rounding_up(self):
        from orchestrator import compute_multiview_geometry
        views = [
            {"name": "v1", "width": 500, "height": 300,
             "fx": 1.0, "fy": 1.0, "cx": 1.0, "cy": 1.0},
            {"name": "v2", "width": 200, "height": 250,
             "fx": 1.0, "fy": 1.0, "cx": 1.0, "cy": 1.0},
        ]
        geo = compute_multiview_geometry(views, 4, 8)
        assert geo["padded_height"] == 304
        assert geo["total_width"] == 704
        assert geo["view_crops"][0]["latent_w_start"] == 0
        assert geo["view_crops"][0]["latent_w_end"] == 63
        assert geo["view_crops"][1]["latent_w_start"] == 63
        assert geo["view_crops"][1]["latent_w_end"] == 88
        assert geo["view_crops"][0]["latent_h_content"] == 37
        assert geo["view_crops"][1]["latent_h_content"] == 31


class TestMultiviewGeometrySingleView:
    """Edge case: single view."""

    def test_single_view(self):
        from orchestrator import compute_multiview_geometry
        views = [
            {"name": "main", "width": 640, "height": 480,
             "fx": 1.0, "fy": 1.0, "cx": 1.0, "cy": 1.0},
        ]
        geo = compute_multiview_geometry(views, 4, 8)
        assert geo["padded_height"] == 480
        assert geo["total_width"] == 640
        assert len(geo["view_crops"]) == 1
        assert geo["view_crops"][0]["pixel_w_start"] == 0
        assert geo["view_crops"][0]["pixel_w_end"] == 640


# ═══════════════════════════════════════════════════════════════════════
# 4. Chunk Scheduling
# ═══════════════════════════════════════════════════════════════════════

class TestChunkSchedulingEpisode1:
    """100 frames, stride=2 -> 50 sampled -> 6 chunks after merge."""

    @pytest.fixture
    def chunks_and_config(self):
        from orchestrator import parse_wme, compute_multiview_geometry, plan_chunks
        ep = parse_wme("/app/episodes/episode_001.wme")
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        geo = compute_multiview_geometry(ep["views"], 4, 8)
        chunks = plan_chunks(ep["trajectory"], config,
                             geo["padded_height"], geo["total_width"])
        return chunks, config

    def test_num_chunks(self, chunks_and_config):
        chunks, _ = chunks_and_config
        assert len(chunks) == 6

    def test_chunk_indices_sequential(self, chunks_and_config):
        chunks, _ = chunks_and_config
        for i, c in enumerate(chunks):
            assert c["chunk_index"] == i

    def test_chunk0_range(self, chunks_and_config):
        chunks, _ = chunks_and_config
        assert chunks[0]["sample_start"] == 0
        assert chunks[0]["sample_end"] == 9
        assert chunks[0]["num_sampled_frames"] == 9

    def test_chunk1_range(self, chunks_and_config):
        chunks, _ = chunks_and_config
        assert chunks[1]["sample_start"] == 8
        assert chunks[1]["sample_end"] == 17

    def test_last_chunk_merged(self, chunks_and_config):
        """Last chunk should extend to cover remaining 2 frames (merged)."""
        chunks, _ = chunks_and_config
        last = chunks[-1]
        assert last["sample_start"] == 40
        assert last["sample_end"] == 50
        assert last["num_sampled_frames"] == 10

    def test_overlap_between_consecutive(self, chunks_and_config):
        """Each consecutive pair shares exactly 1 sampled frame."""
        chunks, _ = chunks_and_config
        for i in range(len(chunks) - 1):
            overlap = chunks[i]["sample_end"] - chunks[i + 1]["sample_start"]
            assert overlap == 1, f"Overlap between chunk {i} and {i+1}: {overlap}"

    def test_full_coverage(self, chunks_and_config):
        """All 50 sampled frames must be covered by at least one chunk."""
        chunks, _ = chunks_and_config
        covered = set()
        for c in chunks:
            for s in range(c["sample_start"], c["sample_end"]):
                covered.add(s)
        assert covered == set(range(50))

    def test_adaptive_steps_bounds(self, chunks_and_config):
        chunks, config = chunks_and_config
        for c in chunks:
            assert 6 <= c["num_steps"] <= 20

    def test_flow_shift_lower_bound(self, chunks_and_config):
        chunks, config = chunks_and_config
        for c in chunks:
            assert c["flow_shift"] >= 3.0

    def test_stage_boundary_formula(self, chunks_and_config):
        chunks, config = chunks_and_config
        for c in chunks:
            expected = int(c["num_steps"] * 0.3)
            assert c["stage_boundary"] == expected

    def test_action_variance_nonnegative(self, chunks_and_config):
        chunks, _ = chunks_and_config
        for c in chunks:
            assert c["action_variance"] >= 0.0

    def test_latent_dims_standard_chunks(self, chunks_and_config):
        """Chunks with 9 frames: latent_t = (9-1)//4+1 = 3."""
        chunks, _ = chunks_and_config
        for c in chunks[:5]:
            assert c["latent_t"] == 3
        assert chunks[0]["latent_h"] == 60
        assert chunks[0]["latent_w"] == 136

    def test_latent_t_merged_chunk(self, chunks_and_config):
        """Merged chunk has 10 frames: latent_t = (10-1)//4+1 = 3."""
        chunks, _ = chunks_and_config
        assert chunks[-1]["latent_t"] == 3

    def test_frame_indices_chunk0(self, chunks_and_config):
        """Chunk 0 frame indices: [0, 2, 4, 6, 8, 10, 12, 14, 16]."""
        chunks, _ = chunks_and_config
        expected = np.array([0, 2, 4, 6, 8, 10, 12, 14, 16])
        np.testing.assert_array_equal(chunks[0]["frame_indices"], expected)


class TestChunkSchedulingEpisode2:
    """37 frames, stride=2 -> 19 sampled -> 3 chunks (no merge)."""

    @pytest.fixture
    def chunks_and_config(self):
        from orchestrator import parse_wme, compute_multiview_geometry, plan_chunks
        ep = parse_wme("/app/episodes/episode_002.wme")
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        geo = compute_multiview_geometry(ep["views"], 4, 8)
        chunks = plan_chunks(ep["trajectory"], config,
                             geo["padded_height"], geo["total_width"])
        return chunks, config

    def test_num_chunks(self, chunks_and_config):
        chunks, _ = chunks_and_config
        assert len(chunks) == 3

    def test_last_chunk_not_merged(self, chunks_and_config):
        """Last chunk has 3 frames (>= min_chunk_frames), no merge."""
        chunks, _ = chunks_and_config
        assert chunks[-1]["num_sampled_frames"] == 3

    def test_last_chunk_latent_t(self, chunks_and_config):
        """3 frames: latent_t = (3-1)//4+1 = 1."""
        chunks, _ = chunks_and_config
        assert chunks[-1]["latent_t"] == 1

    def test_latent_w_episode2(self, chunks_and_config):
        """Episode 2 total_width=1120, latent_w=140."""
        chunks, _ = chunks_and_config
        assert chunks[0]["latent_w"] == 140

    def test_full_coverage(self, chunks_and_config):
        chunks, _ = chunks_and_config
        covered = set()
        for c in chunks:
            for s in range(c["sample_start"], c["sample_end"]):
                covered.add(s)
        assert covered == set(range(19))


# ═══════════════════════════════════════════════════════════════════════
# 5. Adaptive Parameter Exact Values (hand-crafted example)
# ═══════════════════════════════════════════════════════════════════════

class TestAdaptiveParametersExact:
    """Verify adaptive formulas with a hand-crafted trajectory."""

    def test_exact_values(self):
        from orchestrator import plan_chunks
        traj = np.array([
            [1.0, 2.0, 3.0, 4.0],
            [1.5, 2.5, 3.5, 4.5],
            [2.0, 3.0, 4.0, 5.0],
            [2.5, 3.5, 4.5, 5.5],
            [3.0, 4.0, 5.0, 6.0],
            [3.5, 4.5, 5.5, 6.5],
            [4.0, 5.0, 6.0, 7.0],
            [4.5, 5.5, 6.5, 7.5],
            [5.0, 6.0, 7.0, 8.0],
        ], dtype=np.float32)
        config = {
            "pipeline": {
                "min_steps": 6, "max_steps": 20,
                "base_shift": 3.0, "shift_sensitivity": 2.0,
                "var_scale": 0.5, "boundary_ratio": 0.3,
            },
            "video": {
                "chunk_size": 9, "overlap": 1,
                "stride": 1, "start": 0, "min_chunk_frames": 3,
            },
            "vae": {"temporal_factor": 4, "spatial_factor": 8},
        }
        chunks = plan_chunks(traj, config, 480, 640)
        assert len(chunks) == 1
        c = chunks[0]

        expected_var = 5.0 / 3.0
        np.testing.assert_allclose(c["action_variance"], expected_var, atol=1e-4)

        normalized = min(expected_var / 0.5, 1.0)
        assert normalized == 1.0

        expected_shift = 3.0 * (1.0 + 2.0 * 1.0)
        np.testing.assert_allclose(c["flow_shift"], expected_shift, atol=1e-6)

        expected_steps = 20
        assert c["num_steps"] == expected_steps

        expected_boundary = int(20 * 0.3)
        assert c["stage_boundary"] == expected_boundary

    def test_low_variance_example(self):
        from orchestrator import plan_chunks
        traj = np.ones((9, 4), dtype=np.float32) * 3.0
        config = {
            "pipeline": {
                "min_steps": 6, "max_steps": 20,
                "base_shift": 3.0, "shift_sensitivity": 2.0,
                "var_scale": 0.5, "boundary_ratio": 0.3,
            },
            "video": {
                "chunk_size": 9, "overlap": 1,
                "stride": 1, "start": 0, "min_chunk_frames": 3,
            },
            "vae": {"temporal_factor": 4, "spatial_factor": 8},
        }
        chunks = plan_chunks(traj, config, 480, 640)
        c = chunks[0]
        assert abs(c["action_variance"]) < 1e-12
        assert c["flow_shift"] == 3.0
        assert c["num_steps"] == 6
        assert c["stage_boundary"] == int(6 * 0.3)


# ═══════════════════════════════════════════════════════════════════════
# 6. SQLite Plan Database
# ═══════════════════════════════════════════════════════════════════════

class TestDatabaseSchema:
    """Verify the database has the correct tables and columns."""

    @pytest.fixture
    def db_path(self, tmp_path):
        from orchestrator import build_plan_database
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        db = str(tmp_path / "plan.db")
        eps = sorted([
            "/app/episodes/episode_001.wme",
            "/app/episodes/episode_002.wme",
        ])
        build_plan_database(eps, config, db)
        return db

    def test_tables_exist(self, db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        assert "episodes" in tables
        assert "views" in tables
        assert "chunks" in tables
        assert "geometry" in tables
        assert "view_crops" in tables

    def test_episode_count(self, db_path):
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        conn.close()
        assert count == 2

    def test_view_count(self, db_path):
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM views").fetchone()[0]
        conn.close()
        assert count == 5

    def test_chunk_count(self, db_path):
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.close()
        assert count == 9

    def test_geometry_count(self, db_path):
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM geometry").fetchone()[0]
        conn.close()
        assert count == 2

    def test_view_crops_count(self, db_path):
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM view_crops").fetchone()[0]
        conn.close()
        assert count == 5


class TestDatabaseContent:
    """Verify specific data in the plan database."""

    @pytest.fixture
    def conn(self, tmp_path):
        from orchestrator import build_plan_database
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        db = str(tmp_path / "plan.db")
        eps = sorted([
            "/app/episodes/episode_001.wme",
            "/app/episodes/episode_002.wme",
        ])
        build_plan_database(eps, config, db)
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        yield c
        c.close()

    def test_episode1_metadata(self, conn):
        row = conn.execute(
            "SELECT * FROM episodes WHERE filepath LIKE '%episode_001%'"
        ).fetchone()
        assert row is not None
        assert row["num_frames"] == 100
        assert row["num_views"] == 3
        assert row["trajectory_dim"] == 14
        assert row["fps"] == 30

    def test_episode2_metadata(self, conn):
        row = conn.execute(
            "SELECT * FROM episodes WHERE filepath LIKE '%episode_002%'"
        ).fetchone()
        assert row is not None
        assert row["num_frames"] == 37
        assert row["num_views"] == 2
        assert row["fps"] == 15

    def test_episode1_views(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_001%'"
        ).fetchone()
        views = conn.execute(
            "SELECT * FROM views WHERE episode_id=? ORDER BY view_index",
            (ep["id"],)
        ).fetchall()
        assert len(views) == 3
        assert views[0]["name"] == "cam_high"
        assert views[0]["width"] == 640
        assert views[1]["name"] == "cam_left_wrist"

    def test_episode1_chunk_count(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_001%'"
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE episode_id=?",
            (ep["id"],)
        ).fetchone()[0]
        assert count == 6

    def test_episode1_last_chunk_merged(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_001%'"
        ).fetchone()
        last = conn.execute(
            "SELECT * FROM chunks WHERE episode_id=? ORDER BY chunk_index DESC LIMIT 1",
            (ep["id"],)
        ).fetchone()
        assert last["sample_start"] == 40
        assert last["sample_end"] == 50
        assert last["num_sampled_frames"] == 10

    def test_episode2_chunk_count(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_002%'"
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE episode_id=?",
            (ep["id"],)
        ).fetchone()[0]
        assert count == 3

    def test_episode1_geometry(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_001%'"
        ).fetchone()
        geo = conn.execute(
            "SELECT * FROM geometry WHERE episode_id=?",
            (ep["id"],)
        ).fetchone()
        assert geo["padded_height"] == 480
        assert geo["total_width"] == 1088
        assert geo["num_views"] == 3

    def test_episode2_geometry(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_002%'"
        ).fetchone()
        geo = conn.execute(
            "SELECT * FROM geometry WHERE episode_id=?",
            (ep["id"],)
        ).fetchone()
        assert geo["padded_height"] == 480
        assert geo["total_width"] == 1120

    def test_episode1_view_crops(self, conn):
        ep = conn.execute(
            "SELECT id FROM episodes WHERE filepath LIKE '%episode_001%'"
        ).fetchone()
        crops = conn.execute(
            "SELECT * FROM view_crops WHERE episode_id=? ORDER BY view_index",
            (ep["id"],)
        ).fetchall()
        assert len(crops) == 3
        assert crops[0]["pixel_w_start"] == 0
        assert crops[0]["pixel_w_end"] == 640
        assert crops[0]["latent_w_end"] == 80
        assert crops[1]["pixel_w_start"] == 640
        assert crops[1]["latent_w_start"] == 80
        assert crops[1]["latent_h_content"] == 28
        assert crops[2]["latent_w_end"] == 136

    def test_chunk_steps_within_bounds(self, conn):
        rows = conn.execute("SELECT num_steps FROM chunks").fetchall()
        for row in rows:
            assert 6 <= row["num_steps"] <= 20

    def test_chunk_flow_shift_lower_bound(self, conn):
        rows = conn.execute("SELECT flow_shift FROM chunks").fetchall()
        for row in rows:
            assert row["flow_shift"] >= 3.0

    def test_chunk_stage_boundary_consistency(self, conn):
        rows = conn.execute(
            "SELECT num_steps, stage_boundary FROM chunks"
        ).fetchall()
        for row in rows:
            expected = int(row["num_steps"] * 0.3)
            assert row["stage_boundary"] == expected


# ═══════════════════════════════════════════════════════════════════════
# 7. Integration — run as script
# ═══════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Run the orchestrator as a script and verify the output database."""

    def test_script_execution(self, tmp_path):
        db_path = str(tmp_path / "plan.db")
        result = subprocess.run(
            ["python3", "-c",
             f"""
import sys, yaml, glob, os
sys.path.insert(0, '/app')
from orchestrator import build_plan_database
with open('/app/config.yaml') as f:
    config = yaml.safe_load(f)
eps = sorted(glob.glob('/app/episodes/*.wme'))
build_plan_database(eps, config, '{db_path}')
"""],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        assert os.path.exists(db_path)

        conn = sqlite3.connect(db_path)
        ep_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.close()
        assert ep_count == 2
        assert chunk_count == 9

    def test_idempotent_rebuild(self, tmp_path):
        """Building twice to same path should produce valid database."""
        from orchestrator import build_plan_database
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        db = str(tmp_path / "plan.db")
        eps = sorted([
            "/app/episodes/episode_001.wme",
            "/app/episodes/episode_002.wme",
        ])
        build_plan_database(eps, config, db)
        os.remove(db)
        build_plan_database(eps, config, db)
        conn = sqlite3.connect(db)
        assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 2
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 8. ZMQ Server
# ═══════════════════════════════════════════════════════════════════════

class TestZMQServer:
    """Verify the ZMQ plan server serves correct JSON responses."""

    def test_server_integration(self, tmp_path):
        """Start server, query via ZMQ REQ, verify JSON responses."""
        import glob as g

        # Build plan database
        from orchestrator import build_plan_database
        with open("/app/config.yaml") as f:
            config = yaml.safe_load(f)
        eps = sorted(g.glob("/app/episodes/*.wme"))
        db_path = str(tmp_path / "plan.db")
        build_plan_database(eps, config, db_path)

        # Start server in background
        port = 15557
        proc = subprocess.Popen(
            ["python3", "/app/server.py", "--db", db_path, "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        try:
            time.sleep(2.0)
            assert proc.poll() is None, (
                f"Server exited prematurely: {proc.stderr.read().decode()}"
            )

            def query(request, timeout_ms=5000):
                ctx = zmq.Context()
                sock = ctx.socket(zmq.REQ)
                sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
                sock.setsockopt(zmq.LINGER, 0)
                sock.connect(f"tcp://localhost:{port}")
                sock.send(json.dumps(request).encode())
                raw = sock.recv()
                sock.close()
                ctx.term()
                return json.loads(raw.decode())

            # Ping
            resp = query({"endpoint": "ping"})
            assert resp["status"] == "ok"

            # Get episodes
            resp = query({"endpoint": "get_episodes"})
            assert resp["status"] == "ok"
            assert len(resp["episodes"]) == 2

            # Get chunks for episode 1
            resp = query({"endpoint": "get_chunks", "episode_id": 1})
            assert resp["status"] == "ok"
            assert len(resp["chunks"]) == 6

            # Get geometry for episode 1
            resp = query({"endpoint": "get_geometry", "episode_id": 1})
            assert resp["status"] == "ok"
            assert resp["geometry"]["padded_height"] == 480
            assert resp["geometry"]["total_width"] == 1088

            # Get schedule — verifies numpy serialization
            resp = query({"endpoint": "get_schedule", "episode_id": 1,
                          "chunk_index": 0})
            assert resp["status"] == "ok"
            sigmas = resp["schedule"]["sigmas"]
            assert isinstance(sigmas, list), "sigmas must be a JSON list"
            assert len(sigmas) > 1
            for i in range(len(sigmas) - 1):
                assert sigmas[i] > sigmas[i + 1], (
                    "Sigma schedule must be monotonically decreasing"
                )

            # Unknown endpoint
            resp = query({"endpoint": "nonexistent"})
            assert resp["status"] == "error"

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
