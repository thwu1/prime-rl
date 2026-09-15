"""
Test verification for Multi-Precision Numerical Analysis Challenge.

Compares agent output against pre-computed reference answers verified
to 15+ significant digits. Each value must match to at least 10
significant digits (relative error < 5e-10).

"""

import pytest
import os


# Pre-computed reference values (verified with mpmath at 50+ decimal digits
# using quadosc with Lambert-W zeros, scipy sparse direct solve, and
# mpmath nsum with Shanks acceleration respectively).
REF_INTEGRALS = [
    3.233674316777787605e-01,   # I(1)
    1.621767613966121624e-01,   # I(2)
    1.000786867681825731e-01,   # I(3)
    6.836051063038084408e-02,   # I(4)
    4.972914033015370799e-02,   # I(5)
]

REF_MATRIX_ENTRY = 7.413286083912125068e-01   # (M^{-1})_{1,1}, N=5000

REF_SERIES_SUM = 7.782352228838740338e-01     # sum (-1)^{n+1}/(n*H_n)


def assert_significant_digits(computed, reference, digits=10, label=""):
    """Assert computed matches reference to given significant digits."""
    if reference == 0:
        assert abs(computed) < 10**(-digits), (
            f"{label}: expected ~0, got {computed}"
        )
        return
    rel_err = abs((computed - reference) / reference)
    threshold = 5e-10  # ~9.3 significant digits (slightly lenient)
    assert rel_err < threshold, (
        f"{label}: computed={computed:.15e}, reference={reference:.15e}, "
        f"rel_error={rel_err:.2e}, threshold={threshold:.2e}"
    )


class TestProblem1:
    """Verify oscillatory integrals I(a) = integral_0^inf cos(a*t*e^t) dt."""

    def test_file_exists(self):
        assert os.path.isfile('/app/results/integrals.txt'), (
            "/app/results/integrals.txt not found"
        )

    def test_correct_line_count(self):
        with open('/app/results/integrals.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}"

    def test_integral_a1(self):
        with open('/app/results/integrals.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        computed = float(lines[0])
        assert_significant_digits(computed, REF_INTEGRALS[0], 10, "I(1)")

    def test_integral_a2(self):
        with open('/app/results/integrals.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        computed = float(lines[1])
        assert_significant_digits(computed, REF_INTEGRALS[1], 10, "I(2)")

    def test_integral_a3(self):
        with open('/app/results/integrals.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        computed = float(lines[2])
        assert_significant_digits(computed, REF_INTEGRALS[2], 10, "I(3)")

    def test_integral_a4(self):
        with open('/app/results/integrals.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        computed = float(lines[3])
        assert_significant_digits(computed, REF_INTEGRALS[3], 10, "I(4)")

    def test_integral_a5(self):
        with open('/app/results/integrals.txt') as f:
            lines = [l.strip() for l in f if l.strip()]
        computed = float(lines[4])
        assert_significant_digits(computed, REF_INTEGRALS[4], 10, "I(5)")


class TestProblem2:
    """Verify sparse matrix inverse entry (M^{-1})_{1,1}."""

    def test_file_exists(self):
        assert os.path.isfile('/app/results/matrix_entry.txt'), (
            "/app/results/matrix_entry.txt not found"
        )

    def test_value_accurate(self):
        with open('/app/results/matrix_entry.txt') as f:
            text = f.read().strip()
        computed = float(text)
        assert_significant_digits(
            computed, REF_MATRIX_ENTRY, 10, "M^{-1}[1,1]"
        )


class TestProblem3:
    """Verify alternating series S = sum (-1)^{n+1} / (n * H_n)."""

    def test_file_exists(self):
        assert os.path.isfile('/app/results/series_sum.txt'), (
            "/app/results/series_sum.txt not found"
        )

    def test_value_accurate(self):
        with open('/app/results/series_sum.txt') as f:
            text = f.read().strip()
        computed = float(text)
        assert_significant_digits(
            computed, REF_SERIES_SUM, 10, "Series S"
        )
