
import json
import os

import numpy as np
import pytest
from scipy import sparse
from scipy.linalg import eigvalsh as dense_eigvalsh
from scipy.sparse.linalg import factorized


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def problem():
    A = sparse.load_npz("/app/problem/A.npz")
    B = sparse.load_npz("/app/problem/B.npz")
    C = sparse.load_npz("/app/problem/C.npz")
    M = sparse.load_npz("/app/problem/M.npz")
    rhs = np.load("/app/problem/rhs.npy")
    return A, B, C, M, rhs


@pytest.fixture(scope="module")
def results():
    assert os.path.exists("/app/results.json"), "/app/results.json not found"
    with open("/app/results.json") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def ref_Q1(problem):
    A, B, C, _, _ = problem
    n1 = A.shape[0]
    n2 = B.shape[0]
    solve_A = factorized(A.tocsc())
    BT = B.T.toarray()
    X = np.column_stack([solve_A(BT[:, i]) for i in range(n2)])
    Q1 = B.toarray() @ X + C.toarray()
    eigs = np.sort(np.linalg.eigvalsh(Q1))
    return Q1, eigs


@pytest.fixture(scope="module")
def ref_Q2(problem):
    A, B, C, _, _ = problem
    d_inv = 1.0 / A.diagonal()
    D_inv = sparse.diags(d_inv)
    Q2 = (B @ D_inv @ B.T).toarray() + C.toarray()
    eigs = np.sort(np.linalg.eigvalsh(Q2))
    return Q2, eigs


@pytest.fixture(scope="module")
def ref_gen_eig_1(problem, ref_Q1):
    A, _, _, M, _ = problem
    Q1, _ = ref_Q1
    n1 = A.shape[0]
    n_total = M.shape[0]
    M_d = M.toarray()
    P = np.zeros((n_total, n_total))
    P[:n1, :n1] = A.toarray()
    P[n1:, n1:] = Q1
    eigs = np.sort(dense_eigvalsh(M_d, P))
    return eigs


@pytest.fixture(scope="module")
def ref_gen_eig_2(problem, ref_Q2):
    A, _, _, M, _ = problem
    Q2, _ = ref_Q2
    n1 = A.shape[0]
    n_total = M.shape[0]
    M_d = M.toarray()
    P = np.zeros((n_total, n_total))
    P[:n1, :n1] = A.toarray()
    P[n1:, n1:] = Q2
    eigs = np.sort(dense_eigvalsh(M_d, P))
    return eigs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_results_file_structure(results):
    """Verify results.json has the required top-level keys."""
    required = [
        "Q1", "Q2",
        "gen_eig_1", "gen_eig_2",
        "solution", "relative_residual",
    ]
    for key in required:
        assert key in results, f"Missing key: {key}"


def test_Q1_largest(results, ref_Q1):
    _, ref_eigs = ref_Q1
    reported = np.sort(results["Q1"]["largest_5"])
    expected = np.sort(ref_eigs[-5:])
    np.testing.assert_allclose(reported, expected, rtol=1e-5,
                               err_msg="Q1: largest 5 eigenvalues mismatch")


def test_Q1_smallest(results, ref_Q1):
    _, ref_eigs = ref_Q1
    reported = np.sort(results["Q1"]["smallest_5"])
    expected = np.sort(ref_eigs[:5])
    np.testing.assert_allclose(reported, expected, rtol=1e-5,
                               err_msg="Q1: smallest 5 eigenvalues mismatch")


def test_Q2_largest(results, ref_Q2):
    _, ref_eigs = ref_Q2
    reported = np.sort(results["Q2"]["largest_5"])
    expected = np.sort(ref_eigs[-5:])
    np.testing.assert_allclose(reported, expected, rtol=1e-5,
                               err_msg="Q2: largest 5 eigenvalues mismatch")


def test_Q2_smallest(results, ref_Q2):
    _, ref_eigs = ref_Q2
    reported = np.sort(results["Q2"]["smallest_5"])
    expected = np.sort(ref_eigs[:5])
    np.testing.assert_allclose(reported, expected, rtol=1e-5,
                               err_msg="Q2: smallest 5 eigenvalues mismatch")


def test_gen_eig_1_largest(results, ref_gen_eig_1):
    reported = np.sort(results["gen_eig_1"]["largest_real_3"])
    expected = np.sort(ref_gen_eig_1[-3:])
    np.testing.assert_allclose(reported, expected, rtol=1e-4,
                               err_msg="gen_eig_1: largest 3 mismatch")


def test_gen_eig_1_smallest(results, ref_gen_eig_1):
    reported = np.sort(results["gen_eig_1"]["smallest_real_3"])
    expected = np.sort(ref_gen_eig_1[:3])
    np.testing.assert_allclose(reported, expected, rtol=1e-4,
                               err_msg="gen_eig_1: smallest 3 mismatch")


def test_gen_eig_2_largest(results, ref_gen_eig_2):
    reported = np.sort(results["gen_eig_2"]["largest_real_3"])
    expected = np.sort(ref_gen_eig_2[-3:])
    np.testing.assert_allclose(reported, expected, rtol=1e-4,
                               err_msg="gen_eig_2: largest 3 mismatch")


def test_gen_eig_2_smallest(results, ref_gen_eig_2):
    reported = np.sort(results["gen_eig_2"]["smallest_real_3"])
    expected = np.sort(ref_gen_eig_2[:3])
    np.testing.assert_allclose(reported, expected, rtol=1e-4,
                               err_msg="gen_eig_2: smallest 3 mismatch")


def test_solution_residual(results, problem):
    """Solution must satisfy the linear system to high accuracy."""
    _, _, _, M, rhs = problem
    x = np.array(results["solution"])
    assert x.shape == (M.shape[0],), f"Solution has wrong shape: {x.shape}"
    resid = np.linalg.norm(M @ x - rhs) / np.linalg.norm(rhs)
    assert resid < 1e-7, f"Relative residual too large: {resid:.2e}"


def test_reported_residual_consistent(results, problem):
    """The reported relative_residual must match the actual residual."""
    _, _, _, M, rhs = problem
    x = np.array(results["solution"])
    actual_resid = np.linalg.norm(M @ x - rhs) / np.linalg.norm(rhs)
    reported = results["relative_residual"]
    assert abs(actual_resid - reported) / max(actual_resid, 1e-15) < 0.1, \
        f"Reported residual ({reported:.2e}) inconsistent with actual ({actual_resid:.2e})"
