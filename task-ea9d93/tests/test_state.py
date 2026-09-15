
"""Tests for cross-validated hierarchical roofline analysis.

Verifies ERT-derived bandwidths, STREAM parsing, theoretical peak calculations,
cross-validation metrics, kernel classifications, and gnuplot chart generation.
"""

import json
import os
import pytest

RESULT_FILE = "/app/results/roofline_analysis.json"
SVG_FILE = "/app/results/roofline.svg"

# Ground truth: ERT-derived empirical values
TRUE_BW = {"L1": 1450.0, "L2": 480.0, "L3": 190.0, "DRAM": 72.0}
TRUE_PEAK = 280.0
TRUE_BOUNDARIES = {"L1": 32768, "L2": 262144, "L3": 8388608}

# Ground truth: STREAM output values (MB/s converted to GB/s)
TRUE_STREAM = {
    "copy_gbs": 48.2345,
    "scale_gbs": 47.8912,
    "add_gbs": 54.1028,
    "triad_gbs": 54.3851,
}

# Ground truth: theoretical peaks
# peak = 16 * 2.2 * (32/8) * 2 = 281.6
# dram_bw = 2 * 3.2 * 8 * 2 = 102.4
TRUE_THEO_PEAK = 281.6
TRUE_THEO_DRAM_BW = 102.4

# Ground truth: STREAM Triad corrected for write-allocate
# Triad counts 24 bytes/element, actual hardware = 32 bytes (WA on write array)
# corrected = 54.3851 * (32/24) = 72.5135
TRUE_STREAM_TRIAD_CORRECTED = 54.3851 * (32.0 / 24.0)

# Kernel ground truth
TRUE_KERNELS = {
    "stream_triad": {
        "ai": 2.0 / 24.0,
        "ai_wa": 2.0 / 32.0,
        "level": "DRAM",
        "classification": "memory-bound",
        "achievable": 2.0 / 32.0 * 72.0,
    },
    "stencil_3d_7pt": {
        "ai": 13.0 / 24.0,
        "ai_wa": 13.0 / 32.0,
        "level": "DRAM",
        "classification": "memory-bound",
        "achievable": 13.0 / 32.0 * 72.0,
    },
    "fft_radix2": {
        "ai": 5.0 / 32.0,
        "ai_wa": None,
        "level": "L3",
        "classification": "memory-bound",
        "achievable": 5.0 / 32.0 * 190.0,
    },
    "dgemm_blocked": {
        "ai": 128.0 / 24.0,
        "ai_wa": None,
        "level": "L2",
        "classification": "compute-bound",
        "achievable": 280.0,
    },
    "sparse_matvec": {
        "ai": 20.0 / 120.0,
        "ai_wa": 20.0 / 128.0,
        "level": "DRAM",
        "classification": "memory-bound",
        "achievable": 20.0 / 128.0 * 72.0,
    },
}


@pytest.fixture
def results():
    assert os.path.exists(RESULT_FILE), (
        "Output file {} does not exist.".format(RESULT_FILE)
    )
    with open(RESULT_FILE) as f:
        data = json.load(f)
    return data


class TestOutputStructure:
    """Verify the output JSON has all required sections."""

    def test_file_exists_and_valid_json(self):
        assert os.path.exists(RESULT_FILE), "Output file missing"
        with open(RESULT_FILE) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_empirical_section(self, results):
        assert "empirical" in results
        emp = results["empirical"]
        assert "bandwidths_gbs" in emp
        assert "cache_boundaries_bytes" in emp
        assert "peak_gflops" in emp

    def test_has_theoretical_section(self, results):
        assert "theoretical" in results
        theo = results["theoretical"]
        assert "peak_gflops" in theo
        assert "dram_bandwidth_gbs" in theo

    def test_has_stream_section(self, results):
        assert "stream" in results
        st = results["stream"]
        for key in ["copy_gbs", "scale_gbs", "add_gbs", "triad_gbs"]:
            assert key in st, "Missing stream field: {}".format(key)

    def test_has_validation_section(self, results):
        assert "validation" in results
        val = results["validation"]
        for key in ["peak_efficiency", "dram_efficiency",
                     "stream_triad_corrected_gbs", "stream_ert_ratio"]:
            assert key in val, "Missing validation field: {}".format(key)

    def test_has_ridge_points(self, results):
        assert "ridge_points" in results

    def test_has_kernel_analysis(self, results):
        assert "kernel_analysis" in results
        assert isinstance(results["kernel_analysis"], list)


