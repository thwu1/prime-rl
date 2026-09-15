
import pytest
import subprocess
import json
import os
import numpy as np
from scipy import sparse


def write_csr_files(data_dir, row_ptr, col_idx, values, vec):
    """Write CSR matrix and vector in raw format."""
    os.makedirs(data_dir, exist_ok=True)

    with open(os.path.join(data_dir, "row.raw"), "w") as f:
        f.write(f"{len(row_ptr)}\n")
        for r in row_ptr:
            f.write(f"{r}\n")

    with open(os.path.join(data_dir, "col.raw"), "w") as f:
        f.write(f"{len(col_idx)}\n")
        for c in col_idx:
            f.write(f"{c}\n")

    with open(os.path.join(data_dir, "data.raw"), "w") as f:
        f.write(f"{len(values)}\n")
        for v in values:
            f.write(f"{v:.6e}\n")

    with open(os.path.join(data_dir, "vec.raw"), "w") as f:
        f.write(f"{len(vec)}\n")
        for v in vec:
            f.write(f"{v:.6e}\n")


def compute_bandwidth(row_ptr, col_idx, dim):
    """Compute matrix bandwidth: max |i - j| over non-zeros."""
    bw = 0
    for i in range(dim):
        for j in range(row_ptr[i], row_ptr[i + 1]):
            bw = max(bw, abs(i - col_idx[j]))
    return bw


def compute_profile_ref(row_ptr, col_idx, dim):
    """Reference profile computation: sum of per-row envelopes."""
    profile = 0
    for i in range(dim):
        if row_ptr[i] < row_ptr[i + 1]:
            min_col = min(col_idx[j] for j in range(row_ptr[i], row_ptr[i + 1]))
            envelope = i - min_col
            if envelope > 0:
                profile += envelope
    return profile


def run_pipeline(data_dir, output_path):
    """Run the sparse_pipeline.py tool and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/sparse_pipeline.py", data_dir, output_path],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"Pipeline exited with code {result.returncode}.\n"
        f"stdout: {result.stdout[-2000:]}\n"
        f"stderr: {result.stderr[-2000:]}"
    )
    assert os.path.exists(output_path), f"Output file not created: {output_path}"
    with open(output_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test 1: Small known 5x5 tridiagonal matrix
# ---------------------------------------------------------------------------
class TestSmallTridiagonal:
    """5x5 tridiagonal matrix: A = tridiag(-1, 2, -1), vec = [1..5]."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.dim = 5
        row_ptr = [0, 2, 5, 8, 11, 13]
        col_idx = [0, 1, 0, 1, 2, 1, 2, 3, 2, 3, 4, 3, 4]
        values = [2.0, -1.0, -1.0, 2.0, -1.0, -1.0, 2.0, -1.0,
                  -1.0, 2.0, -1.0, -1.0, 2.0]
        vec = [1.0, 2.0, 3.0, 4.0, 5.0]

        self.row_ptr = row_ptr
        self.col_idx = col_idx

        data_dir = str(tmp_path / "small")
        output_path = str(tmp_path / "small_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec)

        self.report = run_pipeline(data_dir, output_path)

        A = sparse.csr_matrix((values, col_idx, row_ptr), shape=(5, 5))
        self.ref_result = (A @ np.array(vec)).tolist()

    def test_dimension(self):
        assert self.report["dimension"] == 5

    def test_nnz(self):
        assert self.report["nnz"] == 13

    def test_csr_spmv_correct(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["jds_spmv"], self.ref_result, atol=1e-5)

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(self.report["ell_spmv"], self.ref_result, atol=1e-5)

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["rcm_jds_spmv"], self.ref_result, atol=1e-5)

    def test_jds_row_perm_is_valid_permutation(self):
        perm = self.report["jds_row_perm"]
        assert sorted(perm) == list(range(5))

    def test_jds_row_perm_sorted_by_nnz_desc(self):
        perm = self.report["jds_row_perm"]
        nnz_per_row = [self.row_ptr[i + 1] - self.row_ptr[i] for i in range(5)]
        sorted_nnz = [nnz_per_row[perm[i]] for i in range(5)]
        for i in range(len(sorted_nnz) - 1):
            assert sorted_nnz[i] >= sorted_nnz[i + 1]

    def test_jds_col_start_bounds(self):
        cs = self.report["jds_col_start"]
        assert cs[0] == 0
        assert cs[-1] == 13

    def test_bandwidth_original(self):
        expected = compute_bandwidth(self.row_ptr, self.col_idx, 5)
        assert self.report["bandwidth_original"] == expected

    def test_bandwidth_not_increased(self):
        assert self.report["bandwidth_reordered"] <= self.report["bandwidth_original"]

    def test_rcm_perm_valid(self):
        assert sorted(self.report["rcm_perm"]) == list(range(5))

    def test_profile_original(self):
        assert self.report["profile_original"] == 4

    def test_profile_not_increased(self):
        assert self.report["profile_reordered"] <= self.report["profile_original"]

    def test_format_ell_ranked_above_jds(self):
        scores = self.report["format_scores"]
        assert scores["ELL"]["recommended_rank"] < scores["JDS"]["recommended_rank"], (
            f"For uniform rows, ELL should rank above JDS: "
            f"ELL={scores['ELL']['recommended_rank']}, JDS={scores['JDS']['recommended_rank']}"
        )

    def test_matrix_stats_cv(self):
        cv = self.report["matrix_stats"]["cv"]
        assert abs(cv - 0.1884) < 0.01, f"Expected cv ~ 0.1884, got {cv}"

    def test_matrix_stats_fill_ratio(self):
        fill = self.report["matrix_stats"]["ell_fill_ratio"]
        assert abs(fill - 0.8667) < 0.01, f"Expected fill ~ 0.8667, got {fill}"


