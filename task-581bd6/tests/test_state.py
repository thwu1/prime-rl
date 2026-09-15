
"""
Verification tests for the singularly perturbed BVP solver.
Compares numerical solutions against known exact solutions.
"""

import json
import os

import numpy as np
import pytest
from scipy.special import erf


# ---------------------------------------------------------------------------
# Exact solution helpers
# ---------------------------------------------------------------------------

def _log_cosh_safe(x):
    """Numerically stable ln(cosh(x))."""
    ax = np.abs(np.asarray(x, dtype=float))
    return ax + np.log1p(np.exp(-2.0 * ax)) - np.log(2.0)


def exact_bvpT2(t, eps):
    """z(t) = (1 - exp((t-1)/eps)) / (1 - exp(-1/eps))"""
    return (1.0 - np.exp((t - 1.0) / eps)) / (1.0 - np.exp(-1.0 / eps))


def exact_bvpT10(t, eps):
    """z(t) = 1 + erf(t/sqrt(2*eps)) / erf(1/sqrt(2*eps))"""
    s = np.sqrt(2.0 * eps)
    return 1.0 + erf(t / s) / erf(1.0 / s)


def exact_bvpT14(t, eps):
    """z(t) = cos(pi*t) + exp((t-1)/sqrt(eps)) + exp(-(t+1)/sqrt(eps))"""
    se = np.sqrt(eps)
    return np.cos(np.pi * t) + np.exp((t - 1.0) / se) + np.exp(-(t + 1.0) / se)


def exact_bvpT20(t, eps):
    """z(t) = 1 + eps * ln(cosh((t - 0.745)/eps))"""
    return 1.0 + eps * _log_cosh_safe((t - 0.745) / eps)


def exact_bvpT21(t, eps):
    """z(t) = exp(-t / sqrt(eps))"""
    se = np.sqrt(eps)
    arg = t / se
    return np.where(arg < 700.0, np.exp(-arg), 0.0)


EXACT_FNS = {
    "bvpT2": exact_bvpT2,
    "bvpT10": exact_bvpT10,
    "bvpT14": exact_bvpT14,
    "bvpT20": exact_bvpT20,
    "bvpT21": exact_bvpT21,
}

PROBLEMS = ["bvpT2", "bvpT10", "bvpT14", "bvpT20", "bvpT21"]
EPS_STRS = ["0.1", "0.01", "0.001"]
TOLERANCES = {"0.1": 1e-4, "0.01": 1e-3, "0.001": 1e-2}

RESULTS_PATH = "/app/results.json"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def results():
    assert os.path.isfile(RESULTS_PATH), f"{RESULTS_PATH} not found"
    with open(RESULTS_PATH) as fh:
        data = json.load(fh)
    assert isinstance(data, dict), "results.json root must be a JSON object"
    return data


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

class TestStructure:
    @pytest.mark.parametrize("pid", PROBLEMS)
    def test_problem_present(self, results, pid):
        assert pid in results, f"Problem '{pid}' missing from results"

    @pytest.mark.parametrize("pid", PROBLEMS)
    @pytest.mark.parametrize("eps_str", EPS_STRS)
    def test_eps_present(self, results, pid, eps_str):
        assert eps_str in results[pid], (
            f"Epsilon '{eps_str}' missing for problem '{pid}'"
        )

    @pytest.mark.parametrize("pid", PROBLEMS)
    @pytest.mark.parametrize("eps_str", EPS_STRS)
    def test_keys_and_lengths(self, results, pid, eps_str):
        entry = results[pid][eps_str]
        assert "t" in entry and "y" in entry, "Each entry needs 't' and 'y'"
        assert len(entry["t"]) == 1000, (
            f"Expected 1000 grid points, got {len(entry['t'])}"
        )
        assert len(entry["y"]) == 1000, (
            f"Expected 1000 y-values, got {len(entry['y'])}"
        )


# ---------------------------------------------------------------------------
# Accuracy tests — the core verification
# ---------------------------------------------------------------------------

class TestAccuracy:
    @pytest.mark.parametrize("pid", PROBLEMS)
    @pytest.mark.parametrize("eps_str", EPS_STRS)
    def test_solution_accuracy(self, results, pid, eps_str):
        eps = float(eps_str)
        t = np.asarray(results[pid][eps_str]["t"], dtype=float)
        y_num = np.asarray(results[pid][eps_str]["y"], dtype=float)

        y_exact = EXACT_FNS[pid](t, eps)
        max_err = float(np.max(np.abs(y_num - y_exact)))
        tol = TOLERANCES[eps_str]

        assert max_err < tol, (
            f"{pid} @ eps={eps_str}: max error {max_err:.4e} >= tolerance {tol:.1e}"
        )

    @pytest.mark.parametrize("pid", PROBLEMS)
    @pytest.mark.parametrize("eps_str", EPS_STRS)
    def test_no_nans(self, results, pid, eps_str):
        y = np.asarray(results[pid][eps_str]["y"], dtype=float)
        assert not np.any(np.isnan(y)), f"{pid} @ eps={eps_str} contains NaNs"

    @pytest.mark.parametrize("pid", PROBLEMS)
    @pytest.mark.parametrize("eps_str", EPS_STRS)
    def test_finite(self, results, pid, eps_str):
        y = np.asarray(results[pid][eps_str]["y"], dtype=float)
        assert np.all(np.isfinite(y)), f"{pid} @ eps={eps_str} contains Inf"
