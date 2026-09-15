
import subprocess
import re
import os
import json
import pytest

SEED = "42"
ORIGINAL = "/app/.original/pipeline"
OPTIMIZED = "/app/pipeline"
RUNS = 3
MIN_SPEEDUP = 3.0
ANALYSIS_PATH = "/app/analysis.json"


def run_pipeline(binary, output_path, timeout=180):
    """Run a pipeline binary and return (elapsed_seconds, output_lines)."""
    result = subprocess.run(
        [binary, SEED, output_path],
        capture_output=True, timeout=timeout
    )
    assert result.returncode == 0, (
        f"{binary} exited with code {result.returncode}: "
        f"{result.stderr.decode()[:500]}"
    )
    time_match = re.search(r"TIME=([\d.]+)", result.stderr.decode())
    assert time_match, (
        f"Could not parse TIME from stderr of {binary}: "
        f"{result.stderr.decode()[:500]}"
    )
    elapsed = float(time_match.group(1))
    with open(output_path) as f:
        lines = f.readlines()
    return elapsed, lines


# ──────────────────────────────────────────────
# Analysis report tests
# ──────────────────────────────────────────────

class TestAnalysisReport:
    """Validate the cachegrind-based performance diagnosis report."""

    def test_analysis_exists(self):
        assert os.path.isfile(ANALYSIS_PATH), (
            f"Analysis report not found at {ANALYSIS_PATH}. "
            "Profile the pipeline with cachegrind and write this file."
        )

    def test_analysis_valid_json(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_cache_config_present(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        cc = data.get("cache_config", {})
        assert "l1d_size_bytes" in cc, "Missing l1d_size_bytes"
        assert "l1d_line_bytes" in cc, "Missing l1d_line_bytes"
        assert "l1d_associativity" in cc, "Missing l1d_associativity"
        assert isinstance(cc["l1d_size_bytes"], int) and cc["l1d_size_bytes"] > 0
        assert cc["l1d_line_bytes"] == 64, (
            f"L1 cache line size should be 64 bytes, got {cc['l1d_line_bytes']}"
        )
        assert isinstance(cc["l1d_associativity"], int) and cc["l1d_associativity"] > 0

    def test_all_kernels_profiled(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        kp = data.get("kernel_profiles", {})
        expected = {"analyze_sensors", "normalize_data",
                    "compute_distances", "smooth_data"}
        assert set(kp.keys()) == expected, (
            f"kernel_profiles must contain exactly {expected}, "
            f"got {set(kp.keys())}"
        )

    def test_kernel_profile_fields(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        for name, profile in data["kernel_profiles"].items():
            assert "d1_read_miss_rate_pct" in profile, (
                f"{name}: missing d1_read_miss_rate_pct"
            )
            assert isinstance(profile["d1_read_miss_rate_pct"], (int, float)), (
                f"{name}: d1_read_miss_rate_pct must be numeric"
            )
            assert profile["d1_read_miss_rate_pct"] >= 0, (
                f"{name}: d1_read_miss_rate_pct must be non-negative"
            )
            assert "classification" in profile, (
                f"{name}: missing classification"
            )
            assert profile["classification"] in ("cache_bound", "compute_bound"), (
                f"{name}: classification must be 'cache_bound' or "
                f"'compute_bound', got '{profile['classification']}'"
            )

    def test_cache_bound_classifications(self):
        """Column-major kernels must be classified as cache_bound."""
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        kp = data["kernel_profiles"]
        for name in ["analyze_sensors", "normalize_data", "compute_distances"]:
            assert kp[name]["classification"] == "cache_bound", (
                f"{name} uses column-major (stride-4096) access and must be "
                f"classified as cache_bound, got '{kp[name]['classification']}'"
            )

    def test_compute_bound_classification(self):
        """Row-major smooth_data must be classified as compute_bound."""
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        kp = data["kernel_profiles"]
        assert kp["smooth_data"]["classification"] == "compute_bound", (
            "smooth_data uses row-major access with low D1 miss rate and "
            "should be compute_bound, got "
            f"'{kp['smooth_data']['classification']}'"
        )

    def test_miss_rate_ordering(self):
        """Cache-bound kernels must have higher miss rates than smooth_data."""
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        kp = data["kernel_profiles"]
        cache_rates = [
            kp[k]["d1_read_miss_rate_pct"]
            for k in ["analyze_sensors", "normalize_data", "compute_distances"]
        ]
        smooth_rate = kp["smooth_data"]["d1_read_miss_rate_pct"]
        min_cache = min(cache_rates)
        assert smooth_rate < min_cache, (
            f"smooth_data miss rate ({smooth_rate:.1f}%) must be lower than "
            f"all cache-bound kernels (min={min_cache:.1f}%)"
        )

    def test_most_impactful_is_cache_bound(self):
        with open(ANALYSIS_PATH) as f:
            data = json.load(f)
        assert "most_cache_impactful" in data
        assert data["most_cache_impactful"] in [
            "analyze_sensors", "normalize_data", "compute_distances"
        ], (
            f"most_cache_impactful must be a cache-bound kernel, "
            f"got '{data['most_cache_impactful']}'"
        )


# ──────────────────────────────────────────────
# Optimization tests
# ──────────────────────────────────────────────

class TestOptimization:
    """Validate the optimized pipeline implementation."""

    def test_optimized_binary_exists(self):
        assert os.path.isfile(OPTIMIZED), (
            f"Optimized binary not found at {OPTIMIZED}. Did 'make' succeed?"
        )

    def test_correctness(self):
        """Optimized output must match original output numerically."""
        _, orig_lines = run_pipeline(ORIGINAL, "/tmp/orig_out.txt")
        _, opt_lines = run_pipeline(OPTIMIZED, "/tmp/opt_out.txt")

        assert len(orig_lines) == len(opt_lines), (
            f"Line count mismatch: original={len(orig_lines)}, "
            f"optimized={len(opt_lines)}"
        )

        for i, (ol, pl) in enumerate(zip(orig_lines, opt_lines)):
            o_nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", ol)
            p_nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", pl)
            assert len(o_nums) == len(p_nums), (
                f"Line {i+1}: different number of numeric values "
                f"({len(o_nums)} vs {len(p_nums)})"
            )
            for ov, pv in zip(o_nums, p_nums):
                of = float(ov)
                pf = float(pv)
                if abs(of) > 1e-10:
                    rel_err = abs(of - pf) / abs(of)
                    assert rel_err < 1e-6, (
                        f"Line {i+1}: relative error {rel_err:.2e} "
                        f"(original={ov}, optimized={pv})"
                    )
                else:
                    assert abs(of - pf) < 1e-12, (
                        f"Line {i+1}: absolute error "
                        f"(original={ov}, optimized={pv})"
                    )

    def test_performance(self):
        """Optimized version must be at least 3x faster than original."""
        orig_times = []
        for run_idx in range(RUNS):
            t, _ = run_pipeline(
                ORIGINAL, f"/tmp/perf_orig_{run_idx}.txt"
            )
            orig_times.append(t)

        opt_times = []
        for run_idx in range(RUNS):
            t, _ = run_pipeline(
                OPTIMIZED, f"/tmp/perf_opt_{run_idx}.txt"
            )
            opt_times.append(t)

        orig_median = sorted(orig_times)[RUNS // 2]
        opt_median = sorted(opt_times)[RUNS // 2]

        speedup = orig_median / opt_median if opt_median > 0 else float("inf")
        assert speedup >= MIN_SPEEDUP, (
            f"Speedup {speedup:.2f}x is below {MIN_SPEEDUP}x threshold "
            f"(original median: {orig_median:.4f}s, "
            f"optimized median: {opt_median:.4f}s)"
        )
