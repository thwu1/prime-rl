"""Test hierarchical roofline analysis results.

"""

import json
import os
import pytest

RESULT_FILE = "/app/results/roofline_analysis.json"
CHART_FILE = "/app/results/roofline_chart.svg"
BW_PROFILE_FILE = "/app/results/bw_profile.dat"

# Ground truth machine parameters
GROUND_TRUTH_PEAK = 51.2
GROUND_TRUTH_BW = {
    "L1": 195.0,
    "L2": 78.0,
    "L3": 38.5,
    "DRAM": 19.2,
}

# STREAM raw values parsed from the benchmark output (GB/s)
STREAM_RAW = {
    "copy": 12.650,
    "scale": 12.480,
    "add": 14.320,
    "triad": 14.180,
}

# Expected kernel properties
EXPECTED_KERNELS = {
    "sparse_matvec": {"ai": 0.125, "level": "DRAM", "bound": "memory"},
    "dense_gemm_small": {"ai": 40.0, "level": "L2", "bound": "compute"},
    "3d_stencil": {"ai": 0.5, "level": "L3", "bound": "memory"},
    "fft_1d": {"ai": 0.8, "level": "L3", "bound": "memory"},
    "particle_update": {"ai": 4.0, "level": "DRAM", "bound": "compute"},
    "histogram_reduction": {"ai": 0.125, "level": "L1", "bound": "memory"},
}

KERNEL_MEASURED = {
    "sparse_matvec": 2.1,
    "dense_gemm_small": 38.2,
    "3d_stencil": 17.8,
    "fft_1d": 28.5,
    "particle_update": 33.5,
    "histogram_reduction": 18.2,
}


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULT_FILE), f"Result file {RESULT_FILE} not found"
    with open(RESULT_FILE) as f:
        data = json.load(f)
    return data


# ---- Tool usage verification ----


