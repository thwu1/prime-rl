"""Tests for GPU Kernel Fleet Performance Audit report.

Verifies that /app/audit_report.json contains correct occupancy calculations,
shared memory carve-out selections, memory coalescing analysis, bank conflict
degrees, performance diagnoses, and kernel fusion analyses across two GPU
architectures.
"""

import json
import os

import pytest

REPORT_PATH = "/app/audit_report.json"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "audit_report.json must be a JSON object"
    return data


class TestReportStructure:
    def test_top_level_sections(self, report):
        assert "kernel_analyses" in report, "Missing 'kernel_analyses'"
        assert "fusion_analyses" in report, "Missing 'fusion_analyses'"

    def test_all_kernels_present(self, report):
        expected = {"gemm_tile", "reduce_atomic", "transpose_opt", "conv_smem", "fft_radix"}
        actual = set(report["kernel_analyses"].keys())
        missing = expected - actual
        assert not missing, f"Missing kernels: {missing}"

    def test_all_archs_per_kernel(self, report):
        for kernel in report["kernel_analyses"]:
            for arch in ["sm80", "sm90"]:
                assert arch in report["kernel_analyses"][kernel], (
                    f"{kernel} missing architecture {arch}"
                )

    def test_all_fusion_pairs(self, report):
        expected = {
            "gemm_tile+transpose_opt",
            "transpose_opt+fft_radix",
            "conv_smem+fft_radix",
            "fft_radix+reduce_atomic",
            "conv_smem+reduce_atomic",
        }
        actual = set(report["fusion_analyses"].keys())
        missing = expected - actual
        assert not missing, f"Missing fusion pairs: {missing}"

    def test_reduce_atomic_no_shared_memory(self, report):
        for arch in ["sm80", "sm90"]:
            entry = report["kernel_analyses"]["reduce_atomic"][arch]
            assert "shared_memory" not in entry, (
                f"reduce_atomic/{arch} should not have shared_memory section"
            )


class TestOccupancy:
    @pytest.mark.parametrize(
        "kernel,arch,occ,blocks,warps,limiter,carveout",
        [
            ("gemm_tile", "sm80", 50.0, 4, 32, "shared_memory", 167936),
            ("gemm_tile", "sm90", 75.0, 6, 48, "registers", 233472),
            ("reduce_atomic", "sm80", 50.0, 2, 32, "registers", 8192),
            ("reduce_atomic", "sm90", 50.0, 2, 32, "registers", 8192),
            ("transpose_opt", "sm80", 100.0, 8, 64, "block_size", 65536),
            ("transpose_opt", "sm90", 100.0, 8, 64, "block_size", 65536),
            ("conv_smem", "sm80", 18.75, 3, 12, "shared_memory", 167936),
            ("conv_smem", "sm90", 25.0, 4, 16, "shared_memory", 233472),
            ("fft_radix", "sm80", 50.0, 4, 32, "registers", 65536),
            ("fft_radix", "sm90", 50.0, 4, 32, "registers", 65536),
        ],
    )
    def test_occupancy_values(self, report, kernel, arch, occ, blocks, warps, limiter, carveout):
        ka = report["kernel_analyses"][kernel][arch]
        assert abs(ka["occupancy_pct"] - occ) < 0.01, (
            f"{kernel}/{arch}: occupancy_pct={ka['occupancy_pct']}, expected={occ}"
        )
        assert ka["active_blocks_per_sm"] == blocks, (
            f"{kernel}/{arch}: active_blocks={ka['active_blocks_per_sm']}, expected={blocks}"
        )
        assert ka["active_warps_per_sm"] == warps, (
            f"{kernel}/{arch}: active_warps={ka['active_warps_per_sm']}, expected={warps}"
        )
        assert ka["occupancy_limiter"] == limiter, (
            f"{kernel}/{arch}: limiter={ka['occupancy_limiter']}, expected={limiter}"
        )
        assert ka["optimal_smem_carveout_bytes"] == carveout, (
            f"{kernel}/{arch}: carveout={ka['optimal_smem_carveout_bytes']}, expected={carveout}"
        )


