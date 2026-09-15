
"""
Tests for [[4,2,2]] code noisy state preparation — logical channel analysis.

Verifies that /app/result.json contains the correct exact polynomial coefficients
for codespace probability, projected logical populations, and infidelity scaling.
"""

import json
import os
import pytest
from fractions import Fraction


# ─── Expected answers (verified via independent symbolic density matrix simulation) ───

# P_cs(p) = 1 - 12p/5 + 64p^2/25 - 1024p^3/1125
EXPECTED_PCS = [Fraction(1), Fraction(-12, 5), Fraction(64, 25), Fraction(-1024, 1125)]

# q_{00}(p) = 1 - 8p/3 + 64p^2/25 - 2816p^3/3375
EXPECTED_Q00 = [Fraction(1), Fraction(-8, 3), Fraction(64, 25), Fraction(-2816, 3375)]

# q_{01}(p) = 4p/15 - 64p^2/225 + 256p^3/3375
EXPECTED_Q01 = [Fraction(0), Fraction(4, 15), Fraction(-64, 225), Fraction(256, 3375)]

# q_{10}(p) = 32p^2/225 - 256p^3/3375
EXPECTED_Q10 = [Fraction(0), Fraction(0), Fraction(32, 225), Fraction(-256, 3375)]

# q_{11}(p) = 32p^2/225 - 256p^3/3375
EXPECTED_Q11 = [Fraction(0), Fraction(0), Fraction(32, 225), Fraction(-256, 3375)]

EXPECTED_LEADING_POWER = 1
EXPECTED_LEADING_COEFF = Fraction(4, 15)

# Test points (as exact fractions)
TEST_POINTS = [
    Fraction(1, 100),
    Fraction(1, 20),
    Fraction(1, 10),
    Fraction(3, 20),
    Fraction(1, 5),
    Fraction(3, 10),
    Fraction(2, 5),
    Fraction(1, 2),
    Fraction(3, 5),
    Fraction(7, 10),
    Fraction(4, 5),
    Fraction(9, 10),
    Fraction(1, 3),
    Fraction(1, 7),
    Fraction(2, 7),
]


def eval_poly(coeffs, x):
    """Evaluate polynomial c_0 + c_1*x + c_2*x^2 + ... at x using exact arithmetic."""
    result = Fraction(0)
    for i, c in enumerate(coeffs):
        result += c * (x ** i)
    return result


def load_result():
    result_path = "/app/result.json"
    assert os.path.exists(result_path), f"Result file not found at {result_path}"
    with open(result_path) as f:
        return json.load(f)


@pytest.fixture
def result():
    return load_result()