class TestToolUsage:
    def test_bw_profile_exists(self):
        """C tool must be compiled and run to produce bw_profile.dat."""
        assert os.path.exists(BW_PROFILE_FILE), (
            "Bandwidth profile not found at /app/results/bw_profile.dat"
        )

    def test_bw_profile_has_data(self):
        """Output must contain multiple data rows."""
        with open(BW_PROFILE_FILE) as f:
            data_lines = [l for l in f if l.strip() and not l.startswith("#")]
        assert len(data_lines) >= 10, (
            f"bw_profile.dat has only {len(data_lines)} data rows, expected >= 10"
        )

    def test_bw_profile_format(self):
        """Output must have correct column structure."""
        with open(BW_PROFILE_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                assert len(parts) >= 3, (
                    f"Expected >= 3 columns, got {len(parts)}: {line}"
                )
                # First column should be working set in bytes (integer)
                int(parts[0])
                # Remaining columns should be floats
                for p in parts[1:]:
                    float(p)
                break  # just check first data line


# ---- Roofline chart tests ----


class TestRooflineChart:
    def test_svg_exists(self):
        assert os.path.exists(CHART_FILE), (
            f"Roofline chart not found at {CHART_FILE}"
        )

    def test_svg_valid(self):
        with open(CHART_FILE) as f:
            content = f.read()
        assert "<svg" in content[:1000], "File does not appear to be valid SVG"

    def test_svg_generated_by_gnuplot(self):
        """Chart must be rendered with gnuplot."""
        with open(CHART_FILE) as f:
            content = f.read()
        assert "gnuplot" in content.lower(), (
            "SVG does not contain gnuplot signature — chart must be generated "
            "using gnuplot"
        )

    def test_svg_has_title(self):
        with open(CHART_FILE) as f:
            content = f.read()
        assert "Hierarchical Roofline" in content, (
            "Chart missing required title containing 'Hierarchical Roofline'"
        )

    def test_svg_has_cache_level_labels(self):
        with open(CHART_FILE) as f:
            content = f.read()
        for level in ["L1", "L2", "L3", "DRAM"]:
            assert level in content, (
                f"Chart missing cache level label: {level}"
            )

    def test_svg_has_peak_label(self):
        with open(CHART_FILE) as f:
            content = f.read()
        assert "Peak" in content, "Chart missing peak compute label"

    def test_svg_has_kernel_labels(self):
        with open(CHART_FILE) as f:
            content = f.read().lower()
        markers = ["sparse", "gemm", "stencil", "fft", "particle", "histogram"]
        for m in markers:
            assert m in content, f"Chart missing kernel label containing '{m}'"

    def test_svg_reasonable_size(self):
        size = os.path.getsize(CHART_FILE)
        assert size > 3000, f"SVG too small ({size} bytes) — likely empty or broken"
        assert size < 1000000, f"SVG too large ({size} bytes)"


# ---- Structure tests ----


class TestStructure:
    def test_required_top_level_keys(self, results):
        for key in ["peak_gflops", "cache_hierarchy", "stream_corrected", "kernel_analysis"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_cache_hierarchy_is_list_of_four(self, results):
        hierarchy = results["cache_hierarchy"]
        assert isinstance(hierarchy, list)
        assert len(hierarchy) == 4, f"Expected 4 cache levels, got {len(hierarchy)}"

    def test_cache_hierarchy_entry_keys(self, results):
        for level in results["cache_hierarchy"]:
            assert "level" in level
            assert "bandwidth_gbps" in level
            assert "ridge_point" in level

    def test_kernel_analysis_count(self, results):
        assert len(results["kernel_analysis"]) == 6

    def test_kernel_analysis_entry_keys(self, results):
        required = {"name", "arithmetic_intensity", "cache_level", "bound",
                     "attainable_gflops", "efficiency"}
        for k in results["kernel_analysis"]:
            missing = required - set(k.keys())
            assert not missing, f"Kernel {k.get('name', '?')} missing keys: {missing}"

    def test_stream_corrected_keys(self, results):
        required = {"copy_gbps", "scale_gbps", "add_gbps", "triad_gbps", "average_gbps"}
        missing = required - set(results["stream_corrected"].keys())
        assert not missing, f"stream_corrected missing keys: {missing}"


# ---- Peak performance ----


class TestPeakPerformance:
    def test_peak_gflops_within_tolerance(self, results):
        peak = results["peak_gflops"]
        rel_err = abs(peak - GROUND_TRUTH_PEAK) / GROUND_TRUTH_PEAK
        assert rel_err < 0.10, (
            f"Peak GFLOP/s {peak:.2f} not within 10% of {GROUND_TRUTH_PEAK}"
        )


# ---- Cache hierarchy ----


class TestCacheHierarchy:
    def test_level_names_present(self, results):
        names = {h["level"] for h in results["cache_hierarchy"]}
        for expected in ("L1", "L2", "L3", "DRAM"):
            assert expected in names, f"Missing cache level: {expected}"

    def test_bandwidth_decreasing_order(self, results):
        bws = [h["bandwidth_gbps"] for h in results["cache_hierarchy"]]
        for i in range(len(bws) - 1):
            assert bws[i] > bws[i + 1], (
                f"Bandwidth not decreasing: {bws[i]} vs {bws[i + 1]}"
            )

    @pytest.mark.parametrize("level,expected_bw", list(GROUND_TRUTH_BW.items()))
    def test_bandwidth_value(self, results, level, expected_bw):
        levels = {h["level"]: h for h in results["cache_hierarchy"]}
        actual = levels[level]["bandwidth_gbps"]
        rel_err = abs(actual - expected_bw) / expected_bw
        assert rel_err < 0.15, (
            f"{level} bandwidth {actual:.2f} not within 15% of {expected_bw} "
            f"(error {rel_err:.1%})"
        )

    def test_ridge_point_consistency(self, results):
        peak = results["peak_gflops"]
        for h in results["cache_hierarchy"]:
            expected_ridge = peak / h["bandwidth_gbps"]
            actual_ridge = h["ridge_point"]
            rel_err = abs(actual_ridge - expected_ridge) / expected_ridge
            assert rel_err < 0.02, (
                f"{h['level']} ridge point {actual_ridge:.4f} != "
                f"peak/bw = {expected_ridge:.4f}"
            )

    def test_l1_cache_size(self, results):
        levels = {h["level"]: h for h in results["cache_hierarchy"]}
        if "size_bytes" in levels["L1"]:
            s = levels["L1"]["size_bytes"]
            assert 16384 <= s <= 65536, f"L1 size {s} not in [16KB, 64KB]"

    def test_l2_cache_size(self, results):
        levels = {h["level"]: h for h in results["cache_hierarchy"]}
        if "size_bytes" in levels["L2"]:
            s = levels["L2"]["size_bytes"]
            assert 131072 <= s <= 524288, f"L2 size {s} not in [128KB, 512KB]"

    def test_l3_cache_size(self, results):
        levels = {h["level"]: h for h in results["cache_hierarchy"]}
        if "size_bytes" in levels["L3"]:
            s = levels["L3"]["size_bytes"]
            assert 4194304 <= s <= 16777216, f"L3 size {s} not in [4MB, 16MB]"

    def test_dram_has_no_size(self, results):
        levels = {h["level"]: h for h in results["cache_hierarchy"]}
        assert "size_bytes" not in levels["DRAM"], (
            "DRAM level should not have size_bytes"
        )


# ---- STREAM write-allocate corrections ----


class TestStreamCorrections:
    def test_copy_correction(self, results):
        expected = STREAM_RAW["copy"] * 1.5
        actual = results["stream_corrected"]["copy_gbps"]
        assert abs(actual - expected) < 0.01, (
            f"Copy: {actual} != {expected}"
        )

    def test_scale_correction(self, results):
        expected = STREAM_RAW["scale"] * 1.5
        actual = results["stream_corrected"]["scale_gbps"]
        assert abs(actual - expected) < 0.01, (
            f"Scale: {actual} != {expected}"
        )

    def test_add_correction(self, results):
        expected = STREAM_RAW["add"] * (4.0 / 3.0)
        actual = results["stream_corrected"]["add_gbps"]
        assert abs(actual - expected) < 0.01, (
            f"Add: {actual} != {expected}"
        )

    def test_triad_correction(self, results):
        expected = STREAM_RAW["triad"] * (4.0 / 3.0)
        actual = results["stream_corrected"]["triad_gbps"]
        assert abs(actual - expected) < 0.01, (
            f"Triad: {actual} != {expected}"
        )

    def test_average_is_mean_of_corrected(self, results):
        sc = results["stream_corrected"]
        expected_avg = (
            sc["copy_gbps"] + sc["scale_gbps"] + sc["add_gbps"] + sc["triad_gbps"]
        ) / 4.0
        assert abs(sc["average_gbps"] - expected_avg) < 0.01, (
            f"Average: {sc['average_gbps']} != {expected_avg}"
        )


# ---- Kernel analysis ----


class TestKernelAnalysis:
    def _by_name(self, results):
        return {k["name"]: k for k in results["kernel_analysis"]}

    def test_all_kernels_present(self, results):
        names = {k["name"] for k in results["kernel_analysis"]}
        for expected in EXPECTED_KERNELS:
            assert expected in names, f"Missing kernel: {expected}"

    @pytest.mark.parametrize("name,props", list(EXPECTED_KERNELS.items()))
    def test_arithmetic_intensity(self, results, name, props):
        k = self._by_name(results)[name]
        expected_ai = props["ai"]
        rel_err = abs(k["arithmetic_intensity"] - expected_ai) / expected_ai
        assert rel_err < 0.001, (
            f"{name} AI: {k['arithmetic_intensity']} != {expected_ai}"
        )

    @pytest.mark.parametrize("name,props", list(EXPECTED_KERNELS.items()))
    def test_cache_level_assignment(self, results, name, props):
        k = self._by_name(results)[name]
        assert k["cache_level"] == props["level"], (
            f"{name} cache level: {k['cache_level']} != {props['level']}"
        )

    @pytest.mark.parametrize("name,props", list(EXPECTED_KERNELS.items()))
    def test_bound_classification(self, results, name, props):
        k = self._by_name(results)[name]
        assert k["bound"] == props["bound"], (
            f"{name} bound: {k['bound']} != {props['bound']}"
        )

    def test_attainable_consistency(self, results):
        """attainable should equal min(peak, AI * level_bw)."""
        peak = results["peak_gflops"]
        levels = {h["level"]: h for h in results["cache_hierarchy"]}

        for k in results["kernel_analysis"]:
            bw = levels[k["cache_level"]]["bandwidth_gbps"]
            ai = k["arithmetic_intensity"]
            expected = min(peak, ai * bw)
            rel_err = abs(k["attainable_gflops"] - expected) / max(expected, 1e-9)
            assert rel_err < 0.05, (
                f"{k['name']} attainable: {k['attainable_gflops']:.4f} != "
                f"{expected:.4f}"
            )

    def test_efficiency_consistency(self, results):
        """efficiency should equal measured / attainable."""
        for k in results["kernel_analysis"]:
            measured = KERNEL_MEASURED[k["name"]]
            expected_eff = measured / k["attainable_gflops"]
            rel_err = abs(k["efficiency"] - expected_eff) / max(expected_eff, 1e-9)
            assert rel_err < 0.05, (
                f"{k['name']} efficiency: {k['efficiency']:.4f} != "
                f"{expected_eff:.4f}"
            )

    def test_efficiency_in_valid_range(self, results):
        for k in results["kernel_analysis"]:
            assert 0 < k["efficiency"] <= 1.05, (
                f"{k['name']} efficiency {k['efficiency']} not in (0, 1.05]"
            )
