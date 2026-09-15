
import json
import os
import math
import subprocess
import pytest
import numpy as np
from PIL import Image
from io import BytesIO
import cairosvg
from skimage.metrics import structural_similarity
import jsonschema

DATASET_PATH = "/app/dataset/pairs.json"
OUTPUT_PATH = "/app/output/results.json"
SCHEMA_PATH = "/app/spec/output_schema.json"
RASTER_SIZE = 256


# ── Ground-truth helpers (independent of pipeline code) ──────────


def _rasterize_svg(svg_string, size=RASTER_SIZE):
    try:
        png_bytes = cairosvg.svg2png(
            bytestring=svg_string.encode("utf-8"),
            output_width=size,
            output_height=size,
            background_color="white",
        )
        return Image.open(BytesIO(png_bytes)).convert("RGB")
    except Exception:
        return Image.new("RGB", (size, size), (255, 255, 255))


def _correct_mse(img_a, img_b):
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(np.mean((a - b) ** 2))


def _correct_ssim(img_a, img_b):
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(
        structural_similarity(
            a, b, win_size=7, channel_axis=-1,
            data_range=1.0, gaussian_weights=True,
        )
    )


def _correct_histogram_distance(img_a, img_b):
    hsv_a = np.array(img_a.convert("HSV"))
    hsv_b = np.array(img_b.convert("HSV"))
    weights = [0.5, 0.3, 0.2]
    similarity = 0.0
    for ch in range(3):
        hist_a, _ = np.histogram(hsv_a[:, :, ch].ravel(), bins=32, range=(0, 256))
        hist_b, _ = np.histogram(hsv_b[:, :, ch].ravel(), bins=32, range=(0, 256))
        ha = hist_a.astype(np.float64)
        hb = hist_b.astype(np.float64)
        sum_a = ha.sum()
        sum_b = hb.sum()
        if sum_a > 0:
            ha /= sum_a
        if sum_b > 0:
            hb /= sum_b
        hi = float(np.minimum(ha, hb).sum())
        similarity += weights[ch] * hi
    return float(1.0 - similarity)


