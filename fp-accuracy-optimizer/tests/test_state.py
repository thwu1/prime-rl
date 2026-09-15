"""
Tests for regime-based floating-point stabilization.

Verifies that improved implementations achieve high accuracy
across specified input domains by comparing against arbitrary-precision
reference values computed with mpmath.
"""

import pytest
import math
import sys
import os
import json
import random

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_mpmath():
    from mpmath import mp
    mp.dps = 60
    return mp


def bits_of_accuracy(approx_f64, exact_mp):
    """Compute bits of accuracy between a float64 approximation and an mpmath exact value."""
    exact = float(exact_mp)
    approx = float(approx_f64)

    if math.isnan(approx) or math.isinf(approx):
        return 0.0
    if exact == 0.0:
        return 53.0 if approx == 0.0 else 0.0

    rel_err = abs(approx - exact) / abs(exact)
    if rel_err == 0.0:
        return 53.0
    return max(0.0, min(53.0, -math.log2(rel_err)))


def log_uniform_sample(lo, hi, rng):
    """Sample from log-uniform distribution between lo and hi (both positive)."""
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


# ---------------------------------------------------------------------------
# Original (naive) implementations — direct FPCore translations
# ---------------------------------------------------------------------------

def original_1(x):
    """(exp(x) - 1 - x) / x^2"""
    return (math.exp(x) - 1.0 - x) / (x * x)

def original_2(x):
    """coth(x) - 1/x = (exp(x)+exp(-x))/(exp(x)-exp(-x)) - 1/x"""
    return (math.exp(x) + math.exp(-x)) / (math.exp(x) - math.exp(-x)) - 1.0 / x

def original_3(x):
    """(sin(x) - x*cos(x)) / (x - sin(x))"""
    return (math.sin(x) - x * math.cos(x)) / (x - math.sin(x))

def original_4(x, y):
    """(exp(x) - exp(y)) / (x - y)"""
    return (math.exp(x) - math.exp(y)) / (x - y)


# ---------------------------------------------------------------------------
# Reference (high-precision) implementations
# ---------------------------------------------------------------------------

def reference_1(x, mp):
    x = mp.mpf(x)
    return (mp.exp(x) - 1 - x) / (x * x)

def reference_2(x, mp):
    x = mp.mpf(x)
    return (mp.exp(x) + mp.exp(-x)) / (mp.exp(x) - mp.exp(-x)) - 1 / x

def reference_3(x, mp):
    x = mp.mpf(x)
    return (mp.sin(x) - x * mp.cos(x)) / (x - mp.sin(x))

def reference_4(x, y, mp):
    x, y = mp.mpf(x), mp.mpf(y)
    return (mp.exp(x) - mp.exp(y)) / (x - y)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 12345