class TestBandwidthDetection:
    """Verify detected bandwidth values at each cache level."""

    def test_four_levels_detected(self, results):
        bws = results["empirical"]["bandwidths_gbs"]
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert level in bws, "Missing bandwidth for {}".format(level)

    def test_bandwidth_ordering(self, results):
        bws = results["empirical"]["bandwidths_gbs"]
        assert bws["L1"] > bws["L2"] > bws["L3"] > bws["DRAM"], (
            "Bandwidths must be ordered L1 > L2 > L3 > DRAM, "
            "got L1={}, L2={}, L3={}, DRAM={}".format(
                bws["L1"], bws["L2"], bws["L3"], bws["DRAM"]
            )
        )

    @pytest.mark.parametrize("level", ["L1", "L2", "L3", "DRAM"])
    def test_bandwidth_accuracy(self, results, level):
        detected = results["empirical"]["bandwidths_gbs"][level]
        expected = TRUE_BW[level]
        rel_error = abs(detected - expected) / expected
        assert rel_error < 0.15, (
            "{} bandwidth: expected ~{:.1f}, got {:.1f} "
            "(relative error {:.1%})".format(level, expected, detected, rel_error)
        )


class TestPeakCompute:
    """Verify detected peak GFLOP/s."""

    def test_peak_gflops_accuracy(self, results):
        peak = results["empirical"]["peak_gflops"]
        rel_error = abs(peak - TRUE_PEAK) / TRUE_PEAK
        assert rel_error < 0.10, (
            "Peak GFLOP/s: expected ~{:.1f}, got {:.1f} "
            "(relative error {:.1%})".format(TRUE_PEAK, peak, rel_error)
        )


class TestCacheBoundaries:
    """Verify detected cache size boundaries."""

    @pytest.mark.parametrize("level", ["L1", "L2", "L3"])
    def test_boundary_within_factor_2(self, results, level):
        bounds = results["empirical"]["cache_boundaries_bytes"]
        assert level in bounds, "Missing cache boundary for {}".format(level)
        detected = bounds[level]
        expected = TRUE_BOUNDARIES[level]
        ratio = detected / expected
        assert 0.5 <= ratio <= 2.0, (
            "{} boundary: expected ~{}, got {} "
            "(ratio {:.2f})".format(level, expected, detected, ratio)
        )

    def test_boundary_ordering(self, results):
        bounds = results["empirical"]["cache_boundaries_bytes"]
        assert bounds["L1"] < bounds["L2"] < bounds["L3"]


class TestRidgePoints:
    """Verify ridge point internal consistency."""

    @pytest.mark.parametrize("level", ["L1", "L2", "L3", "DRAM"])
    def test_ridge_consistency(self, results, level):
        ridge = results["ridge_points"][level]
        bw = results["empirical"]["bandwidths_gbs"][level]
        peak = results["empirical"]["peak_gflops"]
        expected_ridge = peak / bw
        rel_error = abs(ridge - expected_ridge) / expected_ridge
        assert rel_error < 0.01, (
            "Ridge point {}: expected {:.6f}, got {:.6f}".format(
                level, expected_ridge, ridge
            )
        )

    def test_ridge_ordering(self, results):
        rp = results["ridge_points"]
        assert rp["L1"] < rp["L2"] < rp["L3"] < rp["DRAM"]


