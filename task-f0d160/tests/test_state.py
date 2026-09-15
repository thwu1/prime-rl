"""
Tests for multi-GPU attention workload placement engine.

"""

import json
import math
import os
import ctypes
import pytest

REPORT_PATH = "/app/report.json"
REL_TOL = 1e-6

# Hardware specs matching /app/data/hardware.db
GPUS = {
    "NVIDIA H100 SXM": {"peak_tflops": 312.0, "bandwidth_gb_s": 2000.0, "memory_gb": 80.0},
    "NVIDIA H100 PCIe": {"peak_tflops": 267.6, "bandwidth_gb_s": 2000.0, "memory_gb": 80.0},
    "NVIDIA A100 SXM": {"peak_tflops": 156.0, "bandwidth_gb_s": 2039.0, "memory_gb": 80.0},
    "NVIDIA A100 PCIe": {"peak_tflops": 156.0, "bandwidth_gb_s": 1555.0, "memory_gb": 40.0},
}

GPU_NAMES = sorted(GPUS.keys())

# Scenario parameters: (name, h, h_kv, d, n_layers, dtype_bytes, b, lq, lkv)
SCENARIOS = [
    ("decode_gqa4", 32, 8, 128, 32, 2, 1, 1, 4096),
    ("prefill_gqa4", 32, 8, 128, 32, 2, 1, 2048, 2048),
    ("decode_mqa", 32, 1, 128, 32, 2, 1, 1, 2048),
    ("prefill_mha", 16, 16, 64, 12, 2, 4, 512, 512),
    ("decode_gqa8", 64, 8, 128, 80, 2, 16, 1, 8192),
]


def compute_ridge(gpu):
    return (gpu["peak_tflops"] * 1e12) / (gpu["bandwidth_gb_s"] * 1e9)


def compute_flops(b, h, lq, lkv, d):
    """Attention FLOPs: 2*b*h*lq*lkv*d (QK^T) + 2*b*h*lq*lkv*d (S*V)."""
    return 2 * b * h * lq * lkv * d + 2 * b * h * lq * lkv * d


def compute_memory(b, h, h_kv, lq, lkv, d, dtype_bytes):
    """Memory: Q(h heads) + K(h_kv heads) + V(h_kv heads) + O(h heads)."""
    return dtype_bytes * (
        b * h * lq * d
        + b * h_kv * lkv * d
        + b * h_kv * lkv * d
        + b * h * lq * d
    )


def compute_kv_cache(b, h_kv, lkv, d, dtype_bytes, n_layers):
    """KV cache: 2 (key+value) * batch * layers * h_kv * seq * d * dtype."""
    return 2 * b * n_layers * h_kv * lkv * d * dtype_bytes


def compute_roofline_tflops(ai, gpu):
    bw_bytes = gpu["bandwidth_gb_s"] * 1e9
    peak_flops = gpu["peak_tflops"] * 1e12
    return min(ai * bw_bytes, peak_flops) / 1e12


def find_optimal_gpu(ai, kv_bytes):
    """Find optimal GPU: highest roofline among feasible GPUs."""
    candidates = []
    for gname, gpu in GPUS.items():
        fits = kv_bytes <= gpu["memory_gb"] * 1e9
        if fits:
            rtf = compute_roofline_tflops(ai, gpu)
            candidates.append((gname, rtf, gpu["peak_tflops"]))
    candidates.sort(key=lambda x: (-x[1], -x[2], x[0]))
    return candidates[0][0] if candidates else None


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


