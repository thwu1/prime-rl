"""Tests for multi-architecture HPC stencil performance analysis framework.

Validates config loading, stencil FLOP/byte counting with write-allocate,
roofline model predictions across cache hierarchies, parallel scaling laws,
performance portability metrics, cache-aware tiling, C kernel verification,
and the full analysis pipeline output.
"""


import json
import math
import os
import sys

import pytest

sys.path.insert(0, "/app")


# ============================================================
# Reference configs for isolated module tests (independent of config_loader)
# ============================================================

SKYLAKE_CFG = {
    "name": "Skylake",
    "peak_flops": 1200e9,
    "dram_bandwidth": 120e9,
    "l3_bandwidth": 400e9,
    "l2_bandwidth": 900e9,
    "l3_size": 33 * 1024**2,   # 34603008
    "l2_size": 1024 * 1024,    # 1048576
    "cacheline_bytes": 64,
    "write_allocate": True,
    "elem_bytes": 8,
}

A64FX_CFG = {
    "name": "A64FX",
    "peak_flops": 3380e9,
    "dram_bandwidth": 1024e9,
    "l3_bandwidth": None,
    "l2_bandwidth": 3600e9,
    "l3_size": None,
    "l2_size": 8192 * 1024,    # 8388608
    "cacheline_bytes": 256,
    "write_allocate": False,
    "elem_bytes": 8,
}

EPYC_CFG = {
    "name": "EPYC",
    "peak_flops": 1800e9,
    "dram_bandwidth": 200e9,
    "l3_bandwidth": 500e9,
    "l2_bandwidth": 1200e9,
    "l3_size": 256 * 1024**2,  # 268435456
    "l2_size": 512 * 1024,     # 524288
    "cacheline_bytes": 64,
    "write_allocate": True,
    "elem_bytes": 8,
}


# ============================================================
# Configuration loader
# ============================================================


class TestConfigLoader:
    """Verify config files are loaded and normalized to SI units."""

    def test_skylake_peak_flops(self):
        from config_loader import load_config
        cfg = load_config("/app/configs/skylake.json")
        assert cfg["peak_flops"] == 1200e9, (
            f"Skylake peak should be 1.2e12, got {cfg['peak_flops']}"
        )

    def test_skylake_dram_bandwidth(self):
        from config_loader import load_config
        cfg = load_config("/app/configs/skylake.json")
        assert cfg["dram_bandwidth"] == 120e9, (
            f"Skylake DRAM BW should be 120e9 B/s, got {cfg['dram_bandwidth']}"
        )

    def test_skylake_l3_bandwidth(self):
        from config_loader import load_config
        cfg = load_config("/app/configs/skylake.json")
        assert cfg["l3_bandwidth"] == 400e9, (
            f"Skylake L3 BW should be 400e9 B/s, got {cfg['l3_bandwidth']}"
        )

    def test_a64fx_no_l3(self):
        from config_loader import load_config
        cfg = load_config("/app/configs/a64fx.json")
        assert cfg["l3_size"] is None, "A64FX should have no L3 cache"
        assert cfg["l3_bandwidth"] is None, "A64FX should have no L3 bandwidth"

    def test_epyc_l3_size(self):
        from config_loader import load_config
        cfg = load_config("/app/configs/epyc.json")
        expected = 256 * 1024 * 1024
        assert cfg["l3_size"] == expected, (
            f"EPYC L3 size should be {expected}, got {cfg['l3_size']}"
        )

    def test_load_all_count(self):
        from config_loader import load_all_configs
        configs = load_all_configs("/app/configs")
        assert len(configs) == 3, f"Should load 3 configs, got {len(configs)}"
        assert "Skylake" in configs
        assert "EPYC" in configs
        assert "A64FX" in configs


# ============================================================
# Stencil FLOP / byte counting
# ============================================================


