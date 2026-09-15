"""
Tests for hierarchical roofline model construction.

"""

import json
import os
import xml.etree.ElementTree as ET
import pytest

RESULT_PATH = "/app/results/roofline_analysis.json"
SVG_PATH = "/app/results/roofline_chart.svg"
REL_TOL = 0.01  # 1% relative tolerance


def approx(expected, rel=REL_TOL):
    return pytest.approx(expected, rel=rel)


@pytest.fixture(scope="module")
def result():
    assert os.path.exists(RESULT_PATH), f"Output file {RESULT_PATH} does not exist"
    with open(RESULT_PATH) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Roofline Chart (gnuplot SVG)
# ---------------------------------------------------------------------------

class TestRooflineChart:
    def test_svg_file_exists(self):
        assert os.path.exists(SVG_PATH), f"SVG chart {SVG_PATH} does not exist"

    def test_svg_file_not_empty(self):
        size = os.path.getsize(SVG_PATH)
        assert size > 1000, f"SVG file too small ({size} bytes), likely not a real chart"

    def test_produced_by_gnuplot(self):
        with open(SVG_PATH) as f:
            content = f.read()
        assert "gnuplot" in content.lower() or "GNUPLOT" in content, \
            "SVG does not appear to be produced by gnuplot"

    def test_valid_svg_xml(self):
        tree = ET.parse(SVG_PATH)
        root = tree.getroot()
        assert "svg" in root.tag.lower(), f"Root element is {root.tag}, expected svg"

    def test_cache_level_labels_present(self):
        with open(SVG_PATH) as f:
            content = f.read()
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert level in content, f"Cache level label '{level}' not found in SVG"

    def test_kernel_names_present(self):
        with open(SVG_PATH) as f:
            content = f.read()
        for name in ["stencil_3d", "dense_matmul", "sparse_mv", "fft_radix2", "particle_force"]:
            assert name in content, f"Kernel label '{name}' not found in SVG"

    def test_axis_labels_present(self):
        with open(SVG_PATH) as f:
            content = f.read()
        assert "Arithmetic Intensity" in content, \
            "X-axis label 'Arithmetic Intensity' not found in SVG"
        assert "GFLOP" in content, \
            "Y-axis label containing 'GFLOP' not found in SVG"


# ---------------------------------------------------------------------------
# Empirical peak GFLOP/s
# ---------------------------------------------------------------------------

class TestEmpiricalPeak:
    def test_peak_gflops_present(self, result):
        assert "empirical_peak_gflops" in result

    def test_peak_gflops_value(self, result):
        assert result["empirical_peak_gflops"] == approx(64.2)


# ---------------------------------------------------------------------------
# Memory hierarchy characterization
# ---------------------------------------------------------------------------

class TestMemoryLevels:
    def test_all_levels_present(self, result):
        levels = result["memory_levels"]
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert level in levels, f"Missing memory level: {level}"

    def test_l1_bandwidth(self, result):
        assert result["memory_levels"]["L1"]["peak_bandwidth_gb_per_s"] == approx(450.0)

    def test_l2_bandwidth(self, result):
        assert result["memory_levels"]["L2"]["peak_bandwidth_gb_per_s"] == approx(180.0)

    def test_l3_bandwidth(self, result):
        assert result["memory_levels"]["L3"]["peak_bandwidth_gb_per_s"] == approx(54.0)

    def test_dram_bandwidth(self, result):
        assert result["memory_levels"]["DRAM"]["peak_bandwidth_gb_per_s"] == approx(28.0)

    def test_l1_ridge_point(self, result):
        assert result["memory_levels"]["L1"]["ridge_point_flop_per_byte"] == approx(64.2 / 450.0)

    def test_l2_ridge_point(self, result):
        assert result["memory_levels"]["L2"]["ridge_point_flop_per_byte"] == approx(64.2 / 180.0)

    def test_l3_ridge_point(self, result):
        assert result["memory_levels"]["L3"]["ridge_point_flop_per_byte"] == approx(64.2 / 54.0)

    def test_dram_ridge_point(self, result):
        assert result["memory_levels"]["DRAM"]["ridge_point_flop_per_byte"] == approx(64.2 / 28.0)

    def test_bandwidth_hierarchy_order(self, result):
        """Peak bandwidth must decrease from L1 to DRAM."""
        levels = result["memory_levels"]
        bw_l1 = levels["L1"]["peak_bandwidth_gb_per_s"]
        bw_l2 = levels["L2"]["peak_bandwidth_gb_per_s"]
        bw_l3 = levels["L3"]["peak_bandwidth_gb_per_s"]
        bw_dram = levels["DRAM"]["peak_bandwidth_gb_per_s"]
        assert bw_l1 > bw_l2 > bw_l3 > bw_dram


