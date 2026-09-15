
import sys
sys.path.insert(0, "/app")
import pytest

import spmv_bench as sb

# ===== Test Matrix 1: 8x8, 21 nnz, irregular sparsity =====
# NNZ per row: [2, 3, 5, 1, 3, 4, 1, 2]
M1_ROW_PTR = [0, 2, 5, 10, 11, 14, 18, 19, 21]
M1_COL_IDX = [0, 3, 1, 2, 5, 0, 2, 4, 6, 7, 3, 1, 4, 7, 0, 2, 5, 6, 6, 1, 3]
M1_DATA = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
           11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0]
M1_NUM_ROWS = 8
M1_NUM_COLS = 8
M1_NNZ = 21
M1_VEC = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
M1_SPMV = [9.0, 48.0, 210.0, 44.0, 201.0, 291.0, 133.0, 124.0]

# ===== Test Matrix 2: 3x3, 3 nnz, empty row =====
M2_ROW_PTR = [0, 2, 2, 3]
M2_COL_IDX = [0, 2, 1]
M2_DATA = [1.0, 2.0, 3.0]
M2_NUM_ROWS = 3
M2_VEC = [1.0, 2.0, 3.0]
M2_SPMV = [7.0, 0.0, 6.0]

# ===== Test Matrix 3: 4x6, 10 nnz, non-square =====
M3_ROW_PTR = [0, 2, 5, 6, 10]
M3_COL_IDX = [0, 5, 1, 2, 4, 3, 0, 2, 3, 5]
M3_DATA = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
M3_NUM_ROWS = 4
M3_NUM_COLS = 6
M3_NNZ = 10
M3_VEC = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
M3_SPMV = [13.0, 43.0, 24.0, 127.0]

# ===== Test Matrix 4: 4x4 diagonal (uniform NNZ=1) =====
M4_ROW_PTR = [0, 1, 2, 3, 4]
M4_COL_IDX = [0, 1, 2, 3]
M4_DATA = [2.0, 3.0, 5.0, 7.0]
M4_NUM_ROWS = 4
M4_VEC = [1.0, 1.0, 1.0, 1.0]
M4_SPMV = [2.0, 3.0, 5.0, 7.0]

# ===== Circuit matrix (loaded from Matrix Market .mtx) =====
CIRCUIT_ROW_PTR = [0, 2, 4, 6, 7, 8]
CIRCUIT_COL_IDX = [0, 2, 1, 3, 0, 2, 3, 1]
CIRCUIT_DATA = [4.0, -1.0, 5.0, -2.0, -1.0, 6.0, 3.0, -1.0]
CIRCUIT_VEC = [1.0, 2.0, 3.0, 4.0, 5.0]
CIRCUIT_SPMV = [1.0, 2.0, 17.0, 12.0, -2.0]


def _assert_vec_close(actual, expected, tol=1e-6):
    assert len(actual) == len(expected), f"length mismatch: {len(actual)} vs {len(expected)}"
    for i, (a, b) in enumerate(zip(actual, expected)):
        assert abs(a - b) < tol, f"Row {i}: expected {b}, got {a}"


# =====================================================================
# CSR loading and SpMV (baseline — these should work correctly)
# =====================================================================

class TestCSRBaseline:
    def test_load_matrix1(self):
        rp, ci, d, nr, nc, nnz = sb.load_csr_dir("/app/data/matrix1")
        assert rp == M1_ROW_PTR
        assert ci == M1_COL_IDX
        assert nr == 8 and nc == 8 and nnz == 21

    def test_spmv_matrix1(self):
        r = sb.spmv_csr(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_VEC, M1_NUM_ROWS)
        _assert_vec_close(r, M1_SPMV)

    def test_spmv_empty_row(self):
        r = sb.spmv_csr(M2_ROW_PTR, M2_COL_IDX, M2_DATA, M2_VEC, M2_NUM_ROWS)
        _assert_vec_close(r, M2_SPMV)

    def test_spmv_nonsquare(self):
        r = sb.spmv_csr(M3_ROW_PTR, M3_COL_IDX, M3_DATA, M3_VEC, M3_NUM_ROWS)
        _assert_vec_close(r, M3_SPMV)


# =====================================================================
# ELLPACK pipeline (no bugs — should pass)
# =====================================================================