class TestStencil:
    """Verify stencil counting handles interior points and write-allocate."""

    def test_7pt_flops_interior(self):
        """7pt flops should count interior points only: (nx-2)*(ny-2)*(nz-2)*6."""
        from stencil import jacobi_7pt_flops
        result = jacobi_7pt_flops(100, 100, 100)
        expected = 98 * 98 * 98 * 6  # 5647152
        assert result == expected, f"Expected {expected}, got {result}"

    def test_7pt_flops_small(self):
        """7pt on 10^3: interior 8^3 = 512 points, 6 FLOPs each."""
        from stencil import jacobi_7pt_flops
        result = jacobi_7pt_flops(10, 10, 10)
        expected = 8 * 8 * 8 * 6  # 3072
        assert result == expected, f"Expected {expected}, got {result}"

    def test_7pt_bytes_no_write_allocate(self):
        """Without write-allocate: (7 reads + 1 write) * 8 = 64 bytes/point."""
        from stencil import jacobi_7pt_bytes
        result = jacobi_7pt_bytes(10, 10, 10, elem_bytes=8, write_allocate=False)
        expected = 512 * 64  # 32768
        assert result == expected, f"Expected {expected}, got {result}"

    def test_7pt_bytes_with_write_allocate(self):
        """With write-allocate: (7 reads + 1 write + 1 RFO) * 8 = 72 bytes/point."""
        from stencil import jacobi_7pt_bytes
        result = jacobi_7pt_bytes(10, 10, 10, elem_bytes=8, write_allocate=True)
        expected = 512 * 72  # 36864
        assert result == expected, f"Expected {expected}, got {result}"

    def test_27pt_flops(self):
        """27pt stencil FLOPs on 10^3 grid: 512 interior * 27."""
        from stencil import jacobi_27pt_flops
        result = jacobi_27pt_flops(10, 10, 10)
        expected = 512 * 27  # 13824
        assert result == expected, f"Expected {expected}, got {result}"

    def test_27pt_bytes_no_write_allocate(self):
        """27pt without write-allocate: (27+1)*8 = 224 bytes/point."""
        from stencil import jacobi_27pt_bytes
        result = jacobi_27pt_bytes(10, 10, 10, elem_bytes=8, write_allocate=False)
        expected = 512 * 224  # 114688
        assert result == expected, f"Expected {expected}, got {result}"

    def test_27pt_bytes_with_write_allocate(self):
        """27pt with write-allocate: (27+1+1)*8 = 232 bytes/point."""
        from stencil import jacobi_27pt_bytes
        result = jacobi_27pt_bytes(10, 10, 10, elem_bytes=8, write_allocate=True)
        expected = 512 * 232  # 118784
        assert result == expected, f"Expected {expected}, got {result}"

    def test_oi_7pt_no_wa(self):
        """OI for 7pt without write-allocate: 6/64 = 0.09375."""
        from stencil import jacobi_7pt_flops, jacobi_7pt_bytes, operational_intensity
        f = jacobi_7pt_flops(100, 100, 100)
        b = jacobi_7pt_bytes(100, 100, 100, write_allocate=False)
        oi = operational_intensity(f, b)
        assert abs(oi - 6.0 / 64.0) < 1e-10, f"Expected 0.09375, got {oi}"

    def test_oi_7pt_with_wa(self):
        """OI for 7pt with write-allocate: 6/72 = 1/12."""
        from stencil import jacobi_7pt_flops, jacobi_7pt_bytes, operational_intensity
        f = jacobi_7pt_flops(100, 100, 100)
        b = jacobi_7pt_bytes(100, 100, 100, write_allocate=True)
        oi = operational_intensity(f, b)
        assert abs(oi - 1.0 / 12.0) < 1e-10, f"Expected 1/12, got {oi}"


# ============================================================
# Roofline model
# ============================================================