# ---------------------------------------------------------------------------
# STREAM bandwidth correction
# ---------------------------------------------------------------------------

class TestStreamCorrection:
    def test_stream_section_present(self, result):
        assert "stream_corrected" in result

    def test_all_kernels_present(self, result):
        for k in ["Copy", "Scale", "Add", "Triad"]:
            assert k in result["stream_corrected"], f"Missing STREAM kernel: {k}"

    def test_copy_wa_factor(self, result):
        assert result["stream_corrected"]["Copy"]["wa_factor"] == approx(1.5)

    def test_scale_wa_factor(self, result):
        assert result["stream_corrected"]["Scale"]["wa_factor"] == approx(1.5)

    def test_add_wa_factor(self, result):
        assert result["stream_corrected"]["Add"]["wa_factor"] == approx(4.0 / 3.0)

    def test_triad_wa_factor(self, result):
        assert result["stream_corrected"]["Triad"]["wa_factor"] == approx(4.0 / 3.0)

    def test_copy_reported(self, result):
        assert result["stream_corrected"]["Copy"]["reported_mb_per_s"] == approx(18500.0)

    def test_scale_reported(self, result):
        assert result["stream_corrected"]["Scale"]["reported_mb_per_s"] == approx(18200.0)

    def test_add_reported(self, result):
        assert result["stream_corrected"]["Add"]["reported_mb_per_s"] == approx(20700.0)

    def test_triad_reported(self, result):
        assert result["stream_corrected"]["Triad"]["reported_mb_per_s"] == approx(20550.0)

    def test_copy_corrected(self, result):
        assert result["stream_corrected"]["Copy"]["corrected_gb_per_s"] == approx(27.75)

    def test_scale_corrected(self, result):
        assert result["stream_corrected"]["Scale"]["corrected_gb_per_s"] == approx(27.3)

    def test_add_corrected(self, result):
        assert result["stream_corrected"]["Add"]["corrected_gb_per_s"] == approx(27.6)

    def test_triad_corrected(self, result):
        assert result["stream_corrected"]["Triad"]["corrected_gb_per_s"] == approx(27.4)

    def test_corrected_consistency(self, result):
        """corrected_gb_per_s should equal reported_mb_per_s * wa_factor / 1000."""
        for k in ["Copy", "Scale", "Add", "Triad"]:
            entry = result["stream_corrected"][k]
            expected = entry["reported_mb_per_s"] * entry["wa_factor"] / 1000.0
            assert entry["corrected_gb_per_s"] == approx(expected)


# ---------------------------------------------------------------------------
# Kernel analysis
# ---------------------------------------------------------------------------

def _find_kernel(result, name):
    for k in result["kernel_analysis"]:
        if k["name"] == name:
            return k
    pytest.fail(f"Kernel '{name}' not found in kernel_analysis")


class TestKernelAnalysis:
    def test_kernel_count(self, result):
        assert len(result["kernel_analysis"]) == 5

    def test_kernel_names(self, result):
        names = {k["name"] for k in result["kernel_analysis"]}
        expected = {"stencil_3d", "dense_matmul", "sparse_mv", "fft_radix2", "particle_force"}
        assert names == expected


