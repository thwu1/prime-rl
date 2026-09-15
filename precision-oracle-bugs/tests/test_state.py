
"""
Tests for the adaptive precision computation engine.

Verifies:
1. Result correctness against independently computed references
2. Diagnostics structure with dual-algorithm data
3. Cross-validation agreement between independent algorithms
4. Both algorithms individually produce correct values
"""

import json
import subprocess
import os
import pytest
from mpmath import mp, mpf, mpc, nstr, power, matrix, det, polylog, zeta


OUTPUT_DPS = 50
TOLERANCE_DIGITS = 40
ALGO_TOLERANCE = 35
CROSS_CHECK_MIN = 45


# ---- Reference value computation ----

_ref_cache = {}


def compute_reference(category, param):
    """Compute a reference value using correct mpmath built-ins at high precision."""
    key = (category, param)
    if key in _ref_cache:
        return _ref_cache[key]

    saved_dps = mp.dps
    try:
        if category == "polylog":
            parts = param.split(":", 1)
            s = int(parts[0])
            z_str = parts[1]
            mp.dps = OUTPUT_DPS + 200
            if z_str == "0.5":
                z = mpf("0.5")
            elif z_str == "-1":
                z = mpf("-1")
            elif z_str == "1-1e-20":
                z = 1 - power(10, -20)
            else:
                z = mpf(z_str)
            val = nstr(polylog(s, z), OUTPUT_DPS, strip_zeros=False)

        elif category == "hurwitz_zeta":
            parts = param.split(":", 1)
            s_str = parts[0]
            a_str = parts[1]
            mp.dps = OUTPUT_DPS + 200
            s = mpf(s_str)
            a = mpf(a_str)
            val = nstr(zeta(s, a), OUTPUT_DPS, strip_zeros=False)

        elif category == "hilbert_det":
            n = int(param)
            # Use generous guard digits to handle ill-conditioning
            mp.dps = OUTPUT_DPS + 20 * n
            H = matrix(n, n)
            for i in range(n):
                for j in range(n):
                    H[i, j] = mpf(1) / (i + j + 1)
            val = nstr(det(H), OUTPUT_DPS, strip_zeros=False)

        else:
            raise ValueError(f"Unknown category: {category}")
    finally:
        mp.dps = saved_dps

    _ref_cache[key] = val
    return val


def values_agree(computed_str, reference_str, min_digits):
    """Check if two value strings agree to min_digits significant digits."""
    saved_dps = mp.dps
    try:
        mp.dps = 200
        c = mpf(computed_str)
        r = mpf(reference_str)
        if r == 0:
            return abs(c) < power(10, -min_digits)
        rel_err = abs((c - r) / r)
        return rel_err < power(10, -min_digits)
    finally:
        mp.dps = saved_dps


# ---- Fixture: run engine once ----