class TestGlobalMemoryCoalescing:
    @pytest.mark.parametrize(
        "kernel,access,sectors,eff",
        [
            ("gemm_tile", "tile_load_A", 4, 100.0),
            ("gemm_tile", "tile_load_B", 32, 12.5),
            ("gemm_tile", "result_store", 4, 100.0),
            ("reduce_atomic", "input_read", 4, 100.0),
            ("transpose_opt", "coalesced_read", 4, 100.0),
            ("transpose_opt", "strided_write", 32, 12.5),
            ("conv_smem", "input_load", 4, 100.0),
            ("conv_smem", "filter_load", 4, 100.0),
            ("conv_smem", "output_store", 4, 100.0),
            ("fft_radix", "butterfly_read", 8, 100.0),
            ("fft_radix", "butterfly_write", 8, 100.0),
            ("fft_radix", "twiddle_load", 32, 25.0),
        ],
    )
    def test_coalescing_sm80(self, report, kernel, access, sectors, eff):
        gm = report["kernel_analyses"][kernel]["sm80"]["global_memory"][access]
        assert gm["sectors_per_request"] == sectors, (
            f"{kernel}/{access}: sectors={gm['sectors_per_request']}, expected={sectors}"
        )
        assert abs(gm["coalescing_efficiency_pct"] - eff) < 0.01, (
            f"{kernel}/{access}: efficiency={gm['coalescing_efficiency_pct']}, expected={eff}"
        )

    def test_coalescing_sm90_spot_check(self, report):
        gm = report["kernel_analyses"]["fft_radix"]["sm90"]["global_memory"]
        assert gm["twiddle_load"]["sectors_per_request"] == 32
        assert abs(gm["twiddle_load"]["coalescing_efficiency_pct"] - 25.0) < 0.01
        gm2 = report["kernel_analyses"]["gemm_tile"]["sm90"]["global_memory"]
        assert gm2["tile_load_B"]["sectors_per_request"] == 32
        assert abs(gm2["tile_load_B"]["coalescing_efficiency_pct"] - 12.5) < 0.01


class TestBankConflicts:
    @pytest.mark.parametrize(
        "kernel,access,degree",
        [
            ("gemm_tile", "smem_row", 1),
            ("gemm_tile", "smem_col", 32),
            ("transpose_opt", "unpadded_col", 32),
            ("transpose_opt", "padded_col", 1),
            ("transpose_opt", "diagonal", 1),
            ("conv_smem", "smem_linear", 1),
            ("conv_smem", "smem_stride4", 4),
            ("fft_radix", "butterfly_smem", 2),
            ("fft_radix", "butterfly_smem_rev", 16),
        ],
    )
    def test_bank_conflicts_sm80(self, report, kernel, access, degree):
        sm = report["kernel_analyses"][kernel]["sm80"]["shared_memory"][access]
        assert sm["bank_conflict_degree"] == degree, (
            f"{kernel}/{access}: degree={sm['bank_conflict_degree']}, expected={degree}"
        )

    def test_bank_conflicts_sm90_spot_check(self, report):
        sm = report["kernel_analyses"]["gemm_tile"]["sm90"]["shared_memory"]
        assert sm["smem_col"]["bank_conflict_degree"] == 32
        assert sm["smem_row"]["bank_conflict_degree"] == 1
        sm2 = report["kernel_analyses"]["fft_radix"]["sm90"]["shared_memory"]
        assert sm2["butterfly_smem_rev"]["bank_conflict_degree"] == 16


class TestDiagnosis:
    @pytest.mark.parametrize(
        "kernel,arch,has_disc,meas_occ,theo_occ,meas_co,rec_co",
        [
            ("gemm_tile", "sm80", True, 12.5, 50.0, 65536, 167936),
            ("gemm_tile", "sm90", True, 37.5, 75.0, 102400, 233472),
            ("reduce_atomic", "sm80", False, 50.0, 50.0, 8192, 8192),
            ("reduce_atomic", "sm90", False, 50.0, 50.0, 8192, 8192),
            ("transpose_opt", "sm80", False, 100.0, 100.0, 65536, 65536),
            ("transpose_opt", "sm90", False, 100.0, 100.0, 65536, 65536),
            ("conv_smem", "sm80", True, 12.5, 18.75, 102400, 167936),
            ("conv_smem", "sm90", True, 18.75, 25.0, 167936, 233472),
            ("fft_radix", "sm80", False, 50.0, 50.0, 65536, 65536),
            ("fft_radix", "sm90", False, 50.0, 50.0, 65536, 65536),
        ],
    )
    def test_diagnosis(self, report, kernel, arch, has_disc, meas_occ, theo_occ, meas_co, rec_co):
        diag = report["kernel_analyses"][kernel][arch]["diagnosis"]
        assert diag["has_discrepancy"] == has_disc, (
            f"{kernel}/{arch}: has_discrepancy={diag['has_discrepancy']}, expected={has_disc}"
        )
        assert abs(diag["measured_occupancy_pct"] - meas_occ) < 0.01, (
            f"{kernel}/{arch}: measured_occ={diag['measured_occupancy_pct']}, expected={meas_occ}"
        )
        assert abs(diag["theoretical_occupancy_pct"] - theo_occ) < 0.01, (
            f"{kernel}/{arch}: theoretical_occ={diag['theoretical_occupancy_pct']}, expected={theo_occ}"
        )
        assert diag["measured_carveout_bytes"] == meas_co, (
            f"{kernel}/{arch}: measured_carveout={diag['measured_carveout_bytes']}, expected={meas_co}"
        )
        assert diag["recommended_carveout_bytes"] == rec_co, (
            f"{kernel}/{arch}: recommended_carveout={diag['recommended_carveout_bytes']}, expected={rec_co}"
        )