class TestStencil3D:
    def test_ai_l1(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L1"]["arithmetic_intensity"] == approx(0.2)

    def test_ai_l2(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L2"]["arithmetic_intensity"] == approx(0.4)

    def test_ai_l3(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L3"]["arithmetic_intensity"] == approx(0.8)

    def test_ai_dram(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["DRAM"]["arithmetic_intensity"] == approx(2.0)

    def test_bound_l1(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L1"]["bound"] == "compute"

    def test_bound_l2(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L2"]["bound"] == "compute"

    def test_bound_l3(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L3"]["bound"] == "memory"

    def test_bound_dram(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["DRAM"]["bound"] == "memory"

    def test_attainable_l1(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L1"]["attainable_gflops"] == approx(64.2)

    def test_attainable_l2(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L2"]["attainable_gflops"] == approx(64.2)

    def test_attainable_l3(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["L3"]["attainable_gflops"] == approx(43.2)

    def test_attainable_dram(self, result):
        k = _find_kernel(result, "stencil_3d")
        assert k["levels"]["DRAM"]["attainable_gflops"] == approx(56.0)


class TestDenseMatmul:
    def test_all_compute_bound(self, result):
        k = _find_kernel(result, "dense_matmul")
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert k["levels"][level]["bound"] == "compute", f"Expected compute at {level}"
            assert k["levels"][level]["attainable_gflops"] == approx(64.2)

    def test_ai_values(self, result):
        k = _find_kernel(result, "dense_matmul")
        assert k["levels"]["L1"]["arithmetic_intensity"] == approx(0.4)
        assert k["levels"]["L2"]["arithmetic_intensity"] == approx(2.0)
        assert k["levels"]["L3"]["arithmetic_intensity"] == approx(10.0)
        assert k["levels"]["DRAM"]["arithmetic_intensity"] == approx(40.0)


class TestSparseMV:
    def test_all_memory_bound(self, result):
        k = _find_kernel(result, "sparse_mv")
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert k["levels"][level]["bound"] == "memory", f"Expected memory at {level}"

    def test_ai_values(self, result):
        k = _find_kernel(result, "sparse_mv")
        assert k["levels"]["L1"]["arithmetic_intensity"] == approx(0.025)
        assert k["levels"]["L2"]["arithmetic_intensity"] == approx(0.05)
        assert k["levels"]["L3"]["arithmetic_intensity"] == approx(0.1)
        assert k["levels"]["DRAM"]["arithmetic_intensity"] == approx(0.125)

    def test_attainable_l1(self, result):
        k = _find_kernel(result, "sparse_mv")
        assert k["levels"]["L1"]["attainable_gflops"] == approx(11.25)

    def test_attainable_l2(self, result):
        k = _find_kernel(result, "sparse_mv")
        assert k["levels"]["L2"]["attainable_gflops"] == approx(9.0)

    def test_attainable_l3(self, result):
        k = _find_kernel(result, "sparse_mv")
        assert k["levels"]["L3"]["attainable_gflops"] == approx(5.4)

    def test_attainable_dram(self, result):
        k = _find_kernel(result, "sparse_mv")
        assert k["levels"]["DRAM"]["attainable_gflops"] == approx(3.5)


class TestFFTRadix2:
    def test_bound_l1(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["L1"]["bound"] == "memory"

    def test_bound_l2(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["L2"]["bound"] == "compute"

    def test_bound_l3(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["L3"]["bound"] == "compute"

    def test_bound_dram(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["DRAM"]["bound"] == "compute"

    def test_ai_l1(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["L1"]["arithmetic_intensity"] == approx(0.1)

    def test_attainable_l1(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["L1"]["attainable_gflops"] == approx(45.0)

    def test_attainable_l2(self, result):
        k = _find_kernel(result, "fft_radix2")
        assert k["levels"]["L2"]["attainable_gflops"] == approx(64.2)


class TestParticleForce:
    def test_all_compute_bound(self, result):
        k = _find_kernel(result, "particle_force")
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert k["levels"][level]["bound"] == "compute"
            assert k["levels"][level]["attainable_gflops"] == approx(64.2)

    def test_ai_monotonically_increasing(self, result):
        """AI should increase from L1 to DRAM (cache filtering reduces traffic)."""
        k = _find_kernel(result, "particle_force")
        ai_l1 = k["levels"]["L1"]["arithmetic_intensity"]
        ai_l2 = k["levels"]["L2"]["arithmetic_intensity"]
        ai_l3 = k["levels"]["L3"]["arithmetic_intensity"]
        ai_dram = k["levels"]["DRAM"]["arithmetic_intensity"]
        assert ai_l1 < ai_l2 < ai_l3 < ai_dram