class TestRooflineLibrary:
    """Verify the C shared library has been corrected."""

    def test_gb_to_bytes_si_convention(self):
        lib = ctypes.CDLL("/app/libroofline.so")
        lib.gb_to_bytes.argtypes = [ctypes.c_double]
        lib.gb_to_bytes.restype = ctypes.c_double
        result = lib.gb_to_bytes(1.0)
        assert result == 1e9, f"gb_to_bytes(1.0) must equal 1e9 (SI), got {result}"

    def test_gb_to_bytes_large_value(self):
        lib = ctypes.CDLL("/app/libroofline.so")
        lib.gb_to_bytes.argtypes = [ctypes.c_double]
        lib.gb_to_bytes.restype = ctypes.c_double
        result = lib.gb_to_bytes(2000.0)
        assert result == 2e12, f"gb_to_bytes(2000.0) must equal 2e12, got {result}"

    def test_achievable_flops_compute_bound(self):
        lib = ctypes.CDLL("/app/libroofline.so")
        lib.achievable_flops.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
        lib.achievable_flops.restype = ctypes.c_double
        # AI * bandwidth >> peak → should return peak (not sum)
        result = lib.achievable_flops(1000.0, 1e9, 50e9)
        assert result == 50e9, (
            f"achievable_flops should cap at peak_flops=50e9, got {result}"
        )

    def test_achievable_flops_memory_bound(self):
        lib = ctypes.CDLL("/app/libroofline.so")
        lib.achievable_flops.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
        lib.achievable_flops.restype = ctypes.c_double
        # AI * bandwidth << peak → should return AI * bandwidth
        result = lib.achievable_flops(10.0, 1e9, 50e9)
        assert result == 10e9, (
            f"achievable_flops should return mem_bound=10e9, got {result}"
        )


class TestReportStructure:
    def test_has_gpus_section(self, report):
        assert "gpus" in report
        assert set(report["gpus"].keys()) == set(GPUS.keys())

    def test_has_all_scenarios(self, report):
        assert "scenarios" in report
        expected = {"decode_gqa4", "prefill_gqa4", "decode_mqa", "prefill_mha", "decode_gqa8"}
        assert set(report["scenarios"].keys()) == expected

    def test_has_critical_prefill_for_all_gpus(self, report):
        assert "critical_prefill_seq_lens" in report
        assert set(report["critical_prefill_seq_lens"].keys()) == set(GPUS.keys())

    def test_has_group_analysis(self, report):
        assert "group_size_analysis" in report

    def test_each_scenario_has_gpu_evaluation(self, report):
        for sname, sdata in report["scenarios"].items():
            assert "gpu_evaluation" in sdata, f"{sname} missing gpu_evaluation"
            assert set(sdata["gpu_evaluation"].keys()) == set(GPUS.keys()), (
                f"{sname} gpu_evaluation missing GPUs"
            )

    def test_each_scenario_has_optimal_gpu(self, report):
        for sname, sdata in report["scenarios"].items():
            assert "optimal_gpu" in sdata, f"{sname} missing optimal_gpu"
            assert sdata["optimal_gpu"] in GPUS, (
                f"{sname} optimal_gpu '{sdata['optimal_gpu']}' not a valid GPU"
            )


class TestRidgePoints:
    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_ridge_point(self, report, gpu_name):
        expected = compute_ridge(GPUS[gpu_name])
        actual = report["gpus"][gpu_name]["ridge_point"]
        assert math.isclose(actual, expected, rel_tol=REL_TOL), (
            f"{gpu_name}: expected ridge={expected}, got {actual}"
        )

    def test_h100_sxm_ridge_exact(self, report):
        assert math.isclose(report["gpus"]["NVIDIA H100 SXM"]["ridge_point"], 156.0, rel_tol=REL_TOL)


class TestScenarioFlops:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    def test_attention_flops(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv):
        expected = compute_flops(b, h, lq, lkv, d)
        actual = report["scenarios"][name]["attention_flops"]
        assert actual == expected, (
            f"{name}: expected flops={expected}, got {actual}"
        )


class TestScenarioMemory:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    def test_attention_memory_bytes(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv):
        expected = compute_memory(b, h, h_kv, lq, lkv, d, dtype)
        actual = report["scenarios"][name]["attention_memory_bytes"]
        assert actual == expected, (
            f"{name}: expected mem={expected}, got {actual}"
        )


class TestScenarioArithmeticIntensity:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    def test_arithmetic_intensity(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv):
        flops = compute_flops(b, h, lq, lkv, d)
        mem = compute_memory(b, h, h_kv, lq, lkv, d, dtype)
        expected = flops / mem
        actual = report["scenarios"][name]["arithmetic_intensity"]
        assert math.isclose(actual, expected, rel_tol=REL_TOL), (
            f"{name}: expected AI={expected}, got {actual}"
        )