N_SAMPLES = 2000
ACCURACY_THRESHOLD = 38  # minimum average bits of accuracy for improved


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestImprovedAccuracy:
    """Test that improved expressions achieve high accuracy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from improved import (
            improved_1, improved_2, improved_3, improved_4,
        )
        self.improved = {
            1: improved_1, 2: improved_2, 3: improved_3,
            4: improved_4,
        }

    def _measure_accuracy(self, func, ref_func, sample_points, multivar=False):
        mp = _setup_mpmath()
        total_bits = 0.0
        valid = 0
        for pt in sample_points:
            if multivar:
                exact = ref_func(*pt, mp)
                try:
                    approx = func(*pt)
                except (OverflowError, ValueError, ZeroDivisionError):
                    valid += 1
                    continue
            else:
                exact = ref_func(pt, mp)
                try:
                    approx = func(pt)
                except (OverflowError, ValueError, ZeroDivisionError):
                    valid += 1
                    continue

            bits = bits_of_accuracy(approx, exact)
            total_bits += bits
            valid += 1

        return total_bits / valid if valid > 0 else 0.0

    # --- Expression 1: (exp(x) - 1 - x) / x^2 ---

    def test_expr1_second_order_exp(self):
        """Second-order exp cancellation: (exp(x)-1-x)/x^2 near x=0."""
        rng = random.Random(SEED)
        points = []
        for _ in range(N_SAMPLES):
            x = log_uniform_sample(1e-12, 0.1, rng)
            if rng.random() < 0.5:
                x = -x
            points.append(x)

        orig_bits = self._measure_accuracy(original_1, reference_1, points)
        impr_bits = self._measure_accuracy(self.improved[1], reference_1, points)

        assert impr_bits >= ACCURACY_THRESHOLD, (
            f"improved_1 avg accuracy = {impr_bits:.1f} bits, need >= {ACCURACY_THRESHOLD}. "
            f"Original avg = {orig_bits:.1f} bits."
        )
        assert impr_bits > orig_bits + 5, (
            f"improved_1 ({impr_bits:.1f}) not significantly better than original ({orig_bits:.1f})"
        )

    # --- Expression 2: coth(x) - 1/x (Langevin function) ---

    def test_expr2_langevin(self):
        """Langevin function: coth(x) - 1/x with cancellation of divergences near x=0."""
        rng = random.Random(SEED)
        points = [log_uniform_sample(1e-6, 10.0, rng) for _ in range(N_SAMPLES)]

        orig_bits = self._measure_accuracy(original_2, reference_2, points)
        impr_bits = self._measure_accuracy(self.improved[2], reference_2, points)

        assert impr_bits >= ACCURACY_THRESHOLD, (
            f"improved_2 avg accuracy = {impr_bits:.1f} bits, need >= {ACCURACY_THRESHOLD}. "
            f"Original avg = {orig_bits:.1f} bits."
        )
        assert impr_bits > orig_bits + 3, (
            f"improved_2 ({impr_bits:.1f}) not significantly better than original ({orig_bits:.1f})"
        )

    # --- Expression 3: (sin(x) - x*cos(x)) / (x - sin(x)) ---

    def test_expr3_trig_indeterminate(self):
        """Trigonometric indeterminate form: 0/0 as x->0, limiting value 2."""
        rng = random.Random(SEED)
        points = [log_uniform_sample(1e-8, 2.0, rng) for _ in range(N_SAMPLES)]

        orig_bits = self._measure_accuracy(original_3, reference_3, points)
        impr_bits = self._measure_accuracy(self.improved[3], reference_3, points)

        assert impr_bits >= ACCURACY_THRESHOLD, (
            f"improved_3 avg accuracy = {impr_bits:.1f} bits, need >= {ACCURACY_THRESHOLD}. "
            f"Original avg = {orig_bits:.1f} bits."
        )
        assert impr_bits > orig_bits + 5, (
            f"improved_3 ({impr_bits:.1f}) not significantly better than original ({orig_bits:.1f})"
        )

    # --- Expression 4: (exp(x) - exp(y)) / (x - y) ---

    def test_expr4_exp_diff_quotient(self):
        """Exp difference quotient: catastrophic cancellation when x is close to y."""
        rng = random.Random(SEED)
        points = []
        for _ in range(N_SAMPLES):
            x = rng.uniform(-20.0, 20.0)
            d = log_uniform_sample(1e-12, 1e-2, rng)
            if rng.random() < 0.5:
                d = -d
            y = x - d
            points.append((x, y))

        orig_bits = self._measure_accuracy(original_4, reference_4, points, multivar=True)
        impr_bits = self._measure_accuracy(self.improved[4], reference_4, points, multivar=True)

        assert impr_bits >= ACCURACY_THRESHOLD, (
            f"improved_4 avg accuracy = {impr_bits:.1f} bits, need >= {ACCURACY_THRESHOLD}. "
            f"Original avg = {orig_bits:.1f} bits."
        )
        assert impr_bits > orig_bits + 5, (
            f"improved_4 ({impr_bits:.1f}) not significantly better than original ({orig_bits:.1f})"
        )

    # --- Correctness spot checks ---

    def test_correctness_spot_checks(self):
        """Spot-check that improved functions give correct results at known points."""
        mp = _setup_mpmath()

        # Expression 1: at x=0.001 (in the cancellation-prone region)
        exact = float(reference_1(0.001, mp))
        assert abs(self.improved[1](0.001) - exact) / abs(exact) < 1e-14, \
            f"improved_1(0.001) = {self.improved[1](0.001)}, expected {exact}"

        # Expression 2: at x=0.01 (near-zero divergence region)
        exact = float(reference_2(0.01, mp))
        assert abs(self.improved[2](0.01) - exact) / abs(exact) < 1e-14, \
            f"improved_2(0.01) = {self.improved[2](0.01)}, expected {exact}"

        # Expression 3: at x=0.001 (near-zero indeterminate region)
        exact = float(reference_3(0.001, mp))
        assert abs(self.improved[3](0.001) - exact) / abs(exact) < 1e-14, \
            f"improved_3(0.001) = {self.improved[3](0.001)}, expected {exact}"

        # Expression 4: at x=1.0, y=1.0+1e-8 (close-value cancellation)
        exact = float(reference_4(1.0, 1.0 + 1e-8, mp))
        assert abs(self.improved[4](1.0, 1.0 + 1e-8) - exact) / abs(exact) < 1e-10, \
            f"improved_4(1.0, 1.0+1e-8) = {self.improved[4](1.0, 1.0 + 1e-8)}, expected {exact}"

    # --- No arbitrary-precision cheating ---

    def test_no_arbitrary_precision(self):
        """Improved functions must not use arbitrary-precision libraries."""
        with open('/app/improved.py') as f:
            source = f.read()
        assert 'import mpmath' not in source and 'from mpmath' not in source, \
            "improved.py must not use mpmath"
        assert 'import decimal' not in source and 'from decimal' not in source, \
            "improved.py must not use the decimal module"
        assert 'import gmpy' not in source and 'from gmpy' not in source, \
            "improved.py must not use gmpy"

    # --- Report validation ---

    def test_report_exists_and_valid(self):
        """Check that the measurement report exists, is valid JSON, and shows improvement."""
        assert os.path.exists('/app/report.json'), "report.json not found at /app/report.json"
        with open('/app/report.json') as f:
            report = json.load(f)

        assert 'expressions' in report, "report.json must have 'expressions' key"
        assert len(report['expressions']) == 4, \
            f"report.json must have 4 entries, got {len(report['expressions'])}"

        for entry in report['expressions']:
            assert 'id' in entry, "each entry must have 'id'"
            assert 'original_avg_bits' in entry, "each entry must have 'original_avg_bits'"
            assert 'improved_avg_bits' in entry, "each entry must have 'improved_avg_bits'"
            assert entry['improved_avg_bits'] > entry['original_avg_bits'], (
                f"Expression {entry['id']}: improved ({entry['improved_avg_bits']:.1f}) "
                f"must be better than original ({entry['original_avg_bits']:.1f})"
            )