class TestFusionParams:
    @pytest.mark.parametrize(
        "pair,regs,smem,threads,feasible",
        [
            ("gemm_tile+transpose_opt", 64, 36864, 256, True),
            ("transpose_opt+fft_radix", 88, 12288, 256, True),
            ("conv_smem+fft_radix", 160, 57344, 256, True),
            ("fft_radix+reduce_atomic", 112, 8192, 512, True),
            ("conv_smem+reduce_atomic", 144, 49152, 512, False),
        ],
    )
    def test_fusion_parameters(self, report, pair, regs, smem, threads, feasible):
        fa = report["fusion_analyses"][pair]
        assert fa["fused_registers_per_thread"] == regs, (
            f"{pair}: fused_regs={fa['fused_registers_per_thread']}, expected={regs}"
        )
        assert fa["fused_smem_bytes"] == smem, (
            f"{pair}: fused_smem={fa['fused_smem_bytes']}, expected={smem}"
        )
        assert fa["fused_threads_per_block"] == threads, (
            f"{pair}: fused_threads={fa['fused_threads_per_block']}, expected={threads}"
        )
        assert fa["feasible"] == feasible, (
            f"{pair}: feasible={fa['feasible']}, expected={feasible}"
        )


class TestFusionOccupancy:
    @pytest.mark.parametrize(
        "pair,arch,occ,blocks,warps,carveout",
        [
            ("gemm_tile+transpose_opt", "sm80", 50.0, 4, 32, 167936),
            ("gemm_tile+transpose_opt", "sm90", 50.0, 4, 32, 167936),
            ("transpose_opt+fft_radix", "sm80", 25.0, 2, 16, 32768),
            ("transpose_opt+fft_radix", "sm90", 25.0, 2, 16, 32768),
            ("conv_smem+fft_radix", "sm80", 12.5, 1, 8, 65536),
            ("conv_smem+fft_radix", "sm90", 12.5, 1, 8, 65536),
            ("fft_radix+reduce_atomic", "sm80", 25.0, 1, 16, 16384),
            ("fft_radix+reduce_atomic", "sm90", 25.0, 1, 16, 16384),
        ],
    )
    def test_fusion_occupancy(self, report, pair, arch, occ, blocks, warps, carveout):
        fa = report["fusion_analyses"][pair]["architectures"][arch]
        assert abs(fa["occupancy_pct"] - occ) < 0.01, (
            f"{pair}/{arch}: occ={fa['occupancy_pct']}, expected={occ}"
        )
        assert fa["active_blocks_per_sm"] == blocks, (
            f"{pair}/{arch}: blocks={fa['active_blocks_per_sm']}, expected={blocks}"
        )
        assert fa["active_warps_per_sm"] == warps, (
            f"{pair}/{arch}: warps={fa['active_warps_per_sm']}, expected={warps}"
        )
        assert fa["optimal_smem_carveout_bytes"] == carveout, (
            f"{pair}/{arch}: carveout={fa['optimal_smem_carveout_bytes']}, expected={carveout}"
        )

    def test_infeasible_fusion_zeros(self, report):
        fa = report["fusion_analyses"]["conv_smem+reduce_atomic"]
        assert fa["feasible"] is False
        for arch in ["sm80", "sm90"]:
            arch_data = fa["architectures"][arch]
            assert arch_data["occupancy_pct"] == 0.0, (
                f"conv_smem+reduce_atomic/{arch}: infeasible should have 0.0 occupancy"
            )
            assert arch_data["active_blocks_per_sm"] == 0, (
                f"conv_smem+reduce_atomic/{arch}: infeasible should have 0 blocks"
            )
            assert arch_data["active_warps_per_sm"] == 0, (
                f"conv_smem+reduce_atomic/{arch}: infeasible should have 0 warps"
            )
            assert arch_data["optimal_smem_carveout_bytes"] == 0, (
                f"conv_smem+reduce_atomic/{arch}: infeasible should have 0 carveout"
            )
