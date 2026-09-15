"""
Tests for the matrix condition number estimation benchmark with C/LAPACK extension.

"""
import json
import os
import sys
import ctypes
import numpy as np
import scipy.linalg
import pytest
from math import comb

# ---------------------------------------------------------------------------
# Reference implementations — independent of agent code
# ---------------------------------------------------------------------------

def ref_moler(n):
    U = np.eye(n) - np.triu(np.ones((n, n)), 1)
    return U.T @ U

def ref_pascal(n):
    P = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            P[i, j] = comb(i + j, i)
    return P

def ref_frank(n):
    F = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if j >= i - 1:
                F[i, j] = n - max(i, j)
    return F

def ref_cauchy(n):
    C = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            C[i, j] = 1.0 / (i + j + 2)
    return C

def ref_parter(n):
    P = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            P[i, j] = 1.0 / (i - j + 0.5)
    return P

REF_GEN = {
    "moler": ref_moler,
    "pascal": ref_pascal,
    "frank": ref_frank,
    "cauchy": ref_cauchy,
    "parter": ref_parter,
}

# ---------------------------------------------------------------------------
# Fixture: load results.json once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        return json.load(f)


# ===== Structure tests =====================================================

class TestResultsStructure:
    def test_top_level_keys(self, results):
        assert "results" in results, "Missing top-level key 'results'"
        assert "crossover_nopiv" in results, "Missing top-level key 'crossover_nopiv'"

    def test_all_families_present(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            assert fam in results["results"], f"Missing family '{fam}' in results"

    def test_all_sizes_present(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            for n in [5, 10, 15, 20, 25]:
                assert str(n) in results["results"][fam], \
                    f"Missing size {n} for family '{fam}'"

    def test_entry_keys(self, results):
        required = [
            "exact_cond2", "tricond_nopiv", "tricond_piv",
            "hager_cond1", "blocked_cond1", "score_nopiv", "score_piv",
        ]
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            entry = results["results"][fam]["5"]
            for k in required:
                assert k in entry, f"Missing key '{k}' in {fam}/5"

    def test_crossover_families(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            assert fam in results["crossover_nopiv"], \
                f"Missing crossover entry for '{fam}'"


# ===== Matrix generation correctness =======================================

class TestMatrixImport:
    """Verify agent modules produce correct matrices."""

    def test_moler_structure(self):
        sys.path.insert(0, "/app")
        from matrices import moler
        M = moler(5)
        assert M.shape == (5, 5)
        np.testing.assert_allclose(M, M.T, atol=1e-12,
                                   err_msg="Moler matrix must be symmetric")
        np.testing.assert_allclose(np.diag(M), [1, 2, 3, 4, 5],
                                   err_msg="Moler diagonal must be [1..n]")
        eigvals = np.linalg.eigvalsh(M)
        assert np.all(eigvals > 0), "Moler matrix must be positive definite"

    def test_moler_offdiag(self):
        sys.path.insert(0, "/app")
        from matrices import moler
        M = moler(5)
        ref = ref_moler(5)
        np.testing.assert_allclose(M, ref, atol=1e-12)

    def test_moler_offdiag_n10(self):
        sys.path.insert(0, "/app")
        from matrices import moler
        M = moler(10)
        ref = ref_moler(10)
        np.testing.assert_allclose(M, ref, atol=1e-12)

    def test_pascal_known(self):
        sys.path.insert(0, "/app")
        from matrices import pascal_matrix
        P = pascal_matrix(4)
        expected = np.array([[1, 1, 1, 1],
                             [1, 2, 3, 4],
                             [1, 3, 6, 10],
                             [1, 4, 10, 20]], dtype=float)
        np.testing.assert_allclose(P, expected)

    def test_frank_hessenberg(self):
        sys.path.insert(0, "/app")
        from matrices import frank
        F = frank(6)
        for i in range(6):
            for j in range(6):
                if j < i - 1:
                    assert F[i, j] == 0.0, \
                        f"frank(6)[{i},{j}] should be 0, got {F[i,j]}"
        assert F[0, 0] == 6.0
        assert F[5, 5] == 1.0

    def test_frank_subdiagonal_nonzero(self):
        """Frank matrix is upper Hessenberg: first subdiagonal must be nonzero."""
        sys.path.insert(0, "/app")
        from matrices import frank
        F = frank(6)
        for i in range(1, 6):
            assert F[i, i - 1] != 0.0, \
                f"Frank subdiagonal F[{i},{i-1}] must be nonzero, got {F[i, i-1]}"

    def test_frank_subdiag_values(self):
        """Frank subdiagonal entries F[i, i-1] = n - max(i, i-1) = n - i."""
        sys.path.insert(0, "/app")
        from matrices import frank
        n = 8
        F = frank(n)
        for i in range(1, n):
            expected = n - i
            assert abs(F[i, i - 1] - expected) < 1e-12, \
                f"Frank F[{i},{i-1}] should be {expected}, got {F[i, i-1]}"

    def test_cauchy_entries(self):
        sys.path.insert(0, "/app")
        from matrices import cauchy_matrix
        C = cauchy_matrix(3)
        expected = np.array([[1/2, 1/3, 1/4],
                             [1/3, 1/4, 1/5],
                             [1/4, 1/5, 1/6]])
        np.testing.assert_allclose(C, expected)

    def test_parter_entries(self):
        sys.path.insert(0, "/app")
        from matrices import parter
        P = parter(3)
        assert abs(P[0, 0] - 2.0) < 1e-12
        assert abs(P[0, 1] - (-2.0)) < 1e-12
        assert abs(P[1, 0] - 1.0/1.5) < 1e-12


# ===== Exact condition numbers =============================================

class TestExactCondition:
    @pytest.mark.parametrize("fam,n", [
        ("moler", 5), ("moler", 10), ("moler", 15),
        ("pascal", 5), ("pascal", 10),
        ("frank", 5), ("frank", 10), ("frank", 15),
        ("cauchy", 5), ("cauchy", 10),
        ("parter", 5), ("parter", 10),
    ])
    def test_exact_cond2(self, results, fam, n):
        A = REF_GEN[fam](n)
        expected = float(np.linalg.cond(A))
        reported = results["results"][fam][str(n)]["exact_cond2"]
        np.testing.assert_allclose(reported, expected, rtol=1e-4,
            err_msg=f"Exact cond2 mismatch for {fam} n={n}")

    def test_moler_condition_growth(self, results):
        """Moler matrix condition should grow very rapidly with n."""
        c5  = results["results"]["moler"]["5"]["exact_cond2"]
        c10 = results["results"]["moler"]["10"]["exact_cond2"]
        c15 = results["results"]["moler"]["15"]["exact_cond2"]
        assert c10 > c5 * 100, "Moler cond should grow >100x from n=5 to n=10"
        assert c15 > c10 * 100, "Moler cond should grow >100x from n=10 to n=15"

    def test_all_conditions_at_least_one(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            for n in ["5", "10", "15", "20", "25"]:
                ec = results["results"][fam][n]["exact_cond2"]
                assert ec >= 1.0, f"cond({fam},{n}) = {ec} < 1"


# ===== Tricond (unpivoted) =================================================

class TestTricondNopiv:
    @pytest.mark.parametrize("fam", ["moler", "pascal", "frank", "cauchy", "parter"])
    def test_nopiv_n5(self, results, fam):
        A = REF_GEN[fam](5)
        R = np.linalg.qr(A, mode="r")
        d = np.abs(np.diag(R))
        expected = float(np.max(d) / np.min(d))
        reported = results["results"][fam]["5"]["tricond_nopiv"]
        np.testing.assert_allclose(reported, expected, rtol=1e-4,
            err_msg=f"tricond_nopiv mismatch for {fam} n=5")

    @pytest.mark.parametrize("fam", ["moler", "pascal", "cauchy", "parter"])
    def test_nopiv_n10(self, results, fam):
        A = REF_GEN[fam](10)
        R = np.linalg.qr(A, mode="r")
        d = np.abs(np.diag(R))
        expected = float(np.max(d) / np.min(d))
        reported = results["results"][fam]["10"]["tricond_nopiv"]
        np.testing.assert_allclose(reported, expected, rtol=1e-4,
            err_msg=f"tricond_nopiv mismatch for {fam} n=10")


# ===== Tricond (pivoted) ===================================================

class TestTricondPiv:
    @pytest.mark.parametrize("fam", ["moler", "pascal", "frank", "cauchy", "parter"])
    def test_piv_n5(self, results, fam):
        A = REF_GEN[fam](5)
        _, R, _ = scipy.linalg.qr(A, pivoting=True)
        d = np.abs(np.diag(R))
        expected = float(np.max(d) / np.min(d))
        reported = results["results"][fam]["5"]["tricond_piv"]
        np.testing.assert_allclose(reported, expected, rtol=1e-4,
            err_msg=f"tricond_piv mismatch for {fam} n=5")

    @pytest.mark.parametrize("fam", ["moler", "pascal", "cauchy", "parter"])
    def test_piv_n15(self, results, fam):
        A = REF_GEN[fam](15)
        _, R, _ = scipy.linalg.qr(A, pivoting=True)
        d = np.abs(np.diag(R))
        expected = float(np.max(d) / np.min(d))
        reported = results["results"][fam]["15"]["tricond_piv"]
        np.testing.assert_allclose(reported, expected, rtol=1e-4,
            err_msg=f"tricond_piv mismatch for {fam} n=15")


# ===== Hager-Higham estimator ==============================================

class TestHagerEstimator:
    @pytest.mark.parametrize("fam", ["moler", "pascal", "frank", "cauchy", "parter"])
    def test_reasonable_n5(self, results, fam):
        """Hager estimate within factor 10 of exact 1-norm condition."""
        A = REF_GEN[fam](5)
        exact_c1 = float(np.linalg.cond(A, p=1))
        reported = results["results"][fam]["5"]["hager_cond1"]
        ratio = reported / exact_c1
        assert 0.1 <= ratio <= 10.0, \
            f"Hager estimate for {fam} n=5: ratio {ratio:.4f} outside [0.1, 10]"

    @pytest.mark.parametrize("fam", ["moler", "pascal", "cauchy", "parter"])
    def test_reasonable_n10(self, results, fam):
        A = REF_GEN[fam](10)
        exact_c1 = float(np.linalg.cond(A, p=1))
        reported = results["results"][fam]["10"]["hager_cond1"]
        ratio = reported / exact_c1
        assert 0.1 <= ratio <= 10.0, \
            f"Hager estimate for {fam} n=10: ratio {ratio:.4f} outside [0.1, 10]"

    @pytest.mark.parametrize("fam", ["moler", "pascal", "cauchy"])
    def test_reasonable_n20(self, results, fam):
        A = REF_GEN[fam](20)
        exact_c1 = float(np.linalg.cond(A, p=1))
        reported = results["results"][fam]["20"]["hager_cond1"]
        ratio = reported / exact_c1
        assert 0.01 <= ratio <= 100.0, \
            f"Hager estimate for {fam} n=20: ratio {ratio:.4f} outside [0.01, 100]"

    def test_not_trivial(self, results):
        """Hager estimator should return kappa_1, not just ||A^{-1}||_1."""
        A = ref_moler(10)
        norm1 = float(np.linalg.norm(A, 1))
        hager = results["results"]["moler"]["10"]["hager_cond1"]
        assert hager > norm1, \
            "Hager cond1 must be > ||A||_1 for ill-conditioned matrices"

    def test_all_positive(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            for n in ["5", "10", "15", "20", "25"]:
                h = results["results"][fam][n]["hager_cond1"]
                assert h >= 1.0, f"hager_cond1({fam},{n}) = {h} < 1"

    def test_hager_scales_with_matrix_norm(self, results):
        """Hager estimates must scale proportional to ||A||_1 * ||A^{-1}||_1."""
        A5 = ref_pascal(5)
        A15 = ref_pascal(15)
        exact5 = float(np.linalg.cond(A5, p=1))
        exact15 = float(np.linalg.cond(A15, p=1))
        h5 = results["results"]["pascal"]["5"]["hager_cond1"]
        h15 = results["results"]["pascal"]["15"]["hager_cond1"]
        r5 = h5 / exact5
        r15 = h15 / exact15
        assert 0.1 <= r5 <= 10.0, f"Pascal n=5 hager/exact ratio {r5:.4f}"
        assert 0.1 <= r15 <= 10.0, f"Pascal n=15 hager/exact ratio {r15:.4f}"


# ===== C shared library and blocked estimator ==============================

class TestCLibrary:
    """Tests for the C/LAPACK blocked 1-norm condition estimator."""

    def test_shared_lib_exists(self):
        assert os.path.exists("/app/c_src/libblocked_est.so"), \
            "C shared library not found at /app/c_src/libblocked_est.so"

    def test_load_via_ctypes(self):
        lib = ctypes.CDLL("/app/c_src/libblocked_est.so")
        assert hasattr(lib, "blocked_cond1"), \
            "C library missing blocked_cond1 symbol"

    def _call_c_estimator(self, A, max_iter=6):
        """Helper: call the C blocked_cond1 on matrix A."""
        lib = ctypes.CDLL("/app/c_src/libblocked_est.so")
        lib.blocked_cond1.restype = ctypes.c_double
        lib.blocked_cond1.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
            ctypes.c_int,
        ]
        n = A.shape[0]
        A_flat = A.flatten().astype(np.float64)
        A_ptr = A_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
        return float(lib.blocked_cond1(A_ptr, n, max_iter))

    def test_identity_cond1(self):
        """Condition number of identity matrix is 1."""
        result = self._call_c_estimator(np.eye(5))
        np.testing.assert_allclose(result, 1.0, rtol=0.01,
            err_msg="C estimator: identity should have cond1=1")

    def test_scaled_identity(self):
        """Condition number of alpha*I is 1."""
        result = self._call_c_estimator(3.7 * np.eye(8))
        np.testing.assert_allclose(result, 1.0, rtol=0.01,
            err_msg="C estimator: scaled identity should have cond1=1")

    @pytest.mark.parametrize("fam", ["moler", "pascal", "frank", "cauchy", "parter"])
    def test_c_vs_exact_n5(self, fam):
        """C estimator within factor 10 of exact cond1 for n=5."""
        A = REF_GEN[fam](5)
        exact_c1 = float(np.linalg.cond(A, p=1))
        est = self._call_c_estimator(A)
        ratio = est / exact_c1
        assert 0.1 <= ratio <= 10.0, \
            f"C estimator for {fam} n=5: ratio {ratio:.4f} outside [0.1, 10]"

    @pytest.mark.parametrize("fam", ["moler", "pascal", "cauchy"])
    def test_c_vs_exact_n15(self, fam):
        """C estimator within factor 10 of exact cond1 for n=15."""
        A = REF_GEN[fam](15)
        exact_c1 = float(np.linalg.cond(A, p=1))
        est = self._call_c_estimator(A)
        ratio = est / exact_c1
        assert 0.1 <= ratio <= 10.0, \
            f"C estimator for {fam} n=15: ratio {ratio:.4f} outside [0.1, 10]"

    def test_c_positive_for_spd(self):
        """C estimator returns positive values for SPD matrices."""
        for n in [5, 10, 15]:
            A = ref_moler(n)
            est = self._call_c_estimator(A)
            assert est > 0, f"C estimator returned non-positive for moler({n})"

    def test_c_not_trivial(self):
        """C estimator should not return just ||A||_1 or just ||A^{-1}||_1."""
        A = ref_cauchy(10)
        norm1_A = float(np.linalg.norm(A, 1))
        est = self._call_c_estimator(A)
        # For ill-conditioned Cauchy, cond1 >> ||A||_1
        assert est > norm1_A * 10, \
            "C estimator seems to be missing the ||A^{-1}||_1 factor"


# ===== Blocked estimator in results.json ===================================

class TestBlockedInResults:
    def test_blocked_not_null(self, results):
        """All blocked_cond1 entries must be populated (not null)."""
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            for n in ["5", "10", "15", "20", "25"]:
                bc = results["results"][fam][n]["blocked_cond1"]
                assert bc is not None, \
                    f"blocked_cond1 is null for {fam} n={n}"

    def test_blocked_positive(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            for n in ["5", "10", "15", "20", "25"]:
                bc = results["results"][fam][n]["blocked_cond1"]
                assert bc is not None and bc > 0, \
                    f"blocked_cond1 non-positive for {fam} n={n}"

    @pytest.mark.parametrize("fam,n", [
        ("moler", 5), ("pascal", 5), ("frank", 5),
        ("cauchy", 5), ("parter", 5),
        ("moler", 10), ("pascal", 10), ("cauchy", 10),
    ])
    def test_blocked_vs_exact_cond1(self, results, fam, n):
        """blocked_cond1 in results should be within factor 10 of exact cond1."""
        A = REF_GEN[fam](n)
        exact_c1 = float(np.linalg.cond(A, p=1))
        bc = results["results"][fam][str(n)]["blocked_cond1"]
        assert bc is not None, f"blocked_cond1 is null for {fam} n={n}"
        ratio = bc / exact_c1
        assert 0.1 <= ratio <= 10.0, \
            f"blocked_cond1 ratio for {fam} n={n}: {ratio:.4f} outside [0.1, 10]"

    def test_blocked_ill_conditioned(self, results):
        """For severely ill-conditioned Cauchy(15), blocked estimate must be large."""
        A = ref_cauchy(15)
        exact_c1 = float(np.linalg.cond(A, p=1))
        bc = results["results"]["cauchy"]["15"]["blocked_cond1"]
        assert bc is not None
        # With the convergence bug, est would severely underestimate
        assert bc > exact_c1 * 0.01, \
            f"blocked_cond1 for cauchy n=15 is {bc:.2e}, expected near {exact_c1:.2e}"


# ===== Scores ==============================================================

class TestScores:
    @pytest.mark.parametrize("fam", ["moler", "pascal", "frank", "cauchy", "parter"])
    def test_score_nopiv_consistency(self, results, fam):
        """score_nopiv == tricond_nopiv / exact_cond2"""
        for n in ["5", "10", "15", "20", "25"]:
            e = results["results"][fam][n]
            if np.isfinite(e["tricond_nopiv"]) and np.isfinite(e["exact_cond2"]):
                expected = e["tricond_nopiv"] / e["exact_cond2"]
                np.testing.assert_allclose(e["score_nopiv"], expected, rtol=1e-6,
                    err_msg=f"score_nopiv inconsistency for {fam} n={n}")

    @pytest.mark.parametrize("fam", ["moler", "pascal", "frank", "cauchy", "parter"])
    def test_score_piv_consistency(self, results, fam):
        """score_piv == tricond_piv / exact_cond2"""
        for n in ["5", "10", "15", "20", "25"]:
            e = results["results"][fam][n]
            if np.isfinite(e["tricond_piv"]) and np.isfinite(e["exact_cond2"]):
                expected = e["tricond_piv"] / e["exact_cond2"]
                np.testing.assert_allclose(e["score_piv"], expected, rtol=1e-6,
                    err_msg=f"score_piv inconsistency for {fam} n={n}")

    def test_scores_positive(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            for n in ["5", "10", "15", "20", "25"]:
                e = results["results"][fam][n]
                assert e["score_nopiv"] > 0
                assert e["score_piv"] > 0


# ===== Crossover analysis ==================================================

class TestCrossover:
    def test_crossover_valid_values(self, results):
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            val = results["crossover_nopiv"][fam]
            if val is not None:
                assert val in [5, 10, 15, 20, 25], \
                    f"Crossover for {fam} = {val}, expected one of [5,10,15,20,25]"

    def test_crossover_consistent_with_scores(self, results):
        """If crossover = N, then score_nopiv at N must be >= 0.05 and finite."""
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            co = results["crossover_nopiv"][fam]
            if co is not None:
                score = results["results"][fam][str(co)]["score_nopiv"]
                assert np.isfinite(score) and score >= 0.05, \
                    f"Crossover {fam}={co} but score={score}"

    def test_crossover_no_higher(self, results):
        """No tested size above the crossover should have score >= 0.05 (finite)."""
        sizes = [5, 10, 15, 20, 25]
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            co = results["crossover_nopiv"][fam]
            if co is not None:
                for n in sizes:
                    if n > co:
                        score = results["results"][fam][str(n)]["score_nopiv"]
                        assert not (np.isfinite(score) and score >= 0.05), \
                            f"{fam} n={n} (above crossover {co}) has score={score}"

    def test_crossover_computed_with_correct_threshold(self, results):
        """Crossover must use threshold 0.05 as specified in config."""
        threshold = 0.05
        for fam in ["moler", "pascal", "frank", "cauchy", "parter"]:
            co = results["crossover_nopiv"][fam]
            sizes = [5, 10, 15, 20, 25]
            expected_co = None
            for n in sizes:
                score = results["results"][fam][str(n)]["score_nopiv"]
                if np.isfinite(score) and score >= threshold:
                    expected_co = n
            assert co == expected_co, \
                f"{fam}: crossover_nopiv={co} but expected {expected_co} " \
                f"with threshold={threshold}"

    def test_parter_has_large_crossover(self, results):
        """Parter matrix keeps reasonable unpivoted scores; crossover should be large."""
        co = results["crossover_nopiv"]["parter"]
        assert co is not None and co >= 20, \
            f"Parter crossover expected >= 20, got {co}"


# ===== Module existence ====================================================

class TestModuleFiles:
    def test_matrices_exists(self):
        assert os.path.exists("/app/matrices.py"), "matrices.py not found"

    def test_estimators_exists(self):
        assert os.path.exists("/app/estimators.py"), "estimators.py not found"

    def test_benchmark_exists(self):
        assert os.path.exists("/app/benchmark.py"), "benchmark.py not found"

    def test_results_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_c_source_exists(self):
        assert os.path.exists("/app/c_src/blocked_est.c"), "blocked_est.c not found"

    def test_makefile_exists(self):
        assert os.path.exists("/app/c_src/Makefile"), "Makefile not found"