class TestStreamParsing:
    """Verify STREAM benchmark output was parsed correctly."""

    @pytest.mark.parametrize("field,expected", [
        ("copy_gbs", TRUE_STREAM["copy_gbs"]),
        ("scale_gbs", TRUE_STREAM["scale_gbs"]),
        ("add_gbs", TRUE_STREAM["add_gbs"]),
        ("triad_gbs", TRUE_STREAM["triad_gbs"]),
    ])
    def test_stream_values(self, results, field, expected):
        detected = results["stream"][field]
        rel_error = abs(detected - expected) / expected
        assert rel_error < 0.01, (
            "STREAM {}: expected {:.4f}, got {:.4f} "
            "(relative error {:.2%})".format(field, expected, detected, rel_error)
        )


class TestTheoreticalPeaks:
    """Verify theoretical peak calculations from system spec."""

    def test_theoretical_peak_gflops(self, results):
        theo = results["theoretical"]["peak_gflops"]
        rel_error = abs(theo - TRUE_THEO_PEAK) / TRUE_THEO_PEAK
        assert rel_error < 0.05, (
            "Theoretical peak: expected {:.1f}, got {:.1f} "
            "(relative error {:.1%})".format(TRUE_THEO_PEAK, theo, rel_error)
        )

    def test_theoretical_dram_bw(self, results):
        theo = results["theoretical"]["dram_bandwidth_gbs"]
        rel_error = abs(theo - TRUE_THEO_DRAM_BW) / TRUE_THEO_DRAM_BW
        assert rel_error < 0.05, (
            "Theoretical DRAM BW: expected {:.1f}, got {:.1f} "
            "(relative error {:.1%})".format(TRUE_THEO_DRAM_BW, theo, rel_error)
        )


class TestCrossValidation:
    """Verify cross-validation metrics between ERT, STREAM, and theoretical."""

    def test_peak_efficiency_range(self, results):
        eff = results["validation"]["peak_efficiency"]
        assert 0.80 <= eff <= 1.10, (
            "Peak efficiency {:.3f} out of plausible range [0.80, 1.10]".format(eff)
        )

    def test_dram_efficiency_range(self, results):
        eff = results["validation"]["dram_efficiency"]
        assert 0.50 <= eff <= 0.90, (
            "DRAM efficiency {:.3f} out of plausible range [0.50, 0.90]".format(eff)
        )

    def test_stream_triad_corrected(self, results):
        corrected = results["validation"]["stream_triad_corrected_gbs"]
        rel_error = abs(corrected - TRUE_STREAM_TRIAD_CORRECTED) / TRUE_STREAM_TRIAD_CORRECTED
        assert rel_error < 0.05, (
            "Corrected STREAM Triad: expected {:.2f}, got {:.2f} "
            "(relative error {:.1%})".format(
                TRUE_STREAM_TRIAD_CORRECTED, corrected, rel_error
            )
        )

    def test_stream_ert_ratio(self, results):
        ratio = results["validation"]["stream_ert_ratio"]
        assert 0.85 <= ratio <= 1.15, (
            "STREAM/ERT ratio {:.3f} out of expected range [0.85, 1.15]. "
            "Cross-validation failed.".format(ratio)
        )