class TestRoofline:
    """Verify roofline model correctness and cache-aware bandwidth selection."""

    def test_attainable_memory_bound(self):
        """Low OI: predicted = bandwidth * OI (memory-bound)."""
        from roofline import attainable_performance
        result = attainable_performance(0.1, 1000e9, 200e9)
        expected = 200e9 * 0.1  # 20e9
        assert abs(result - expected) < 1e3, f"Expected {expected}, got {result}"

    def test_attainable_compute_bound(self):
        """High OI: predicted = peak_flops (compute-bound)."""
        from roofline import attainable_performance
        result = attainable_performance(100.0, 1000e9, 200e9)
        expected = 1000e9
        assert abs(result - expected) < 1e3, f"Expected {expected}, got {result}"

    def test_at_ridge_point(self):
        """At ridge point, both ceilings give the same performance."""
        from roofline import attainable_performance, ridge_point
        peak, bw = 1000e9, 200e9
        rp = ridge_point(peak, bw)
        result = attainable_performance(rp, peak, bw)
        assert abs(result - peak) < 1e3

    def test_ridge_point_value(self):
        """Ridge point = peak/bandwidth."""
        from roofline import ridge_point
        rp = ridge_point(1000e9, 200e9)
        assert abs(rp - 5.0) < 1e-10

    def test_working_set_2_arrays(self):
        """Working set for Jacobi stencil must account for 2 arrays."""
        from roofline import working_set_bytes
        ws = working_set_bytes(50, 50, 50, 8)
        expected = 2 * 50**3 * 8  # 2000000
        assert ws == expected, f"Expected {expected} (2 arrays), got {ws}"

    def test_effective_bw_skylake_l2(self):
        """Small grid fits in L2 -> use L2 bandwidth."""
        from roofline import effective_bandwidth
        # 2*10^3*8 = 16000 < L2=1048576
        bw = effective_bandwidth(10, 10, 10, SKYLAKE_CFG)
        assert bw == SKYLAKE_CFG["l2_bandwidth"]

    def test_effective_bw_skylake_l3(self):
        """Medium grid fits in L3 but not L2 -> use L3 bandwidth."""
        from roofline import effective_bandwidth
        # 2*50^3*8 = 2000000 > L2=1048576, < L3=34603008
        bw = effective_bandwidth(50, 50, 50, SKYLAKE_CFG)
        assert bw == SKYLAKE_CFG["l3_bandwidth"]

    def test_effective_bw_skylake_dram(self):
        """Large grid exceeds L3 -> use DRAM bandwidth."""
        from roofline import effective_bandwidth
        # 2*200^3*8 = 128000000 > L3=34603008
        bw = effective_bandwidth(200, 200, 200, SKYLAKE_CFG)
        assert bw == SKYLAKE_CFG["dram_bandwidth"]

    def test_effective_bw_a64fx_dram(self):
        """A64FX: large grid, no L3 -> falls through to DRAM."""
        from roofline import effective_bandwidth
        # 2*100^3*8 = 16000000 > L2=8388608, no L3
        bw = effective_bandwidth(100, 100, 100, A64FX_CFG)
        assert bw == A64FX_CFG["dram_bandwidth"], (
            f"Expected DRAM BW {A64FX_CFG['dram_bandwidth']}, got {bw}"
        )

    def test_effective_bw_a64fx_l2(self):
        """A64FX: small grid fits in L2."""
        from roofline import effective_bandwidth
        # 2*50^3*8 = 2000000 < L2=8388608
        bw = effective_bandwidth(50, 50, 50, A64FX_CFG)
        assert bw == A64FX_CFG["l2_bandwidth"]


# ============================================================
# Scaling laws
# ============================================================