class TestScenarioKVCache:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    def test_kv_cache_bytes(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv):
        expected = compute_kv_cache(b, h_kv, lkv, d, dtype, n_layers)
        actual = report["scenarios"][name]["kv_cache_bytes"]
        assert actual == expected, (
            f"{name}: expected kv_cache={expected}, got {actual}"
        )


class TestGPURoofline:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_roofline_tflops(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv, gpu_name):
        flops = compute_flops(b, h, lq, lkv, d)
        mem = compute_memory(b, h, h_kv, lq, lkv, d, dtype)
        ai = flops / mem
        expected = compute_roofline_tflops(ai, GPUS[gpu_name])
        actual = report["scenarios"][name]["gpu_evaluation"][gpu_name]["roofline_tflops"]
        assert math.isclose(actual, expected, rel_tol=REL_TOL), (
            f"{name}/{gpu_name}: expected roofline={expected}, got {actual}"
        )


class TestGPUBoundClassification:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_is_memory_bound(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv, gpu_name):
        flops = compute_flops(b, h, lq, lkv, d)
        mem = compute_memory(b, h, h_kv, lq, lkv, d, dtype)
        ai = flops / mem
        ridge = compute_ridge(GPUS[gpu_name])
        expected = ai < ridge
        actual = report["scenarios"][name]["gpu_evaluation"][gpu_name]["is_memory_bound"]
        assert actual == expected, (
            f"{name}/{gpu_name}: AI={ai:.4f}, ridge={ridge:.4f}, "
            f"expected bound={expected}, got {actual}"
        )


class TestKVCacheFeasibility:
    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_kv_cache_fits(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv, gpu_name):
        kv = compute_kv_cache(b, h_kv, lkv, d, dtype, n_layers)
        expected = kv <= GPUS[gpu_name]["memory_gb"] * 1e9
        actual = report["scenarios"][name]["gpu_evaluation"][gpu_name]["kv_cache_fits"]
        assert actual == expected, (
            f"{name}/{gpu_name}: kv={kv}, capacity={GPUS[gpu_name]['memory_gb'] * 1e9}, "
            f"expected fits={expected}, got {actual}"
        )

    def test_decode_gqa8_excluded_from_a100_pcie(self, report):
        """decode_gqa8 KV cache (~43GB) exceeds A100 PCIe HBM (40GB)."""
        assert report["scenarios"]["decode_gqa8"]["gpu_evaluation"]["NVIDIA A100 PCIe"]["kv_cache_fits"] is False


class TestOptimalGPUSelection:
    """Core evaluation tests: verify optimal GPU selection logic."""

    @pytest.mark.parametrize(
        "name,h,h_kv,d,n_layers,dtype,b,lq,lkv", SCENARIOS
    )
    def test_optimal_gpu(self, report, name, h, h_kv, d, n_layers, dtype, b, lq, lkv):
        flops = compute_flops(b, h, lq, lkv, d)
        mem = compute_memory(b, h, h_kv, lq, lkv, d, dtype)
        ai = flops / mem
        kv = compute_kv_cache(b, h_kv, lkv, d, dtype, n_layers)
        expected = find_optimal_gpu(ai, kv)
        actual = report["scenarios"][name]["optimal_gpu"]
        assert actual == expected, (
            f"{name}: expected optimal={expected}, got {actual}"
        )

    def test_memory_bound_workloads_prefer_high_bandwidth(self, report):
        """Memory-bound decode workloads should prefer A100 SXM (2039 GB/s bandwidth)."""
        for name in ["decode_gqa4", "decode_mqa", "decode_gqa8"]:
            assert report["scenarios"][name]["optimal_gpu"] == "NVIDIA A100 SXM", (
                f"{name} should prefer A100 SXM (highest bandwidth) for memory-bound decode"
            )

    def test_compute_bound_workloads_prefer_high_peak(self, report):
        """Compute-bound prefill workloads should prefer H100 SXM (312 TFLOPS peak)."""
        for name in ["prefill_gqa4", "prefill_mha"]:
            assert report["scenarios"][name]["optimal_gpu"] == "NVIDIA H100 SXM", (
                f"{name} should prefer H100 SXM (highest peak) for compute-bound prefill"
            )

    def test_infeasible_gpu_not_selected(self, report):
        """A GPU where KV cache doesn't fit must not be selected as optimal."""
        assert report["scenarios"]["decode_gqa8"]["optimal_gpu"] != "NVIDIA A100 PCIe"


