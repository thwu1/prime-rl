
"""Tests for corrected series analysis results."""

import json
import pytest
from fractions import Fraction

import mpmath

mpmath.mp.dps = 60


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def frac_to_mpf(s):
    """Convert a rational-number string like '3/7' or '-5' to mpmath.mpf."""
    f = Fraction(s)
    return mpmath.mpf(f.numerator) / mpmath.mpf(f.denominator)


def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def pade_eval(coeffs_str, m, n, z):
    """Compute the [m/n] Padé approximant from coefficient strings and evaluate at z."""
    coeffs = [frac_to_mpf(c) for c in coeffs_str[: m + n + 1]]
    p, q = mpmath.pade(coeffs, m, n)
    num = sum(c * z ** k for k, c in enumerate(p))
    den = sum(c * z ** k for k, c in enumerate(q))
    return num / den


# ---------------------------------------------------------------------------
# convergence radius
# ---------------------------------------------------------------------------

class TestConvergenceRadius:
    def test_f1_radius(self):
        r = mpmath.mpf(load_results()["f1"]["convergence_radius"])
        assert abs(r - 3) < mpmath.mpf("1e-6"), f"f1 radius {r} != 3"

    def test_f2_radius(self):
        r = mpmath.mpf(load_results()["f2"]["convergence_radius"])
        assert abs(r - 1) < mpmath.mpf("1e-6"), f"f2 radius {r} != 1"

    def test_f3_radius(self):
        r = mpmath.mpf(load_results()["f3"]["convergence_radius"])
        assert abs(r - mpmath.mpf("0.5")) < mpmath.mpf("1e-6"), f"f3 radius {r} != 0.5"


# ---------------------------------------------------------------------------
# singularity type
# ---------------------------------------------------------------------------

class TestSingularityType:
    def test_f1_type(self):
        assert load_results()["f1"]["singularity_type"] == "polar"

    def test_f2_type(self):
        assert load_results()["f2"]["singularity_type"] == "logarithmic_branch"

    def test_f3_type(self):
        assert load_results()["f3"]["singularity_type"] == "algebraic_branch"


# ---------------------------------------------------------------------------
# nearest singularity location
# ---------------------------------------------------------------------------

class TestNearestSingularity:
    def _check(self, fname, expected_re, expected_im, tol="1e-2"):
        results = load_results()
        ns = results[fname]["nearest_singularity"]
        loc = mpmath.mpc(ns["re"], ns["im"])
        expected = mpmath.mpc(expected_re, expected_im)
        assert abs(loc - expected) < mpmath.mpf(tol), (
            f"{fname}: nearest singularity {loc} != {expected}"
        )

    def test_f1_location(self):
        self._check("f1", "3", "0")

    def test_f2_location(self):
        self._check("f2", "-1", "0")

    def test_f3_location(self):
        self._check("f3", "-0.5", "0")


# ---------------------------------------------------------------------------
# Padé evaluations  (3 functions × 3 orders × 4 points = 36 checks)
# ---------------------------------------------------------------------------

_FUNCTIONS = ["f1", "f2", "f3"]
_ORDERS = [(5, 5), (10, 10), (14, 14)]
_POINT_INDICES = [0, 1, 2, 3]

_eval_params = [
    (fn, m, n, pi)
    for fn in _FUNCTIONS
    for m, n in _ORDERS
    for pi in _POINT_INDICES
]


class TestPadeEvaluations:
    @pytest.mark.parametrize("fname,m,n,pt_idx", _eval_params)
    def test_evaluation(self, fname, m, n, pt_idx):
        config = load_config()
        results = load_results()
        coeffs = config["functions"][fname]["coefficients"]
        pt = config["evaluation_points"][pt_idx]
        z = mpmath.mpc(pt["re"], pt["im"])

        ref = pade_eval(coeffs, m, n, z)

        order_key = f"{m}_{n}"
        reported = results[fname]["pade_evaluations"][order_key][str(pt_idx)]
        rep_val = mpmath.mpc(reported["re"], reported["im"])

        if abs(ref) > mpmath.mpf("1e-20"):
            rel_err = abs(rep_val - ref) / abs(ref)
            assert rel_err < mpmath.mpf("1e-30"), (
                f"{fname} [{m}/{n}] pt{pt_idx}: rel_err={float(rel_err):.2e}"
            )
        else:
            assert abs(rep_val - ref) < mpmath.mpf("1e-30"), (
                f"{fname} [{m}/{n}] pt{pt_idx}: abs_err too large"
            )