# ---------------------------------------------------------------------------
# Test 2: Permuted band matrix -- RCM must reduce bandwidth
# ---------------------------------------------------------------------------
class TestPermutedBandMatrix:
    """12x12 tridiagonal matrix with random permutation applied."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        dim = 12
        self.dim = dim
        np.random.seed(42)

        rows, cols, vals = [], [], []
        for i in range(dim):
            rows.append(i); cols.append(i); vals.append(4.0)
            if i > 0:
                rows.append(i); cols.append(i - 1); vals.append(-1.0)
            if i < dim - 1:
                rows.append(i); cols.append(i + 1); vals.append(-1.0)

        A = sparse.csr_matrix((vals, (rows, cols)), shape=(dim, dim))

        perm = np.random.permutation(dim)
        P = sparse.csr_matrix(
            (np.ones(dim), (np.arange(dim), perm)), shape=(dim, dim)
        )
        A_perm = (P @ A @ P.T).tocsr()
        A_perm.sort_indices()

        vec = np.random.rand(dim)

        row_ptr = A_perm.indptr.tolist()
        col_idx = A_perm.indices.tolist()
        values = A_perm.data.tolist()

        self.row_ptr = row_ptr
        self.col_idx = col_idx
        self.original_bw = compute_bandwidth(row_ptr, col_idx, dim)

        data_dir = str(tmp_path / "band")
        output_path = str(tmp_path / "band_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec.tolist())

        self.report = run_pipeline(data_dir, output_path)
        self.ref_result = (A_perm @ vec).tolist()

    def test_csr_spmv(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["jds_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(
            self.report["ell_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["rcm_jds_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_bandwidth_strictly_reduced(self):
        assert self.report["bandwidth_reordered"] < self.report["bandwidth_original"], (
            f"RCM should reduce bandwidth: {self.report['bandwidth_reordered']} "
            f">= {self.report['bandwidth_original']}"
        )

    def test_bandwidth_original_correct(self):
        assert self.report["bandwidth_original"] == self.original_bw

    def test_profile_reduced(self):
        assert self.report["profile_reordered"] <= self.report["profile_original"]

    def test_profile_original_correct(self):
        expected = compute_profile_ref(self.row_ptr, self.col_idx, self.dim)
        assert self.report["profile_original"] == expected


# ---------------------------------------------------------------------------
# Test 3: Matrix with empty rows -- JDS edge case
# ---------------------------------------------------------------------------
class TestEmptyRows:
    """8x8 matrix where rows 0, 3, 5 are empty."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.dim = 8
        row_ptr = [0, 0, 1, 4, 4, 6, 6, 10, 11]
        col_idx = [1, 0, 2, 5, 3, 7, 1, 2, 4, 6, 0]
        values = [2.0, 1.0, 3.0, -1.0, 2.5, 1.5, -2.0, 1.0, 3.0, 4.0, 0.5]
        vec = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]

        self.row_ptr = row_ptr

        data_dir = str(tmp_path / "empty")
        output_path = str(tmp_path / "empty_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec)

        self.report = run_pipeline(data_dir, output_path)

        A = sparse.csr_matrix((values, col_idx, row_ptr), shape=(8, 8))
        self.ref_result = (A @ np.array(vec)).tolist()

    def test_csr_spmv(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["jds_spmv"], self.ref_result, atol=1e-5)

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(self.report["ell_spmv"], self.ref_result, atol=1e-5)

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["rcm_jds_spmv"], self.ref_result, atol=1e-5
        )

    def test_empty_rows_are_zero(self):
        for i in [0, 3, 5]:
            assert abs(self.report["csr_spmv"][i]) < 1e-10

    def test_jds_row_perm_sorted_by_nnz(self):
        perm = self.report["jds_row_perm"]
        nnz_per_row = [self.row_ptr[i + 1] - self.row_ptr[i] for i in range(self.dim)]
        sorted_nnz = [nnz_per_row[perm[i]] for i in range(self.dim)]
        for i in range(len(sorted_nnz) - 1):
            assert sorted_nnz[i] >= sorted_nnz[i + 1]

    def test_jds_col_start_valid(self):
        cs = self.report["jds_col_start"]
        assert cs[0] == 0
        assert cs[-1] == 11
        for i in range(len(cs) - 1):
            assert cs[i] <= cs[i + 1]

    def test_profile_original(self):
        assert self.report["profile_original"] == 15

    def test_format_jds_ranked_above_ell(self):
        scores = self.report["format_scores"]
        assert scores["JDS"]["recommended_rank"] < scores["ELL"]["recommended_rank"], (
            f"For variable rows, JDS should rank above ELL: "
            f"JDS={scores['JDS']['recommended_rank']}, ELL={scores['ELL']['recommended_rank']}"
        )