class TestScaling:
    """Verify Amdahl's and Gustafson's scaling laws and communication model."""

    def test_amdahl_typical(self):
        """S(16, f=0.95) = 1/(0.05 + 0.95/16)."""
        from scaling import amdahl_speedup
        result = amdahl_speedup(16, 0.95)
        expected = 1.0 / (0.05 + 0.95 / 16)
        assert abs(result - expected) < 1e-8, f"Expected {expected}, got {result}"

    def test_amdahl_perfect_parallel(self):
        """Fully parallel (f=1): speedup = p."""
        from scaling import amdahl_speedup
        result = amdahl_speedup(16, 1.0)
        assert abs(result - 16.0) < 1e-10

    def test_amdahl_single_proc(self):
        """Single processor always gives speedup 1."""
        from scaling import amdahl_speedup
        result = amdahl_speedup(1, 0.9)
        assert abs(result - 1.0) < 1e-10

    def test_amdahl_increases_monotonically(self):
        """Speedup must increase with processor count."""
        from scaling import amdahl_speedup
        prev = 1.0
        for p in [2, 4, 8, 16, 32, 64]:
            s = amdahl_speedup(p, 0.9)
            assert s > prev, f"S({p})={s} should be > S(prev)={prev}"
            prev = s

    def test_gustafson_typical(self):
        """S(16, s=0.05) = 16 - 0.05*15 = 15.25."""
        from scaling import gustafson_speedup
        result = gustafson_speedup(16, 0.05)
        expected = 16.0 - 0.05 * 15.0
        assert abs(result - expected) < 1e-10, f"Expected {expected}, got {result}"

    def test_gustafson_no_serial(self):
        """No serial fraction: perfect scaling S=p."""
        from scaling import gustafson_speedup
        result = gustafson_speedup(32, 0.0)
        assert abs(result - 32.0) < 1e-10

    def test_comm_overhead_zero_at_p1(self):
        """No communication with 1 process."""
        from scaling import communication_overhead
        result = communication_overhead(1, 100, 100, 100)
        assert result == 0.0

    def test_comm_overhead_value(self):
        """Verify exact communication overhead for known parameters."""
        from scaling import communication_overhead
        result = communication_overhead(4, 100, 100, 100)
        expected = 0.06  # analytically derived
        assert abs(result - expected) < 1e-10, f"Expected {expected}, got {result}"


# ============================================================
# Performance portability
# ============================================================


class TestPortability:
    """Verify performance portability uses harmonic mean (Pennycook metric)."""

    def test_harmonic_mean(self):
        """Phi must be harmonic mean, not arithmetic mean."""
        from metrics import performance_portability
        effs = [0.1, 0.9, 0.95]
        result = performance_portability(effs)
        expected = 3.0 / (1 / 0.1 + 1 / 0.9 + 1 / 0.95)
        assert abs(result - expected) < 1e-8, (
            f"Expected harmonic mean {expected:.6f}, got {result:.6f}"
        )

    def test_uniform_efficiency(self):
        """All equal efficiencies -> Phi = that efficiency."""
        from metrics import performance_portability
        result = performance_portability([0.8, 0.8, 0.8])
        assert abs(result - 0.8) < 1e-10

    def test_empty(self):
        """No platforms: Phi = 0."""
        from metrics import performance_portability
        assert performance_portability([]) == 0.0

    def test_less_than_arithmetic(self):
        """Harmonic mean < arithmetic mean for unequal positive values."""
        from metrics import performance_portability
        effs = [0.3, 0.7, 0.9]
        phi = performance_portability(effs)
        arith = sum(effs) / len(effs)
        assert phi < arith, f"Phi ({phi}) should be < arithmetic mean ({arith})"

    def test_cross_platform_summary(self):
        """Full summary computes correct efficiencies and Phi."""
        from metrics import cross_platform_summary
        results = [
            {"achieved": 800e9, "peak": 1000e9},
            {"achieved": 450e9, "peak": 500e9},
            {"achieved": 300e9, "peak": 1500e9},
        ]
        summary = cross_platform_summary(results)
        assert abs(summary["efficiencies"][0] - 0.8) < 1e-10
        assert abs(summary["efficiencies"][1] - 0.9) < 1e-10
        assert abs(summary["efficiencies"][2] - 0.2) < 1e-10
        expected_phi = 3.0 / (1 / 0.8 + 1 / 0.9 + 1 / 0.2)
        assert abs(summary["phi"] - expected_phi) < 1e-6


# ============================================================
# Cache-aware tiling
# ============================================================


