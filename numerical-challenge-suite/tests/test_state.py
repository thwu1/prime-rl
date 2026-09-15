"""
"""

import json
import math
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu
from scipy.integrate import quad


# Ground truth: which originals are correct
CORRECT_FLAGS = {
    "gauss_legendre": True,
    "hermite_quadrature": False,
    "sturm_eigencount": True,
    "sparse_logdet": False,
    "spectral_radius": False,
}


def _load_report():
    with open("/app/audit_report.json") as f:
        return json.load(f)


def _ref_gauss_legendre():
    """Reference via scipy adaptive quadrature."""
    val, _ = quad(lambda x: np.exp(x) / (1.0 + 25.0 * x**2), -1, 1,
                  limit=200)
    return val


def _ref_hermite_quadrature():
    """Analytical: 19 * sqrt(pi) / 4."""
    return 19.0 * math.sqrt(math.pi) / 4.0


def _ref_sturm_eigencount():
    """Sturm sequence eigenvalue count — independent reimplementation."""
    N = 5000
    diag = [2.0 + 0.3 * math.sin(2.0 * math.pi * i / N)
            for i in range(1, N + 1)]

    def count_below(sigma):
        cnt = 0
        q = diag[0] - sigma
        if q < 0:
            cnt += 1
        for k in range(1, N):
            if abs(q) < 1e-300:
                q = 1e-300 if q >= 0 else -1e-300
            q = (diag[k] - sigma) - 1.0 / q
            if q < 0:
                cnt += 1
        return cnt

    return count_below(0.8) - count_below(0.2)


def _ref_sparse_logdet():
    """Build the CORRECT symmetric matrix (off-diag = 0.05 on both sides)."""
    N = 1500
    rows, cols, data = [], [], []

    for i in range(N):
        rows.append(i)
        cols.append(i)
        data.append(np.sqrt(float(i + 1)))

    bands = [3**k for k in range(7)]
    for i in range(N):
        for b in bands:
            j = i + b
            if 0 <= j < N:
                rows.append(i)
                cols.append(j)
                data.append(0.05)
                rows.append(j)
                cols.append(i)
                data.append(0.05)

    M = sp.coo_matrix((data, (rows, cols)), shape=(N, N)).tocsc()
    lu = splu(M)
    return float(np.sum(np.log(np.abs(lu.U.diagonal()))))


def _ref_spectral_radius():
    """Full eigendecomposition for exact largest eigenvalue."""
    N = 400
    bw = 20
    B = np.zeros((N, N))
    for i in range(N):
        for d in range(-bw, bw + 1):
            j = i + d
            if 0 <= j < N:
                B[i, j] = 1.0 / (1.0 + abs(d))
    return float(np.max(np.linalg.eigvalsh(B)))


# -------------------- Tests --------------------


def test_report_file_exists_and_has_structure():
    """Verify audit_report.json exists with all required experiments."""
    report = _load_report()
    for key in CORRECT_FLAGS:
        assert key in report, f"Missing experiment '{key}' in audit report"
        entry = report[key]
        assert "value" in entry, f"Missing 'value' field in '{key}'"
        assert "original_is_correct" in entry, (
            f"Missing 'original_is_correct' field in '{key}'"
        )


def test_gauss_legendre_value():
    report = _load_report()
    agent_val = float(report["gauss_legendre"]["value"])
    ref = _ref_gauss_legendre()
    rel_err = abs(agent_val - ref) / abs(ref)
    assert rel_err < 1e-9, (
        f"gauss_legendre: rel_error={rel_err:.2e}, "
        f"expected={ref:.15e}, got={agent_val:.15e}"
    )


def test_hermite_quadrature_value():
    report = _load_report()
    agent_val = float(report["hermite_quadrature"]["value"])
    ref = _ref_hermite_quadrature()
    rel_err = abs(agent_val - ref) / abs(ref)
    assert rel_err < 1e-9, (
        f"hermite_quadrature: rel_error={rel_err:.2e}, "
        f"expected={ref:.15e}, got={agent_val:.15e}"
    )


def test_sturm_eigencount_value():
    report = _load_report()
    agent_val = int(report["sturm_eigencount"]["value"])
    ref = _ref_sturm_eigencount()
    assert agent_val == ref, (
        f"sturm_eigencount: expected={ref}, got={agent_val}"
    )


def test_sparse_logdet_value():
    report = _load_report()
    agent_val = float(report["sparse_logdet"]["value"])
    ref = _ref_sparse_logdet()
    rel_err = abs(agent_val - ref) / abs(ref)
    assert rel_err < 1e-9, (
        f"sparse_logdet: rel_error={rel_err:.2e}, "
        f"expected={ref:.15e}, got={agent_val:.15e}"
    )


def test_spectral_radius_value():
    report = _load_report()
    agent_val = float(report["spectral_radius"]["value"])
    ref = _ref_spectral_radius()
    rel_err = abs(agent_val - ref) / abs(ref)
    assert rel_err < 1e-9, (
        f"spectral_radius: rel_error={rel_err:.2e}, "
        f"expected={ref:.15e}, got={agent_val:.15e}"
    )


def test_correctness_flags():
    """Verify the agent correctly identified which experiments were buggy."""
    report = _load_report()
    for exp_name, expected_flag in CORRECT_FLAGS.items():
        agent_flag = report[exp_name]["original_is_correct"]
        assert isinstance(agent_flag, bool), (
            f"{exp_name}: original_is_correct must be bool, got {type(agent_flag)}"
        )
        assert agent_flag == expected_flag, (
            f"{exp_name}: expected original_is_correct={expected_flag}, "
            f"got {agent_flag}"
        )