class TestCriticalPrefillSeqLens:
    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_critical_value(self, report, gpu_name):
        h, h_kv, dtype = 32, 8, 2
        ridge = compute_ridge(GPUS[gpu_name])
        min_L = ridge * dtype * (h + h_kv) / (2 * h)
        expected = math.ceil(min_L)
        actual = report["critical_prefill_seq_lens"][gpu_name]
        assert actual == expected, (
            f"{gpu_name}: expected critical_L={expected}, got {actual}"
        )

    def test_h100_sxm_is_195(self, report):
        assert report["critical_prefill_seq_lens"]["NVIDIA H100 SXM"] == 195

    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_boundary_below_is_memory_bound(self, report, gpu_name):
        """L-1 should still be memory-bound."""
        h, h_kv, dtype = 32, 8, 2
        ridge = compute_ridge(GPUS[gpu_name])
        L = report["critical_prefill_seq_lens"][gpu_name] - 1
        ai = 2 * h * L / (dtype * (h + h_kv))
        assert ai < ridge, (
            f"{gpu_name}: L={L} gives AI={ai} which should be < ridge={ridge}"
        )

    @pytest.mark.parametrize("gpu_name", GPU_NAMES)
    def test_boundary_at_is_compute_bound(self, report, gpu_name):
        """At the critical L, workload should be compute-bound."""
        h, h_kv, dtype = 32, 8, 2
        ridge = compute_ridge(GPUS[gpu_name])
        L = report["critical_prefill_seq_lens"][gpu_name]
        ai = 2 * h * L / (dtype * (h + h_kv))
        assert ai >= ridge, (
            f"{gpu_name}: L={L} gives AI={ai} which should be >= ridge={ridge}"
        )

    def test_gpus_have_different_critical_lengths(self, report):
        """Different ridge points should produce different critical lengths."""
        values = list(report["critical_prefill_seq_lens"].values())
        assert len(set(values)) > 1, (
            "All GPUs have the same critical length — they should differ"
        )


class TestGroupSizeAnalysis:
    EXPECTED_GROUPS = {1, 2, 4, 8, 16, 32}

    def test_all_valid_groups_present(self, report):
        actual = set(int(k) for k in report["group_size_analysis"].keys())
        assert actual == self.EXPECTED_GROUPS, (
            f"Expected groups {self.EXPECTED_GROUPS}, got {actual}"
        )

    @pytest.mark.parametrize("g", [1, 2, 4, 8, 16, 32])
    def test_group_ai_value(self, report, g):
        h, d, dtype, lkv = 32, 128, 2, 4096
        h_kv = h // g
        flops = compute_flops(1, h, 1, lkv, d)
        mem = compute_memory(1, h, h_kv, 1, lkv, d, dtype)
        expected = flops / mem
        actual = report["group_size_analysis"][str(g)]
        assert math.isclose(actual, expected, rel_tol=REL_TOL), (
            f"g={g}: expected AI={expected}, got {actual}"
        )

    def test_monotonically_increasing(self, report):
        """Larger group size should yield higher arithmetic intensity."""
        gs = sorted(int(k) for k in report["group_size_analysis"].keys())
        ais = [report["group_size_analysis"][str(g)] for g in gs]
        for i in range(len(ais) - 1):
            assert ais[i] < ais[i + 1], (
                f"AI not increasing: g={gs[i]}={ais[i]} >= g={gs[i + 1]}={ais[i + 1]}"
            )