class TestTiling:
    """Verify tile optimizer produces valid, near-optimal tiles."""

    def test_working_set_formula(self):
        """Working set = num_arrays * (tx+2r)(ty+2r)(tz+2r) * elem_bytes."""
        from tiling import tile_working_set
        ws = tile_working_set(10, 10, 10, elem_bytes=8, stencil_radius=1, num_arrays=2)
        expected = 2 * 12 * 12 * 12 * 8  # 27648
        assert ws == expected, f"Expected {expected}, got {ws}"

    def test_validate_valid_tile(self):
        """Tile that fits in cache and grid bounds is valid."""
        from tiling import validate_tiling
        valid, reason = validate_tiling(
            10, 10, 10, 100, 100, 100, 100000,
            elem_bytes=8, stencil_radius=1, num_arrays=2
        )
        assert valid, f"Should be valid, reason: {reason}"

    def test_validate_too_large(self):
        """Tile whose working set exceeds cache is invalid."""
        from tiling import validate_tiling
        valid, reason = validate_tiling(
            50, 50, 50, 100, 100, 100, 100000,
            elem_bytes=8, stencil_radius=1, num_arrays=2
        )
        assert not valid, "50^3 tile should exceed 100KB cache"

    def test_validate_exceeds_grid(self):
        """Tile larger than grid is invalid."""
        from tiling import validate_tiling
        valid, reason = validate_tiling(
            200, 10, 10, 100, 100, 100, 10000000,
            elem_bytes=8, stencil_radius=1, num_arrays=2
        )
        assert not valid, "tx=200 exceeds nx=100"

    def test_optimal_fits_cache(self):
        """Optimal tile's working set must fit in the target cache."""
        from tiling import optimal_tile_3d, tile_working_set
        cache = SKYLAKE_CFG["l2_size"]  # 1048576
        tile = optimal_tile_3d(100, 100, 100, cache)
        ws = tile_working_set(*tile)
        assert ws <= cache, (
            f"Working set {ws} exceeds L2 cache {cache} for tile {tile}"
        )

    def test_optimal_volume_threshold(self):
        """Optimal tile volume should be within 90% of theoretical max cube."""
        from tiling import optimal_tile_3d
        cache = SKYLAKE_CFG["l2_size"]  # 1048576
        tile = optimal_tile_3d(100, 100, 100, cache)
        vol = tile[0] * tile[1] * tile[2]
        # Theoretical max cube: (t+2)^3 <= 65536 -> t=38, vol=54872
        cube_vol = 38 ** 3  # 54872
        assert vol >= 0.90 * cube_vol, (
            f"Tile volume {vol} is below 90% of cube volume {cube_vol}"
        )

    def test_optimal_bounded_by_grid(self):
        """All tile dimensions must be <= grid dimensions."""
        from tiling import optimal_tile_3d
        tile = optimal_tile_3d(20, 30, 40, 1048576)
        assert tile[0] <= 20, f"tx={tile[0]} exceeds nx=20"
        assert tile[1] <= 30, f"ty={tile[1]} exceeds ny=30"
        assert tile[2] <= 40, f"tz={tile[2]} exceeds nz=40"

    def test_optimal_small_cache(self):
        """Very small cache produces small but valid tiles."""
        from tiling import optimal_tile_3d, tile_working_set
        cache = 1024  # 1 KB
        tile = optimal_tile_3d(100, 100, 100, cache, elem_bytes=8,
                               stencil_radius=1, num_arrays=2)
        ws = tile_working_set(*tile)
        assert ws <= cache, f"Working set {ws} exceeds tiny cache {cache}"
        assert all(d >= 1 for d in tile), f"All tile dims must be >= 1: {tile}"


# ============================================================
# C stencil verification kernel
# ============================================================