# ---------------------------------------------------------------------------
# Test 4: Larger random sparse matrix -- stress test
# ---------------------------------------------------------------------------
class TestLargeRandom:
    """50x50 random sparse matrix with ~10% density + diagonal."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        dim = 50
        self.dim = dim
        np.random.seed(123)

        A = sparse.random(dim, dim, density=0.1, format="csr", random_state=123)
        A = A + sparse.eye(dim, format="csr")
        A = A.tocsr()
        A.sort_indices()
        A.sum_duplicates()

        vec = np.random.rand(dim)

        row_ptr = A.indptr.tolist()
        col_idx = A.indices.tolist()
        values = A.data.tolist()

        self.row_ptr = row_ptr
        self.col_idx = col_idx

        data_dir = str(tmp_path / "large")
        output_path = str(tmp_path / "large_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec.tolist())

        self.report = run_pipeline(data_dir, output_path)
        self.ref_result = (A @ vec).tolist()

    def test_csr_spmv(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["jds_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(
            self.report["ell_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["rcm_jds_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_dimension(self):
        assert self.report["dimension"] == self.dim

    def test_rcm_perm_valid(self):
        assert sorted(self.report["rcm_perm"]) == list(range(self.dim))

    def test_jds_perm_valid(self):
        assert sorted(self.report["jds_row_perm"]) == list(range(self.dim))

    def test_bandwidth_not_increased(self):
        assert self.report["bandwidth_reordered"] <= self.report["bandwidth_original"]

    def test_jds_col_start_monotonic(self):
        cs = self.report["jds_col_start"]
        for i in range(len(cs) - 1):
            assert cs[i] <= cs[i + 1]

    def test_jds_col_start_endpoints(self):
        cs = self.report["jds_col_start"]
        nnz = self.row_ptr[-1]
        assert cs[0] == 0
        assert cs[-1] == nnz

    def test_profile_positive(self):
        assert self.report["profile_original"] > 0

    def test_profile_correct(self):
        expected = compute_profile_ref(self.row_ptr, self.col_idx, self.dim)
        assert self.report["profile_original"] == expected


# ---------------------------------------------------------------------------
# Test 5: Disconnected components -- RCM must handle multi-component graphs
# ---------------------------------------------------------------------------
class TestDisconnectedComponents:
    """10x10 block-diagonal (pentadiag + tridiag) scrambled by permutation."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        dim = 10
        self.dim = dim
        np.random.seed(77)

        rows1, cols1, vals1 = [], [], []
        for i in range(5):
            rows1.append(i); cols1.append(i); vals1.append(3.0)
            if i > 0:
                rows1.append(i); cols1.append(i - 1); vals1.append(-0.5)
                rows1.append(i - 1); cols1.append(i); vals1.append(-0.5)
            if i > 1:
                rows1.append(i); cols1.append(i - 2); vals1.append(0.1)
                rows1.append(i - 2); cols1.append(i); vals1.append(0.1)

        rows2, cols2, vals2 = [], [], []
        for i in range(5):
            rows2.append(i + 5); cols2.append(i + 5); vals2.append(2.0)
            if i > 0:
                rows2.append(i + 5); cols2.append(i + 4); vals2.append(-1.0)
                rows2.append(i + 4); cols2.append(i + 5); vals2.append(-1.0)

        all_rows = rows1 + rows2
        all_cols = cols1 + cols2
        all_vals = vals1 + vals2

        A = sparse.csr_matrix((all_vals, (all_rows, all_cols)), shape=(dim, dim))

        perm = np.array([4, 7, 1, 8, 0, 5, 3, 9, 2, 6])
        P = sparse.csr_matrix(
            (np.ones(dim), (np.arange(dim), perm)), shape=(dim, dim)
        )
        A_perm = (P @ A @ P.T).tocsr()
        A_perm.sort_indices()
        A_perm.sum_duplicates()

        vec = np.random.rand(dim)

        row_ptr = A_perm.indptr.tolist()
        col_idx = A_perm.indices.tolist()
        values = A_perm.data.tolist()

        self.row_ptr = row_ptr
        self.col_idx = col_idx
        self.original_bw = compute_bandwidth(row_ptr, col_idx, dim)

        data_dir = str(tmp_path / "disconn")
        output_path = str(tmp_path / "disconn_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec.tolist())

        self.report = run_pipeline(data_dir, output_path)
        self.ref_result = (A_perm @ vec).tolist()

    def test_csr_spmv(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["jds_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(
            self.report["ell_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(
            self.report["rcm_jds_spmv"], self.report["csr_spmv"], atol=1e-5
        )

    def test_bandwidth_significantly_reduced(self):
        assert self.report["bandwidth_reordered"] < self.report["bandwidth_original"], (
            f"Disconnected components should have reduced bandwidth: "
            f"{self.report['bandwidth_reordered']} >= {self.report['bandwidth_original']}"
        )

    def test_rcm_perm_valid(self):
        assert sorted(self.report["rcm_perm"]) == list(range(self.dim))

    def test_bandwidth_original_correct(self):
        assert self.report["bandwidth_original"] == self.original_bw


# ---------------------------------------------------------------------------
# Test 6: Diagonal matrix -- uniform rows, ELLPACK should be best format
# ---------------------------------------------------------------------------
class TestDiagonalMatrix:
    """10x10 diagonal matrix: all rows have exactly 1 non-zero."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        dim = 10
        self.dim = dim

        row_ptr = list(range(dim + 1))
        col_idx = list(range(dim))
        values = [2.0] * dim
        vec = [float(i + 1) for i in range(dim)]

        self.row_ptr = row_ptr
        self.col_idx = col_idx

        data_dir = str(tmp_path / "diag")
        output_path = str(tmp_path / "diag_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec)

        self.report = run_pipeline(data_dir, output_path)

        A = sparse.csr_matrix((values, col_idx, row_ptr), shape=(dim, dim))
        self.ref_result = (A @ np.array(vec)).tolist()

    def test_csr_spmv(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["jds_spmv"], self.ref_result, atol=1e-5)

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(self.report["ell_spmv"], self.ref_result, atol=1e-5)

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["rcm_jds_spmv"], self.ref_result, atol=1e-5)

    def test_profile_zero(self):
        assert self.report["profile_original"] == 0

    def test_format_ell_rank_1(self):
        scores = self.report["format_scores"]
        assert scores["ELL"]["recommended_rank"] == 1, (
            f"For diagonal matrix, ELL should rank 1st, got {scores['ELL']['recommended_rank']}"
        )

    def test_matrix_stats_cv_zero(self):
        assert self.report["matrix_stats"]["cv"] == 0.0

    def test_matrix_stats_fill_ratio_one(self):
        assert abs(self.report["matrix_stats"]["ell_fill_ratio"] - 1.0) < 1e-6

    def test_matrix_stats_max_nnz(self):
        assert self.report["matrix_stats"]["max_nnz_per_row"] == 1

    def test_matrix_stats_mean_nnz(self):
        assert abs(self.report["matrix_stats"]["mean_nnz_per_row"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Test 7: Star graph -- variable rows, JDS should be best format
# ---------------------------------------------------------------------------
class TestStarGraph:
    """15x15 star graph: row 0 connects to all, rows 1-14 connect to 0 only."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        dim = 15
        self.dim = dim

        row_ptr = [0]
        col_idx = []
        values = []

        for j in range(dim):
            col_idx.append(j)
            values.append(3.0 if j == 0 else 0.5)
        row_ptr.append(len(col_idx))

        for i in range(1, dim):
            col_idx.append(0)
            values.append(0.5)
            col_idx.append(i)
            values.append(1.0)
            row_ptr.append(len(col_idx))

        self.row_ptr = row_ptr
        self.col_idx = col_idx

        np.random.seed(200)
        vec = np.random.rand(dim).tolist()

        data_dir = str(tmp_path / "star")
        output_path = str(tmp_path / "star_report.json")
        write_csr_files(data_dir, row_ptr, col_idx, values, vec)

        self.report = run_pipeline(data_dir, output_path)

        A = sparse.csr_matrix((values, col_idx, row_ptr), shape=(dim, dim))
        self.ref_result = (A @ np.array(vec)).tolist()

    def test_csr_spmv(self):
        np.testing.assert_allclose(self.report["csr_spmv"], self.ref_result, atol=1e-5)

    def test_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["jds_spmv"], self.ref_result, atol=1e-5)

    def test_ell_matches_csr(self):
        np.testing.assert_allclose(self.report["ell_spmv"], self.ref_result, atol=1e-5)

    def test_rcm_jds_matches_csr(self):
        np.testing.assert_allclose(self.report["rcm_jds_spmv"], self.ref_result, atol=1e-5)

    def test_profile_correct(self):
        assert self.report["profile_original"] == 105

    def test_format_jds_rank_1(self):
        scores = self.report["format_scores"]
        assert scores["JDS"]["recommended_rank"] == 1, (
            f"For star graph, JDS should rank 1st, got {scores['JDS']['recommended_rank']}"
        )

    def test_format_ell_rank_3(self):
        scores = self.report["format_scores"]
        assert scores["ELL"]["recommended_rank"] == 3, (
            f"For star graph, ELL should rank 3rd, got {scores['ELL']['recommended_rank']}"
        )

    def test_matrix_stats_cv_high(self):
        cv = self.report["matrix_stats"]["cv"]
        assert cv > 1.0, f"Star graph should have CV > 1.0, got {cv}"

    def test_matrix_stats_fill_ratio_low(self):
        fill = self.report["matrix_stats"]["ell_fill_ratio"]
        assert fill < 0.3, f"Star graph should have low fill ratio, got {fill}"