@pytest.fixture(scope="module")
def engine_output():
    """Run the adaptive engine and load its output."""
    for f in ["/app/output/results.json", "/app/output/diagnostics.json"]:
        if os.path.exists(f):
            os.remove(f)

    assert os.path.exists("/app/adaptive_engine.py"), \
        "Engine not found at /app/adaptive_engine.py"

    result = subprocess.run(
        ["python3", "/app/adaptive_engine.py"],
        capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, f"Engine failed with:\n{result.stderr}"

    assert os.path.exists("/app/output/results.json"), \
        "Engine did not produce /app/output/results.json"
    assert os.path.exists("/app/output/diagnostics.json"), \
        "Engine did not produce /app/output/diagnostics.json"

    with open("/app/output/results.json") as f:
        results = json.load(f)
    with open("/app/output/diagnostics.json") as f:
        diagnostics = json.load(f)

    return results, diagnostics


# ---- Result correctness tests ----

class TestResultsCorrectness:
    """Verify all computed values are mathematically correct."""

    @pytest.mark.parametrize("param", ["2:0.5", "2:-1", "3:-1", "2:1-1e-20"])
    def test_polylog_value(self, engine_output, param):
        results, _ = engine_output
        ref = compute_reference("polylog", param)
        computed = results["polylog"][param]
        assert values_agree(computed, ref, TOLERANCE_DIGITS), (
            f"polylog({param}) mismatch:\n"
            f"  computed:  {computed}\n"
            f"  expected:  {ref}"
        )

    @pytest.mark.parametrize("param", ["2:0.25", "3:0.75", "0.5:0.25"])
    def test_hurwitz_value(self, engine_output, param):
        results, _ = engine_output
        ref = compute_reference("hurwitz_zeta", param)
        computed = results["hurwitz_zeta"][param]
        assert values_agree(computed, ref, TOLERANCE_DIGITS), (
            f"hurwitz_zeta({param}) mismatch:\n"
            f"  computed:  {computed}\n"
            f"  expected:  {ref}"
        )

    @pytest.mark.parametrize("n", [10, 15, 20])
    def test_hilbert_det_value(self, engine_output, n):
        results, _ = engine_output
        ref = compute_reference("hilbert_det", str(n))
        computed = results["hilbert_det"][str(n)]
        assert values_agree(computed, ref, TOLERANCE_DIGITS), (
            f"det(H_{n}) mismatch:\n"
            f"  computed:  {computed}\n"
            f"  expected:  {ref}"
        )


# ---- Diagnostics structure tests ----

ALL_KEYS = [
    "polylog:2:0.5", "polylog:2:-1", "polylog:3:-1", "polylog:2:1-1e-20",
    "hurwitz_zeta:2:0.25", "hurwitz_zeta:3:0.75", "hurwitz_zeta:0.5:0.25",
    "hilbert_det:10", "hilbert_det:15", "hilbert_det:20",
]


class TestDiagnosticsStructure:
    """Verify diagnostics report has proper dual-algorithm structure."""

    def test_top_level_keys(self, engine_output):
        _, diag = engine_output
        assert "computations" in diag, "diagnostics missing 'computations' key"
        assert "summary" in diag, "diagnostics missing 'summary' key"

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_dual_algorithm_present(self, engine_output, key):
        _, diag = engine_output
        assert key in diag["computations"], f"Missing computation entry: {key}"
        comp = diag["computations"][key]
        assert "algorithm_a" in comp, f"{key}: missing algorithm_a"
        assert "algorithm_b" in comp, f"{key}: missing algorithm_b"
        assert "name" in comp["algorithm_a"], f"{key}: algorithm_a missing name"
        assert "name" in comp["algorithm_b"], f"{key}: algorithm_b missing name"
        assert "value" in comp["algorithm_a"], f"{key}: algorithm_a missing value"
        assert "value" in comp["algorithm_b"], f"{key}: algorithm_b missing value"

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_different_algorithm_names(self, engine_output, key):
        _, diag = engine_output
        comp = diag["computations"][key]
        assert comp["algorithm_a"]["name"] != comp["algorithm_b"]["name"], (
            f"{key}: algorithms must have different names, "
            f"got '{comp['algorithm_a']['name']}' for both"
        )

    def test_summary_fields(self, engine_output):
        _, diag = engine_output
        s = diag["summary"]
        assert "all_cross_checks_passed" in s
        assert "min_agreement_digits" in s
        assert "total_computations" in s
        assert s["total_computations"] == 10


# ---- Cross-validation tests ----

class TestCrossValidation:
    """Verify cross-validation between independent algorithms."""

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_agreement_digits(self, engine_output, key):
        _, diag = engine_output
        comp = diag["computations"][key]
        assert "agreement_digits" in comp, f"{key}: missing agreement_digits"
        assert comp["agreement_digits"] >= CROSS_CHECK_MIN, (
            f"{key}: agreement {comp['agreement_digits']} < {CROSS_CHECK_MIN}"
        )

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_cross_check_status(self, engine_output, key):
        _, diag = engine_output
        comp = diag["computations"][key]
        assert "cross_check_passed" in comp, f"{key}: missing cross_check_passed"
        assert comp["cross_check_passed"] is True, (
            f"{key}: cross-check did not pass"
        )

    def test_summary_all_passed(self, engine_output):
        _, diag = engine_output
        assert diag["summary"]["all_cross_checks_passed"] is True, \
            "Not all cross-checks passed"
        assert diag["summary"]["min_agreement_digits"] >= CROSS_CHECK_MIN, (
            f"Min agreement {diag['summary']['min_agreement_digits']} "
            f"< {CROSS_CHECK_MIN}"
        )


# ---- Both algorithms must be individually correct ----

class TestBothAlgorithmsCorrect:
    """Verify both algorithm values are independently correct, preventing
    fake second algorithms that just copy the first result."""

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_algorithm_a_correct(self, engine_output, key):
        _, diag = engine_output
        parts = key.split(":", 1)
        category = parts[0]
        param = parts[1]
        ref = compute_reference(category, param)
        val_a = diag["computations"][key]["algorithm_a"]["value"]
        assert values_agree(val_a, ref, ALGO_TOLERANCE), (
            f"{key} algorithm_a incorrect:\n"
            f"  value:     {val_a}\n"
            f"  expected:  {ref}"
        )

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_algorithm_b_correct(self, engine_output, key):
        _, diag = engine_output
        parts = key.split(":", 1)
        category = parts[0]
        param = parts[1]
        ref = compute_reference(category, param)
        val_b = diag["computations"][key]["algorithm_b"]["value"]
        assert values_agree(val_b, ref, ALGO_TOLERANCE), (
            f"{key} algorithm_b incorrect:\n"
            f"  value:     {val_b}\n"
            f"  expected:  {ref}"
        )