class TestResultStructure:
    """Test that the result file has the expected structure."""

    def test_result_file_exists(self):
        assert os.path.exists("/app/result.json"), "result.json not found"

    def test_required_keys(self, result):
        required = [
            "codespace_probability_coefficients",
            "population_00_coefficients",
            "population_01_coefficients",
            "population_10_coefficients",
            "population_11_coefficients",
            "infidelity_leading_power",
            "infidelity_leading_coefficient",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_coefficients_are_lists(self, result):
        for key in [
            "codespace_probability_coefficients",
            "population_00_coefficients",
            "population_01_coefficients",
            "population_10_coefficients",
            "population_11_coefficients",
        ]:
            assert isinstance(result[key], list), f"{key} must be a list"

    def test_coefficients_are_parseable_fractions(self, result):
        for key in [
            "codespace_probability_coefficients",
            "population_00_coefficients",
            "population_01_coefficients",
            "population_10_coefficients",
            "population_11_coefficients",
        ]:
            for i, c in enumerate(result[key]):
                try:
                    Fraction(str(c))
                except (ValueError, ZeroDivisionError):
                    pytest.fail(f"{key}[{i}] = {c!r} is not a valid fraction")


class TestBoundaryValues:
    """Test values at p=0."""

    def test_pcs_at_zero(self, result):
        coeffs = [Fraction(str(c)) for c in result["codespace_probability_coefficients"]]
        val = eval_poly(coeffs, Fraction(0))
        assert val == Fraction(1), f"P_cs(0) should be 1, got {val}"

    def test_q00_at_zero(self, result):
        coeffs = [Fraction(str(c)) for c in result["population_00_coefficients"]]
        val = eval_poly(coeffs, Fraction(0))
        assert val == Fraction(1), f"q_00(0) should be 1, got {val}"

    def test_q01_at_zero(self, result):
        coeffs = [Fraction(str(c)) for c in result["population_01_coefficients"]]
        val = eval_poly(coeffs, Fraction(0))
        assert val == Fraction(0), f"q_01(0) should be 0, got {val}"

    def test_q10_at_zero(self, result):
        coeffs = [Fraction(str(c)) for c in result["population_10_coefficients"]]
        val = eval_poly(coeffs, Fraction(0))
        assert val == Fraction(0), f"q_10(0) should be 0, got {val}"

    def test_q11_at_zero(self, result):
        coeffs = [Fraction(str(c)) for c in result["population_11_coefficients"]]
        val = eval_poly(coeffs, Fraction(0))
        assert val == Fraction(0), f"q_11(0) should be 0, got {val}"


class TestCodespaceProbability:
    """Test codespace acceptance probability at multiple points."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_pcs_value(self, result, p_val):
        coeffs = [Fraction(str(c)) for c in result["codespace_probability_coefficients"]]
        actual = eval_poly(coeffs, p_val)
        expected = eval_poly(EXPECTED_PCS, p_val)
        assert actual == expected, (
            f"P_cs({p_val}) = {float(actual):.12f}, expected {float(expected):.12f}"
        )


class TestPopulation00:
    """Test target logical state population q_{00}(p) at multiple points."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_q00_value(self, result, p_val):
        coeffs = [Fraction(str(c)) for c in result["population_00_coefficients"]]
        actual = eval_poly(coeffs, p_val)
        expected = eval_poly(EXPECTED_Q00, p_val)
        assert actual == expected, (
            f"q_00({p_val}) = {float(actual):.12f}, expected {float(expected):.12f}"
        )


class TestPopulation01:
    """Test logical error population q_{01}(p) at multiple points."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_q01_value(self, result, p_val):
        coeffs = [Fraction(str(c)) for c in result["population_01_coefficients"]]
        actual = eval_poly(coeffs, p_val)
        expected = eval_poly(EXPECTED_Q01, p_val)
        assert actual == expected, (
            f"q_01({p_val}) = {float(actual):.12f}, expected {float(expected):.12f}"
        )


class TestPopulation10:
    """Test logical error population q_{10}(p) at multiple points."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_q10_value(self, result, p_val):
        coeffs = [Fraction(str(c)) for c in result["population_10_coefficients"]]
        actual = eval_poly(coeffs, p_val)
        expected = eval_poly(EXPECTED_Q10, p_val)
        assert actual == expected, (
            f"q_10({p_val}) = {float(actual):.12f}, expected {float(expected):.12f}"
        )


class TestPopulation11:
    """Test logical error population q_{11}(p) at multiple points."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_q11_value(self, result, p_val):
        coeffs = [Fraction(str(c)) for c in result["population_11_coefficients"]]
        actual = eval_poly(coeffs, p_val)
        expected = eval_poly(EXPECTED_Q11, p_val)
        assert actual == expected, (
            f"q_11({p_val}) = {float(actual):.12f}, expected {float(expected):.12f}"
        )


class TestConsistency:
    """Test that populations sum to P_cs and other consistency relations."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_population_sum_equals_pcs(self, result, p_val):
        """q_00 + q_01 + q_10 + q_11 must equal P_cs."""
        pcs_coeffs = [Fraction(str(c)) for c in result["codespace_probability_coefficients"]]
        q00_coeffs = [Fraction(str(c)) for c in result["population_00_coefficients"]]
        q01_coeffs = [Fraction(str(c)) for c in result["population_01_coefficients"]]
        q10_coeffs = [Fraction(str(c)) for c in result["population_10_coefficients"]]
        q11_coeffs = [Fraction(str(c)) for c in result["population_11_coefficients"]]

        pcs_val = eval_poly(pcs_coeffs, p_val)
        q_sum = (
            eval_poly(q00_coeffs, p_val)
            + eval_poly(q01_coeffs, p_val)
            + eval_poly(q10_coeffs, p_val)
            + eval_poly(q11_coeffs, p_val)
        )
        assert q_sum == pcs_val, (
            f"At p={p_val}: sum of populations = {float(q_sum):.12f}, "
            f"P_cs = {float(pcs_val):.12f}"
        )

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_q10_equals_q11(self, result, p_val):
        """By circuit symmetry, q_10 must equal q_11."""
        q10_coeffs = [Fraction(str(c)) for c in result["population_10_coefficients"]]
        q11_coeffs = [Fraction(str(c)) for c in result["population_11_coefficients"]]
        q10_val = eval_poly(q10_coeffs, p_val)
        q11_val = eval_poly(q11_coeffs, p_val)
        assert q10_val == q11_val, (
            f"At p={p_val}: q_10 = {float(q10_val):.12f}, "
            f"q_11 = {float(q11_val):.12f} (should be equal)"
        )

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_all_populations_nonnegative(self, result, p_val):
        """All populations must be non-negative for physical p in [0,1]."""
        for key in [
            "population_00_coefficients",
            "population_01_coefficients",
            "population_10_coefficients",
            "population_11_coefficients",
        ]:
            coeffs = [Fraction(str(c)) for c in result[key]]
            val = eval_poly(coeffs, p_val)
            assert val >= 0, f"At p={p_val}: {key} gives negative value {float(val)}"


class TestInfidelityScaling:
    """Test the leading-order scaling of the logical infidelity."""

    def test_leading_power(self, result):
        power = result["infidelity_leading_power"]
        assert power == EXPECTED_LEADING_POWER, (
            f"Infidelity leading power should be {EXPECTED_LEADING_POWER}, got {power}"
        )

    def test_leading_coefficient(self, result):
        coeff = Fraction(str(result["infidelity_leading_coefficient"]))
        assert coeff == EXPECTED_LEADING_COEFF, (
            f"Infidelity leading coefficient should be {EXPECTED_LEADING_COEFF}, got {coeff}"
        )

    def test_infidelity_matches_populations(self, result):
        """Verify that 1 - q_00/P_cs matches the stated leading order for small p."""
        pcs_coeffs = [Fraction(str(c)) for c in result["codespace_probability_coefficients"]]
        q00_coeffs = [Fraction(str(c)) for c in result["population_00_coefficients"]]

        # At small p, 1 - q_00/P_cs should approximately equal a * p^k
        p_val = Fraction(1, 1000)
        pcs_val = eval_poly(pcs_coeffs, p_val)
        q00_val = eval_poly(q00_coeffs, p_val)
        infidelity_exact = 1 - q00_val / pcs_val

        k = result["infidelity_leading_power"]
        a = Fraction(str(result["infidelity_leading_coefficient"]))
        leading_approx = a * (p_val ** k)

        # The relative error between exact and leading-order should be small
        if infidelity_exact != 0:
            rel_error = abs(float((infidelity_exact - leading_approx) / infidelity_exact))
            assert rel_error < 0.01, (
                f"At p=1/1000: infidelity = {float(infidelity_exact):.15e}, "
                f"leading approx = {float(leading_approx):.15e}, "
                f"relative error = {rel_error:.6f}"
            )


class TestLogicalFidelityValues:
    """Test the post-selected logical fidelity F_L = q_00/P_cs at multiple points."""

    @pytest.mark.parametrize("p_val", TEST_POINTS)
    def test_fidelity_value(self, result, p_val):
        pcs_coeffs = [Fraction(str(c)) for c in result["codespace_probability_coefficients"]]
        q00_coeffs = [Fraction(str(c)) for c in result["population_00_coefficients"]]

        pcs_val = eval_poly(pcs_coeffs, p_val)
        q00_val = eval_poly(q00_coeffs, p_val)
        assert pcs_val > 0, f"P_cs({p_val}) must be positive"

        actual_fidelity = q00_val / pcs_val

        expected_pcs = eval_poly(EXPECTED_PCS, p_val)
        expected_q00 = eval_poly(EXPECTED_Q00, p_val)
        expected_fidelity = expected_q00 / expected_pcs

        assert actual_fidelity == expected_fidelity, (
            f"F_L({p_val}) = {float(actual_fidelity):.12f}, "
            f"expected {float(expected_fidelity):.12f}"
        )