class TestELLPipeline:
    def test_ell_spmv_matrix1(self):
        csr_r = sb.spmv_csr(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_VEC, M1_NUM_ROWS)
        eci, ed, mx = sb.csr_to_ell(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        ell_r = sb.spmv_ell(eci, ed, M1_VEC, M1_NUM_ROWS, mx)
        _assert_vec_close(ell_r, csr_r)

    def test_ell_max_nnz(self):
        _, _, mx = sb.csr_to_ell(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        assert mx == 5

    def test_ell_padding(self):
        eci, ed, mx = sb.csr_to_ell(M2_ROW_PTR, M2_COL_IDX, M2_DATA, M2_NUM_ROWS)
        assert eci[1] == [-1, -1]
        assert ed[1] == [0.0, 0.0]

    def test_ell_spmv_nonsquare(self):
        csr_r = sb.spmv_csr(M3_ROW_PTR, M3_COL_IDX, M3_DATA, M3_VEC, M3_NUM_ROWS)
        eci, ed, mx = sb.csr_to_ell(M3_ROW_PTR, M3_COL_IDX, M3_DATA, M3_NUM_ROWS)
        ell_r = sb.spmv_ell(eci, ed, M3_VEC, M3_NUM_ROWS, mx)
        _assert_vec_close(ell_r, csr_r)


# =====================================================================
# JDS conversion
# =====================================================================

class TestJDSConversion:
    def test_uniform_nnz(self):
        """Diagonal matrix (all rows NNZ=1) — should work regardless of sort."""
        rp, rn, cs, ci, d = sb.csr_to_jds(M4_ROW_PTR, M4_COL_IDX, M4_DATA, M4_NUM_ROWS)
        assert rp == [0, 1, 2, 3]
        assert rn == [1, 1, 1, 1]
        assert cs == [0]
        assert ci == [0, 1, 2, 3]
        assert d == [2.0, 3.0, 5.0, 7.0]

    def test_descending_sort_order(self):
        """Rows must be sorted by descending NNZ count."""
        rp, rn, cs, ci, d = sb.csr_to_jds(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        assert rp[0] == 2, f"Row with max NNZ (row 2, NNZ=5) must be first, got row {rp[0]}"
        for i in range(len(rn) - 1):
            assert rn[i] >= rn[i + 1], f"NNZ not descending at {i}: {rn[i]} < {rn[i + 1]}"

    def test_total_nnz_preserved(self):
        """JDS must contain exactly the same number of non-zeros as CSR."""
        rp, rn, cs, ci, d = sb.csr_to_jds(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        assert len(ci) == M1_NNZ
        assert len(d) == M1_NNZ

    def test_empty_row_handling(self):
        """Matrix with empty rows must convert correctly."""
        rp, rn, cs, ci, d = sb.csr_to_jds(M2_ROW_PTR, M2_COL_IDX, M2_DATA, M2_NUM_ROWS)
        assert len(ci) == 3
        assert rp[0] == 0, "Row 0 (NNZ=2) must be first in descending sort"

    def test_nonsquare(self):
        """Non-square matrix JDS conversion."""
        rp, rn, cs, ci, d = sb.csr_to_jds(M3_ROW_PTR, M3_COL_IDX, M3_DATA, M3_NUM_ROWS)
        assert rp[0] == 3, "Row 3 (NNZ=4) must be first"
        assert rn == [4, 3, 2, 1]


# =====================================================================
# JDS SpMV
# =====================================================================

class TestJDSSpMV:
    def test_matches_csr_matrix1(self):
        """JDS SpMV must produce identical results to CSR SpMV."""
        csr_r = sb.spmv_csr(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_VEC, M1_NUM_ROWS)
        rp, rn, cs, ci, d = sb.csr_to_jds(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        jds_r = sb.spmv_jds(rp, rn, cs, ci, d, M1_VEC, M1_NUM_ROWS)
        _assert_vec_close(jds_r, csr_r)

    def test_matches_csr_nonsquare(self):
        csr_r = sb.spmv_csr(M3_ROW_PTR, M3_COL_IDX, M3_DATA, M3_VEC, M3_NUM_ROWS)
        rp, rn, cs, ci, d = sb.csr_to_jds(M3_ROW_PTR, M3_COL_IDX, M3_DATA, M3_NUM_ROWS)
        jds_r = sb.spmv_jds(rp, rn, cs, ci, d, M3_VEC, M3_NUM_ROWS)
        _assert_vec_close(jds_r, csr_r)

    def test_matches_csr_diagonal(self):
        csr_r = sb.spmv_csr(M4_ROW_PTR, M4_COL_IDX, M4_DATA, M4_VEC, M4_NUM_ROWS)
        rp, rn, cs, ci, d = sb.csr_to_jds(M4_ROW_PTR, M4_COL_IDX, M4_DATA, M4_NUM_ROWS)
        jds_r = sb.spmv_jds(rp, rn, cs, ci, d, M4_VEC, M4_NUM_ROWS)
        _assert_vec_close(jds_r, csr_r)

    def test_all_formats_agree(self):
        """CSR, JDS, and ELL must all produce identical SpMV results."""
        csr_r = sb.spmv_csr(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_VEC, M1_NUM_ROWS)

        rp, rn, cs, ci, d = sb.csr_to_jds(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        jds_r = sb.spmv_jds(rp, rn, cs, ci, d, M1_VEC, M1_NUM_ROWS)

        eci, ed, mx = sb.csr_to_ell(M1_ROW_PTR, M1_COL_IDX, M1_DATA, M1_NUM_ROWS)
        ell_r = sb.spmv_ell(eci, ed, M1_VEC, M1_NUM_ROWS, mx)

        _assert_vec_close(jds_r, csr_r)
        _assert_vec_close(ell_r, csr_r)


# =====================================================================
# Memory traffic modeling
# =====================================================================

class TestMemoryTraffic:
    def test_csr_exact(self):
        # (num_rows+1 + nnz + nnz + num_cols + num_rows) * 4
        expected = (9 + 21 + 21 + 8 + 8) * 4  # 268
        assert sb.memory_traffic_bytes("csr", 8, 8, 21, 5) == expected

    def test_jds_exact(self):
        # (3*num_rows + max_nnz + 2*nnz + num_cols) * 4
        expected = (24 + 5 + 42 + 8) * 4  # 316
        assert sb.memory_traffic_bytes("jds", 8, 8, 21, 5) == expected

    def test_ell_exact(self):
        # ELLPACK uses padded arrays: num_rows * max_nnz_per_row for both col_idx and data
        expected = (2 * 8 * 5 + 8 + 8) * 4  # 384
        assert sb.memory_traffic_bytes("ell", 8, 8, 21, 5) == expected

    def test_ell_exceeds_csr_for_irregular(self):
        """ELLPACK padding overhead must make traffic exceed CSR for irregular sparsity."""
        csr_b = sb.memory_traffic_bytes("csr", 8, 8, 21, 5)
        ell_b = sb.memory_traffic_bytes("ell", 8, 8, 21, 5)
        assert ell_b > csr_b, f"ELL ({ell_b}B) must exceed CSR ({csr_b}B)"

    def test_ell_nonsquare(self):
        expected = (2 * 4 * 4 + 6 + 4) * 4  # 168
        assert sb.memory_traffic_bytes("ell", 4, 6, 10, 4) == expected

    def test_csr_nonsquare(self):
        expected = (5 + 10 + 10 + 6 + 4) * 4  # 140
        assert sb.memory_traffic_bytes("csr", 4, 6, 10, 4) == expected


# =====================================================================
# Warp scheduling simulation
# =====================================================================

class TestWarpSimulation:
    def test_single_warp(self):
        r = sb.simulate_warp_workload([2, 3, 5, 1], 4)
        assert r["warp_steps"] == 5
        assert r["total_slots"] == 20
        assert r["active_slots"] == 11

    def test_two_warps(self):
        r = sb.simulate_warp_workload([2, 3, 5, 1, 3, 4, 1, 2], 4)
        assert r["warp_steps"] == 9
        assert r["total_slots"] == 36
        assert r["active_slots"] == 21
        assert abs(r["warp_efficiency"] - 21.0 / 36.0) < 1e-9

    def test_efficiency_bounded_by_one(self):
        """Physical constraint: warp efficiency cannot exceed 1.0 under SIMT."""
        r = sb.simulate_warp_workload([2, 3, 5, 1], 4)
        assert r["warp_efficiency"] <= 1.0 + 1e-9, (
            f"Efficiency {r['warp_efficiency']:.4f} > 1.0 violates SIMT model"
        )

    def test_uniform_perfect_efficiency(self):
        r = sb.simulate_warp_workload([3, 3, 3, 3], 4)
        assert abs(r["warp_efficiency"] - 1.0) < 1e-9

    def test_partial_last_warp(self):
        r = sb.simulate_warp_workload([3, 3, 3, 3, 2], 4)
        assert r["warp_steps"] == 5
        assert r["total_slots"] == 20
        assert r["active_slots"] == 14

    def test_sorting_improves_efficiency(self):
        """Sorting rows by descending NNZ should not worsen warp efficiency."""
        work = [2, 3, 5, 1, 3, 4, 1, 2]
        sorted_work = sorted(work, reverse=True)
        orig = sb.simulate_warp_workload(work, 4)
        reordered = sb.simulate_warp_workload(sorted_work, 4)
        assert reordered["warp_efficiency"] >= orig["warp_efficiency"] - 1e-9

    def test_warp32(self):
        """Realistic GPU warp size."""
        row_work = [5, 4, 3, 3, 2, 2, 1, 1]
        r = sb.simulate_warp_workload(row_work, 32)
        assert r["warp_steps"] == 5
        assert r["total_slots"] == 160
        assert r["active_slots"] == 21


# =====================================================================
# Matrix Market loading
# =====================================================================

class TestMTXLoading:
    def test_load_dimensions(self):
        rp, ci, d, nr, nc, nnz = sb.load_mtx("/app/matrices/circuit.mtx")
        assert nr == 5
        assert nc == 5
        assert nnz == 8

    def test_load_csr_structure(self):
        rp, ci, d, nr, nc, nnz = sb.load_mtx("/app/matrices/circuit.mtx")
        assert rp == CIRCUIT_ROW_PTR
        assert ci == CIRCUIT_COL_IDX

    def test_load_data_values(self):
        rp, ci, d, nr, nc, nnz = sb.load_mtx("/app/matrices/circuit.mtx")
        _assert_vec_close(d, CIRCUIT_DATA)

    def test_spmv_from_mtx(self):
        rp, ci, d, nr, nc, nnz = sb.load_mtx("/app/matrices/circuit.mtx")
        result = sb.spmv_csr(rp, ci, d, CIRCUIT_VEC, nr)
        _assert_vec_close(result, CIRCUIT_SPMV)