class TestConsistencyChecks:
    """Cross-scenario consistency checks that catch systematic errors."""

    def test_decode_gqa4_ai_near_4(self, report):
        """For decode with g=4 and long KV, AI should approximate g."""
        ai = report["scenarios"]["decode_gqa4"]["arithmetic_intensity"]
        assert 3.99 < ai < 4.01, f"decode_gqa4 AI should be ~4 (g=4), got {ai}"

    def test_prefill_mha_ai_exactly_256(self, report):
        """MHA prefill with L=512, dtype=2: AI = L/dtype = 256."""
        ai = report["scenarios"]["prefill_mha"]["arithmetic_intensity"]
        assert math.isclose(ai, 256.0, rel_tol=REL_TOL), (
            f"prefill_mha AI should be 256.0, got {ai}"
        )

    def test_all_decode_memory_bound_on_every_gpu(self, report):
        """All decode scenarios should be memory-bound on every GPU."""
        for name in ["decode_gqa4", "decode_mqa", "decode_gqa8"]:
            for gpu_name in GPUS:
                assert report["scenarios"][name]["gpu_evaluation"][gpu_name]["is_memory_bound"] is True, (
                    f"{name} should be memory-bound on {gpu_name}"
                )

    def test_all_prefill_compute_bound_on_every_gpu(self, report):
        """Both prefill scenarios should be compute-bound on every GPU."""
        for name in ["prefill_gqa4", "prefill_mha"]:
            for gpu_name in GPUS:
                assert report["scenarios"][name]["gpu_evaluation"][gpu_name]["is_memory_bound"] is False, (
                    f"{name} should be compute-bound on {gpu_name}"
                )

    def test_roofline_never_exceeds_peak(self, report):
        """No roofline prediction should exceed a GPU's peak TFLOPS."""
        for sname, sdata in report["scenarios"].items():
            for gpu_name, gpu in GPUS.items():
                actual = sdata["gpu_evaluation"][gpu_name]["roofline_tflops"]
                assert actual <= gpu["peak_tflops"] + 1e-6, (
                    f"{sname}/{gpu_name}: roofline={actual} exceeds peak={gpu['peak_tflops']}"
                )

    def test_a100_sxm_beats_h100_for_memory_bound(self, report):
        """A100 SXM (2039 GB/s) should outperform H100 SXM (2000 GB/s) on memory-bound work."""
        for name in ["decode_gqa4", "decode_mqa"]:
            a100 = report["scenarios"][name]["gpu_evaluation"]["NVIDIA A100 SXM"]["roofline_tflops"]
            h100 = report["scenarios"][name]["gpu_evaluation"]["NVIDIA H100 SXM"]["roofline_tflops"]
            assert a100 > h100, (
                f"{name}: A100 SXM ({a100:.3f}) should beat H100 SXM ({h100:.3f}) "
                f"for memory-bound workloads (higher bandwidth)"
            )

    def test_h100_sxm_beats_a100_for_compute_bound(self, report):
        """H100 SXM (312 TFLOPS) should outperform A100 SXM (156 TFLOPS) on compute-bound work."""
        for name in ["prefill_gqa4", "prefill_mha"]:
            h100 = report["scenarios"][name]["gpu_evaluation"]["NVIDIA H100 SXM"]["roofline_tflops"]
            a100 = report["scenarios"][name]["gpu_evaluation"]["NVIDIA A100 SXM"]["roofline_tflops"]
            assert h100 > a100, (
                f"{name}: H100 SXM ({h100:.3f}) should beat A100 SXM ({a100:.3f}) "
                f"for compute-bound workloads (higher peak)"
            )

    def test_ridge_points_ordered(self, report):
        """Ridge points should reflect peak/bandwidth ratios correctly."""
        ridges = {gn: report["gpus"][gn]["ridge_point"] for gn in GPUS}
        # H100 SXM has highest peak/bw ratio, A100 SXM has lowest
        assert ridges["NVIDIA H100 SXM"] > ridges["NVIDIA H100 PCIe"]
        assert ridges["NVIDIA H100 PCIe"] > ridges["NVIDIA A100 PCIe"]
        assert ridges["NVIDIA A100 PCIe"] > ridges["NVIDIA A100 SXM"]