class TestKernelAnalysis:
    """Verify per-kernel roofline classification and predictions."""

    def test_kernel_count(self, results):
        assert len(results["kernel_analysis"]) == 5

    def _get_kernel(self, results, name):
        for k in results["kernel_analysis"]:
            if k["name"] == name:
                return k
        pytest.fail("Kernel '{}' not found".format(name))

    @pytest.mark.parametrize("name", list(TRUE_KERNELS.keys()))
    def test_arithmetic_intensity(self, results, name):
        kernel = self._get_kernel(results, name)
        expected_ai = TRUE_KERNELS[name]["ai"]
        detected_ai = kernel["arithmetic_intensity"]
        rel_error = abs(detected_ai - expected_ai) / expected_ai
        assert rel_error < 0.01, (
            "{}: AI expected {:.6f}, got {:.6f}".format(
                name, expected_ai, detected_ai
            )
        )

    @pytest.mark.parametrize("name", list(TRUE_KERNELS.keys()))
    def test_arithmetic_intensity_with_wa(self, results, name):
        kernel = self._get_kernel(results, name)
        expected_ai_wa = TRUE_KERNELS[name]["ai_wa"]
        detected_ai_wa = kernel["arithmetic_intensity_with_wa"]
        if expected_ai_wa is None:
            assert detected_ai_wa is None
        else:
            assert detected_ai_wa is not None
            rel_error = abs(detected_ai_wa - expected_ai_wa) / expected_ai_wa
            assert rel_error < 0.01

    @pytest.mark.parametrize("name", list(TRUE_KERNELS.keys()))
    def test_memory_level(self, results, name):
        kernel = self._get_kernel(results, name)
        assert kernel["memory_level"] == TRUE_KERNELS[name]["level"]

    @pytest.mark.parametrize("name", list(TRUE_KERNELS.keys()))
    def test_classification(self, results, name):
        kernel = self._get_kernel(results, name)
        assert kernel["classification"] == TRUE_KERNELS[name]["classification"]

    @pytest.mark.parametrize("name", list(TRUE_KERNELS.keys()))
    def test_achievable_gflops(self, results, name):
        kernel = self._get_kernel(results, name)
        expected = TRUE_KERNELS[name]["achievable"]
        detected = kernel["achievable_gflops"]
        rel_error = abs(detected - expected) / expected
        assert rel_error < 0.25


class TestRooflineChart:
    """Verify gnuplot-generated roofline SVG chart."""

    def test_svg_exists(self):
        assert os.path.exists(SVG_FILE), (
            "Roofline chart {} does not exist".format(SVG_FILE)
        )

    def test_svg_is_valid(self):
        with open(SVG_FILE) as f:
            content = f.read()
        assert "<svg" in content.lower(), "File is not valid SVG"
        assert "</svg>" in content.lower(), "SVG is not properly closed"

    def test_svg_has_log_scale(self):
        """Gnuplot log-scale SVGs contain specific transform patterns."""
        with open(SVG_FILE) as f:
            content = f.read()
        # Gnuplot log-scale charts use specific axis tick patterns
        # Check for presence of typical log-scale tick values
        has_log_indicator = False
        # Look for characteristic log-scale axis labels (powers of 2 or 10)
        for indicator in ["0.01", "0.1", "10", "100"]:
            if indicator in content:
                has_log_indicator = True
                break
        assert has_log_indicator, "SVG does not appear to use logarithmic scales"

    def test_svg_has_cache_level_labels(self):
        with open(SVG_FILE) as f:
            content = f.read()
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert level in content, (
                "SVG missing cache level label: {}".format(level)
            )

    def test_svg_has_kernel_labels(self):
        with open(SVG_FILE) as f:
            content = f.read()
        kernel_fragments = ["stream_triad", "stencil", "fft", "dgemm", "sparse"]
        found = sum(1 for k in kernel_fragments if k in content.lower())
        assert found >= 3, (
            "SVG should contain at least 3 kernel labels, found {}".format(found)
        )

    def test_svg_has_theoretical_peak(self):
        with open(SVG_FILE) as f:
            content = f.read()
        content_lower = content.lower()
        assert "theoretical" in content_lower or "theo" in content_lower or "dashed" in content_lower or "dash" in content_lower, (
            "SVG should include a theoretical peak indicator"
        )

    def test_svg_has_axis_labels(self):
        with open(SVG_FILE) as f:
            content = f.read()
        content_lower = content.lower()
        has_x = ("arithmetic intensity" in content_lower or
                 "flop/byte" in content_lower or
                 "flops/byte" in content_lower)
        has_y = ("gflop" in content_lower or
                 "performance" in content_lower)
        assert has_x, "SVG missing x-axis label (Arithmetic Intensity)"
        assert has_y, "SVG missing y-axis label (GFLOP/s or Performance)"