def _python_stencil_ref(nx, ny, nz, n_iter):
    """Python reference implementation of the stencil_checksum function.

    Runs n_iter iterations of 7-point Jacobi on an nx*ny*nz grid
    with a 1000.0 point source at center. Returns RMS of final field.
    """
    size = nx * ny * nz
    u = [0.0] * size
    u[(nz // 2) * ny * nx + (ny // 2) * nx + nx // 2] = 1000.0
    for _ in range(n_iter):
        v = [0.0] * size
        for k in range(1, nz - 1):
            for j in range(1, ny - 1):
                for i in range(1, nx - 1):
                    idx = k * ny * nx + j * nx + i
                    v[idx] = (u[idx - 1] + u[idx + 1] +
                              u[idx - nx] + u[idx + nx] +
                              u[idx - nx * ny] + u[idx + nx * ny]) / 6.0
        u = v
    sum_sq = sum(x * x for x in u)
    return math.sqrt(sum_sq / size)


class TestCKernel:
    """Verify the C stencil verification kernel produces correct results."""

    def test_shared_lib_exists(self):
        """The shared library must be built via the Makefile."""
        assert os.path.exists("/app/kernels/stencil_kernel.so"), \
            "kernels/stencil_kernel.so not found — build with 'make' in /app"

    def test_checksum_small_grid(self):
        """C kernel checksum on small grid must match Python reference."""
        import ctypes
        lib = ctypes.CDLL("/app/kernels/stencil_kernel.so")
        lib.stencil_checksum.restype = ctypes.c_double
        lib.stencil_checksum.argtypes = [ctypes.c_int] * 4
        c_val = lib.stencil_checksum(10, 10, 10, 10)
        ref = _python_stencil_ref(10, 10, 10, 10)
        assert abs(c_val - ref) / max(abs(ref), 1e-15) < 1e-8, \
            f"C checksum {c_val} != Python reference {ref}"

    def test_checksum_larger_grid(self):
        """Verify on another grid to catch subtle indexing bugs."""
        import ctypes
        lib = ctypes.CDLL("/app/kernels/stencil_kernel.so")
        lib.stencil_checksum.restype = ctypes.c_double
        lib.stencil_checksum.argtypes = [ctypes.c_int] * 4
        c_val = lib.stencil_checksum(8, 12, 10, 6)
        ref = _python_stencil_ref(8, 12, 10, 6)
        assert abs(c_val - ref) / max(abs(ref), 1e-15) < 1e-8, \
            f"C checksum {c_val} != Python reference {ref}"

    def test_checksum_nonsquare(self):
        """Verify on a non-square grid to catch dimension-ordering bugs."""
        import ctypes
        lib = ctypes.CDLL("/app/kernels/stencil_kernel.so")
        lib.stencil_checksum.restype = ctypes.c_double
        lib.stencil_checksum.argtypes = [ctypes.c_int] * 4
        c_val = lib.stencil_checksum(10, 14, 12, 8)
        ref = _python_stencil_ref(10, 14, 12, 8)
        assert abs(c_val - ref) / max(abs(ref), 1e-15) < 1e-8, \
            f"C checksum {c_val} != Python reference {ref}"


# ============================================================
# Analysis pipeline integration
# ============================================================


class TestPipeline:
    """Verify the full analysis pipeline produces correct results."""

    @classmethod
    def setup_class(cls):
        """Run the analysis pipeline to produce results.json."""
        from analyze import run_analysis
        run_analysis()
        with open("/app/results.json") as f:
            cls.results = json.load(f)

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json")

    def test_three_architectures(self):
        assert len(self.results["architectures"]) == 3

    def test_skylake_peak_flops(self):
        sky = self.results["architectures"]["Skylake"]
        assert abs(sky["peak_flops"] - 1200e9) < 1e3

    def test_skylake_dram_bandwidth(self):
        sky = self.results["architectures"]["Skylake"]
        assert abs(sky["dram_bandwidth"] - 120e9) < 1e3

    def test_skylake_ridge_point(self):
        sky = self.results["architectures"]["Skylake"]
        assert abs(sky["ridge_point"] - 10.0) < 1e-6

    def test_skylake_stencil_flops(self):
        """Skylake uses write-allocate, but FLOPs are architecture-independent."""
        sky = self.results["architectures"]["Skylake"]
        assert sky["stencil_7pt"]["flops"] == 98 * 98 * 98 * 6

    def test_skylake_stencil_bytes_wa(self):
        """Skylake has write-allocate: bytes = interior * (7+1+1)*8."""
        sky = self.results["architectures"]["Skylake"]
        expected_bytes = 98 * 98 * 98 * 72
        assert sky["stencil_7pt"]["bytes"] == expected_bytes, (
            f"Expected {expected_bytes}, got {sky['stencil_7pt']['bytes']}"
        )

    def test_skylake_stencil_prediction(self):
        """Skylake: grid fits L3, OI with WA = 1/12, pred = L3_bw * OI."""
        sky = self.results["architectures"]["Skylake"]
        pred = sky["stencil_7pt"]["predicted_perf"]
        expected = 400e9 / 12.0  # L3 bandwidth * OI(1/12)
        assert abs(pred - expected) / expected < 1e-6, (
            f"Expected {expected}, got {pred}"
        )

    def test_a64fx_stencil_bytes_no_wa(self):
        """A64FX has NO write-allocate: bytes = interior * (7+1)*8."""
        a64 = self.results["architectures"]["A64FX"]
        expected_bytes = 98 * 98 * 98 * 64
        assert a64["stencil_7pt"]["bytes"] == expected_bytes, (
            f"Expected {expected_bytes}, got {a64['stencil_7pt']['bytes']}"
        )

    def test_a64fx_stencil_prediction(self):
        """A64FX: no L3, uses DRAM. OI = 6/64. pred = DRAM_bw * OI."""
        a64 = self.results["architectures"]["A64FX"]
        pred = a64["stencil_7pt"]["predicted_perf"]
        expected = 1024e9 * 6.0 / 64.0  # 96e9
        assert abs(pred - expected) / expected < 1e-6, (
            f"Expected {expected}, got {pred}"
        )

    def test_epyc_stencil_prediction(self):
        """EPYC: grid fits L3, OI with WA = 1/12, pred = L3_bw * OI."""
        epyc = self.results["architectures"]["EPYC"]
        pred = epyc["stencil_7pt"]["predicted_perf"]
        expected = 500e9 / 12.0
        assert abs(pred - expected) / expected < 1e-6

    def test_amdahl_value(self):
        """All architectures should have same Amdahl speedup."""
        sky = self.results["architectures"]["Skylake"]
        expected = 1.0 / (0.05 + 0.95 / 16)
        assert abs(sky["amdahl_16_095"] - expected) < 1e-6

    def test_gustafson_value(self):
        """All architectures should have same Gustafson speedup."""
        sky = self.results["architectures"]["Skylake"]
        expected = 16.0 - 0.05 * 15.0  # 15.25
        assert abs(sky["gustafson_16_005"] - expected) < 1e-10

    def test_portability_phi_is_harmonic(self):
        """Phi must be the harmonic mean of efficiencies."""
        port = self.results["portability"]
        effs = port["efficiencies"]
        phi = port["phi"]
        expected = len(effs) / sum(1.0 / e for e in effs)
        assert abs(phi - expected) < 1e-10, (
            f"Phi {phi} should be harmonic mean {expected}"
        )

    def test_portability_phi_range(self):
        """Phi should be small for memory-bound stencils (low efficiency)."""
        phi = self.results["portability"]["phi"]
        assert 0 < phi < 0.1, f"Phi={phi} outside expected range for stencils"

    def test_optimal_tiles_valid(self):
        """All architectures should have valid L2 tiles."""
        from tiling import tile_working_set
        for name, arch in self.results["architectures"].items():
            tile = arch["optimal_l2_tile"]
            assert len(tile) == 3, f"{name}: tile should be 3 values"
            assert all(d >= 1 for d in tile), f"{name}: tile dims must be >= 1"
            assert all(d <= 100 for d in tile), f"{name}: tile dims must be <= 100"

    def test_verification_exists(self):
        """Pipeline must include C kernel verification checksum."""
        assert "verification" in self.results, \
            "results.json missing 'verification' key"
        v = self.results["verification"]
        assert v["grid"] == [10, 10, 10]
        assert v["iterations"] == 10
        assert v["rms_checksum"] > 0

    def test_verification_checksum_correct(self):
        """Verification checksum must match Python reference."""
        v = self.results["verification"]
        ref = _python_stencil_ref(
            v["grid"][0], v["grid"][1], v["grid"][2], v["iterations"]
        )
        assert abs(v["rms_checksum"] - ref) / max(abs(ref), 1e-15) < 1e-8, (
            f"C checksum {v['rms_checksum']} != Python reference {ref}"
        )
