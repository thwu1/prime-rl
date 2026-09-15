"""
Verification tests for the high-precision numerical challenge.

"""

import json
import math
import os

import pytest

# Reference answers verified to 40+ significant digits by 20+ independent teams.
# Sources: OEIS A117231, A117237, A117240.
REFERENCES = {
    "problem1": 0.3233674316777787614,
    "problem2": 0.7250783462684011675,
    "problem3": 3.8375879792512261034e-7,
}

# 10 significant digits => relative error < 5e-10
TOLERANCE = 5e-10


def relative_error(computed, reference):
    if reference == 0:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


@pytest.fixture
def answers():
    path = "/app/answers.json"
    assert os.path.exists(path), f"answers.json not found at {path}"
    with open(path) as f:
        data = json.load(f)
    return data


class TestStructure:
    def test_file_exists(self):
        assert os.path.exists("/app/answers.json"), "answers.json missing"

    def test_valid_json(self):
        with open("/app/answers.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_all_keys(self, answers):
        for key in ("problem1", "problem2", "problem3"):
            assert key in answers, f"Key '{key}' missing from answers.json"

    def test_values_are_numeric(self, answers):
        for key in ("problem1", "problem2", "problem3"):
            val = answers[key]
            assert isinstance(val, (int, float)), (
                f"Value for '{key}' must be numeric, got {type(val)}"
            )


class TestProblem1:
    """Oscillatory improper integral: lim_{e->0} int_e^1 cos(ln(x)/x)/x dx."""

    def test_accuracy(self, answers):
        computed = float(answers["problem1"])
        ref = REFERENCES["problem1"]
        rel_err = relative_error(computed, ref)
        assert rel_err < TOLERANCE, (
            f"Problem 1: rel error {rel_err:.2e} >= {TOLERANCE:.2e}. "
            f"Got {computed:.15e}, expected {ref:.15e}"
        )

    def test_sign_and_magnitude(self, answers):
        val = float(answers["problem1"])
        assert 0.1 < val < 0.5, f"Problem 1 answer {val} outside plausible range (0.1, 0.5)"


class TestProblem2:
    """Sparse matrix inverse: (A^{-1})_{1,1} for 20000x20000 prime-diagonal matrix."""

    def test_accuracy(self, answers):
        computed = float(answers["problem2"])
        ref = REFERENCES["problem2"]
        rel_err = relative_error(computed, ref)
        assert rel_err < TOLERANCE, (
            f"Problem 2: rel error {rel_err:.2e} >= {TOLERANCE:.2e}. "
            f"Got {computed:.15e}, expected {ref:.15e}"
        )

    def test_sign_and_magnitude(self, answers):
        val = float(answers["problem2"])
        assert 0.1 < val < 1.0, f"Problem 2 answer {val} outside plausible range (0.1, 1.0)"


class TestProblem3:
    """Brownian exit probability from 10x1 rectangle through short sides."""

    def test_accuracy(self, answers):
        computed = float(answers["problem3"])
        ref = REFERENCES["problem3"]
        rel_err = relative_error(computed, ref)
        assert rel_err < TOLERANCE, (
            f"Problem 3: rel error {rel_err:.2e} >= {TOLERANCE:.2e}. "
            f"Got {computed:.15e}, expected {ref:.15e}"
        )

    def test_sign_and_magnitude(self, answers):
        val = float(answers["problem3"])
        assert 1e-8 < val < 1e-5, (
            f"Problem 3 answer {val} outside plausible range (1e-8, 1e-5)"
        )

    def test_independent_fourier_check(self, answers):
        """Cross-check using the Fourier series for the Laplace equation."""
        # P = (4/pi) * sum_{n=0}^{inf} (-1)^n / ((2n+1) * cosh((2n+1)*5*pi))
        # Series converges super-exponentially; first 3 terms give 20+ digits.
        prob = 0.0
        for n in range(5):
            k = 2 * n + 1
            arg = k * 5 * math.pi
            if arg > 700:  # avoid overflow in cosh
                break
            term = ((-1) ** n) / (k * math.cosh(arg))
            prob += term
        prob *= 4.0 / math.pi

        computed = float(answers["problem3"])
        rel_err = relative_error(computed, prob)
        assert rel_err < TOLERANCE, (
            f"Problem 3 independent check failed: rel error {rel_err:.2e}. "
            f"Got {computed:.15e}, independent calc {prob:.15e}"
        )