def _correct_quality_score(ssim_val, mse_val, hist_dist, comp_ratio, target_pct):
    target_frac = target_pct / 100.0
    if target_frac <= 0:
        target_frac = 1e-10
    cr = max(comp_ratio, 0.0)
    return (
        math.sqrt(ssim_val)
        * (1.0 - math.sqrt(mse_val))
        * (1.0 - 0.3 * hist_dist)
        * min(cr / target_frac, 1.0)
    )


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def run_pipeline():
    result = subprocess.run(
        [
            "python3", "-m", "pipeline.run",
            "--input", DATASET_PATH,
            "--output", OUTPUT_PATH,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )
    return result


@pytest.fixture(scope="module")
def output(run_pipeline):
    assert run_pipeline.returncode == 0, (
        f"Pipeline failed:\nstdout: {run_pipeline.stdout}\n"
        f"stderr: {run_pipeline.stderr}"
    )
    assert os.path.exists(OUTPUT_PATH), f"{OUTPUT_PATH} not found"
    with open(OUTPUT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def schema():
    assert os.path.exists(SCHEMA_PATH), f"{SCHEMA_PATH} not found"
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def dataset():
    with open(DATASET_PATH) as f:
        return json.load(f)


# ── Pipeline execution ───────────────────────────────────────────


class TestPipelineExecution:
    def test_runs_successfully(self, run_pipeline):
        assert run_pipeline.returncode == 0, (
            f"Pipeline exited with code {run_pipeline.returncode}:\n"
            f"{run_pipeline.stderr}"
        )

    def test_output_file_created(self, run_pipeline):
        assert os.path.exists(OUTPUT_PATH)


# ── Schema validation ───────────────────────────────────────────


class TestSchemaValidation:
    def test_output_matches_json_schema(self, output, schema):
        jsonschema.validate(instance=output, schema=schema)

    def test_sample_count_matches_input(self, output, dataset):
        assert len(output["samples"]) == len(dataset)

    def test_target_met_is_boolean(self, output):
        for s in output["samples"]:
            assert isinstance(s["target_met"], bool), (
                f"target_met for {s['id']} should be bool, got {type(s['target_met'])}"
            )


# ── Invariant properties ────────────────────────────────────────


class TestInvariantProperties:
    """Validate metric properties that hold by mathematical definition."""

    def test_identity_mse_zero(self, output):
        s = next(s for s in output["samples"] if s["id"] == "identity")
        assert s["mse"] == pytest.approx(0.0, abs=1e-10)

    def test_identity_ssim_one(self, output):
        s = next(s for s in output["samples"] if s["id"] == "identity")
        assert s["ssim"] == pytest.approx(1.0, abs=1e-6)

    def test_identity_histogram_distance_zero(self, output):
        s = next(s for s in output["samples"] if s["id"] == "identity")
        assert s["histogram_distance"] == pytest.approx(0.0, abs=1e-10)

    def test_whitespace_visually_identical(self, output):
        s = next(s for s in output["samples"] if s["id"] == "whitespace_opt")
        assert s["mse"] < 0.001, (
            f"Whitespace-only opt should have near-zero MSE: {s['mse']}"
        )
        assert s["ssim"] > 0.99, (
            f"Whitespace-only opt should have near-1 SSIM: {s['ssim']}"
        )
        assert s["histogram_distance"] < 0.01, (
            f"Whitespace-only opt should have near-zero histogram distance: "
            f"{s['histogram_distance']}"
        )

    def test_wrong_svg_high_divergence(self, output):
        s = next(s for s in output["samples"] if s["id"] == "wrong_svg")
        assert s["mse"] > 0.01, (
            f"Wrong SVG must have significant MSE: {s['mse']}"
        )
        assert s["ssim"] < 0.9, (
            f"Wrong SVG must have low SSIM: {s['ssim']}"
        )
        assert s["histogram_distance"] > 0.05, (
            f"Wrong SVG must have meaningful histogram distance: "
            f"{s['histogram_distance']}"
        )

    def test_malformed_nonzero_mse(self, output):
        s = next(s for s in output["samples"] if s["id"] == "malformed")
        assert s["mse"] > 0.01, (
            f"Malformed SVG fallback should differ from original: {s['mse']}"
        )

    def test_mse_values_in_range(self, output):
        for s in output["samples"]:
            assert 0.0 <= s["mse"] <= 1.0, (
                f"MSE out of [0,1] for {s['id']}: {s['mse']}"
            )

    def test_ssim_has_meaningful_spread(self, output):
        ssim_vals = [s["ssim"] for s in output["samples"]]
        spread = max(ssim_vals) - min(ssim_vals)
        assert spread > 0.1, (
            f"SSIM values lack meaningful spread ({spread:.4f}), "
            f"suggesting incorrect data_range or weighting configuration"
        )

    def test_histogram_distances_in_range(self, output):
        for s in output["samples"]:
            assert 0.0 <= s["histogram_distance"] <= 1.0, (
                f"Histogram distance out of [0,1] for {s['id']}: "
                f"{s['histogram_distance']}"
            )

    def test_histogram_has_meaningful_spread(self, output):
        vals = [s["histogram_distance"] for s in output["samples"]]
        spread = max(vals) - min(vals)
        assert spread > 0.05, (
            f"Histogram distance values lack spread ({spread:.4f}), "
            f"suggesting incorrect color space or similarity measure"
        )


# ── Independent metric verification ──────────────────────────────


class TestIndependentVerification:
    """Re-compute all metrics from scratch and compare against pipeline output."""

    def test_mse_values_match_ground_truth(self, output, dataset):
        sample_map = {d["id"]: d for d in dataset}
        for out_s in output["samples"]:
            pair = sample_map[out_s["id"]]
            img_orig = _rasterize_svg(pair["original_svg"])
            img_opt = _rasterize_svg(pair["optimized_svg"])
            expected_mse = _correct_mse(img_orig, img_opt)
            assert out_s["mse"] == pytest.approx(expected_mse, abs=1e-4), (
                f"MSE independent check failed for {out_s['id']}: "
                f"got {out_s['mse']}, expected {expected_mse}"
            )

    def test_ssim_values_match_ground_truth(self, output, dataset):
        sample_map = {d["id"]: d for d in dataset}
        for out_s in output["samples"]:
            pair = sample_map[out_s["id"]]
            img_orig = _rasterize_svg(pair["original_svg"])
            img_opt = _rasterize_svg(pair["optimized_svg"])
            expected_ssim = _correct_ssim(img_orig, img_opt)
            assert out_s["ssim"] == pytest.approx(expected_ssim, abs=1e-4), (
                f"SSIM independent check failed for {out_s['id']}: "
                f"got {out_s['ssim']}, expected {expected_ssim}"
            )

    def test_histogram_distance_values_match_ground_truth(self, output, dataset):
        sample_map = {d["id"]: d for d in dataset}
        for out_s in output["samples"]:
            pair = sample_map[out_s["id"]]
            img_orig = _rasterize_svg(pair["original_svg"])
            img_opt = _rasterize_svg(pair["optimized_svg"])
            expected_hist = _correct_histogram_distance(img_orig, img_opt)
            assert out_s["histogram_distance"] == pytest.approx(
                expected_hist, abs=1e-4
            ), (
                f"Histogram distance independent check failed for {out_s['id']}: "
                f"got {out_s['histogram_distance']}, expected {expected_hist}"
            )

    def test_quality_scores_match_ground_truth(self, output, dataset):
        sample_map = {d["id"]: d for d in dataset}
        for out_s in output["samples"]:
            pair = sample_map[out_s["id"]]
            img_orig = _rasterize_svg(pair["original_svg"])
            img_opt = _rasterize_svg(pair["optimized_svg"])
            mse = _correct_mse(img_orig, img_opt)
            ssim = _correct_ssim(img_orig, img_opt)
            hist = _correct_histogram_distance(img_orig, img_opt)
            orig_bytes = len(pair["original_svg"].encode("utf-8"))
            opt_bytes = len(pair["optimized_svg"].encode("utf-8"))
            cr = max(1.0 - opt_bytes / orig_bytes, 0.0)
            expected_q = _correct_quality_score(
                ssim, mse, hist, cr, pair["target_compression_pct"]
            )
            assert out_s["quality_score"] == pytest.approx(expected_q, abs=1e-4), (
                f"Quality score independent check failed for {out_s['id']}: "
                f"got {out_s['quality_score']}, expected {expected_q}"
            )


# ── Internal consistency ──────────────────────────────────────────


class TestInternalConsistency:
    def test_compression_ratio_matches_byte_sizes(self, output):
        for s in output["samples"]:
            expected = max(
                1.0 - s["optimized_size_bytes"] / s["original_size_bytes"], 0.0
            )
            assert s["compression_ratio"] == pytest.approx(expected, abs=1e-6)

    def test_byte_sizes_match_dataset(self, output, dataset):
        dmap = {d["id"]: d for d in dataset}
        for s in output["samples"]:
            d = dmap[s["id"]]
            assert s["original_size_bytes"] == len(
                d["original_svg"].encode("utf-8")
            )
            assert s["optimized_size_bytes"] == len(
                d["optimized_svg"].encode("utf-8")
            )

    def test_quality_score_formula(self, output):
        for s in output["samples"]:
            cr = max(s["compression_ratio"], 0.0)
            target_frac = s["target_compression_pct"] / 100.0
            if target_frac <= 0:
                target_frac = 1e-10
            expected_q = (
                math.sqrt(s["ssim"])
                * (1.0 - math.sqrt(s["mse"]))
                * (1.0 - 0.3 * s["histogram_distance"])
                * min(cr / target_frac, 1.0)
            )
            assert s["quality_score"] == pytest.approx(expected_q, abs=1e-6), (
                f"Quality formula failed for {s['id']}: "
                f"got {s['quality_score']}, expected {expected_q}"
            )

    def test_tier_classification(self, output):
        for s in output["samples"]:
            q = s["quality_score"]
            if q >= 0.8:
                expected = "excellent"
            elif q >= 0.6:
                expected = "good"
            elif q >= 0.4:
                expected = "fair"
            else:
                expected = "poor"
            assert s["quality_tier"] == expected, (
                f"Tier mismatch for {s['id']}: Q={q}, "
                f"got {s['quality_tier']}, expected {expected}"
            )

    def test_aggregate_means(self, output):
        samples = output["samples"]
        n = len(samples)
        agg = output["aggregate"]
        assert agg["mean_mse"] == pytest.approx(
            sum(s["mse"] for s in samples) / n, abs=1e-6
        )
        assert agg["mean_ssim"] == pytest.approx(
            sum(s["ssim"] for s in samples) / n, abs=1e-6
        )
        assert agg["mean_histogram_distance"] == pytest.approx(
            sum(s["histogram_distance"] for s in samples) / n, abs=1e-6
        )
        assert agg["mean_compression_ratio"] == pytest.approx(
            sum(s["compression_ratio"] for s in samples) / n, abs=1e-6
        )

    def test_aggregate_target_hit_rate(self, output):
        samples = output["samples"]
        expected = sum(1 for s in samples if s["target_met"]) / len(samples)
        assert output["aggregate"]["target_hit_rate"] == pytest.approx(
            expected, abs=1e-6
        )

    def test_aggregate_tier_counts(self, output):
        expected = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
        for s in output["samples"]:
            expected[s["quality_tier"]] += 1
        assert output["aggregate"]["tier_counts"] == expected

    def test_total_samples(self, output):
        assert output["aggregate"]["total_samples"] == len(output["samples"])


# ── Ordering ──────────────────────────────────────────────────────


class TestOrdering:
    def test_sample_order_matches_input(self, output, dataset):
        input_ids = [d["id"] for d in dataset]
        output_ids = [s["id"] for s in output["samples"]]
        assert output_ids == input_ids, (
            f"Output order must match input order.\n"
            f"Input:  {input_ids}\nOutput: {output_ids}"
        )


# ── Reproducibility ──────────────────────────────────────────────


class TestReproducibility:
    def test_consistent_across_runs(self, output):
        result = subprocess.run(
            [
                "python3", "-m", "pipeline.run",
                "--input", DATASET_PATH,
                "--output", "/tmp/repro_check.json",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/app",
        )
        assert result.returncode == 0
        with open("/tmp/repro_check.json") as f:
            rerun = json.load(f)
        for orig_s, rerun_s in zip(output["samples"], rerun["samples"]):
            assert orig_s["id"] == rerun_s["id"]
            assert orig_s["mse"] == pytest.approx(rerun_s["mse"], abs=1e-6)
            assert orig_s["ssim"] == pytest.approx(rerun_s["ssim"], abs=1e-6)
            assert orig_s["histogram_distance"] == pytest.approx(
                rerun_s["histogram_distance"], abs=1e-6
            )
            assert orig_s["quality_score"] == pytest.approx(
                rerun_s["quality_score"], abs=1e-6
            )
