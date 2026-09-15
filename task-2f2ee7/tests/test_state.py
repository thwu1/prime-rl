"""Tests for the FPCore floating-point accuracy improver."""

import sys
import math
import os
import pytest

sys.path.insert(0, "/app")
import fp_improver

from mpmath import mp, mpf


def accuracy_bits(computed, exact_mp):
    """Compute bits of accuracy between a float64 result and an mpmath exact value.

    Uses relative error: bits = -log2(|computed - exact| / |exact|).
    Returns value in [0.0, 53.0].
    """
    mp.prec = 200
    if math.isnan(computed) or math.isinf(computed):
        return 0.0
    if exact_mp == 0:
        return 53.0 if computed == 0.0 else 0.0
    computed_mp = mpf(computed)
    rel_err = abs(computed_mp - exact_mp) / abs(exact_mp)
    if rel_err == 0:
        return 53.0
    bits = float(-mp.log(rel_err, 2))
    return max(0.0, min(53.0, bits))


# ============================================================
# Parser tests
# ============================================================

class TestParser:
    def test_parse_returns_list(self):
        with open("/app/benchmarks.fpcore") as f:
            text = f.read()
        exprs = fp_improver.parse_fpcore(text)
        assert isinstance(exprs, list)

    def test_parse_count(self):
        with open("/app/benchmarks.fpcore") as f:
            text = f.read()
        exprs = fp_improver.parse_fpcore(text)
        assert len(exprs) == 6, f"Expected 6 expressions, got {len(exprs)}"

    def test_parse_names(self):
        with open("/app/benchmarks.fpcore") as f:
            text = f.read()
        exprs = fp_improver.parse_fpcore(text)
        names = {e.name for e in exprs}
        expected = {
            "NMSE example 3.1",
            "expm1 (example 3.7)",
            "qlog (example 3.10)",
            "cos2 (problem 3.4.1)",
            "quadp (p42, positive)",
            "sqrtexp (problem 3.4.4)",
        }
        assert names == expected, f"Names mismatch: got {names}"

    def test_parse_params_single(self):
        with open("/app/benchmarks.fpcore") as f:
            text = f.read()
        exprs = fp_improver.parse_fpcore(text)
        by_name = {e.name: e for e in exprs}
        assert by_name["NMSE example 3.1"].params == ["x"]
        assert by_name["expm1 (example 3.7)"].params == ["x"]

    def test_parse_params_multi(self):
        with open("/app/benchmarks.fpcore") as f:
            text = f.read()
        exprs = fp_improver.parse_fpcore(text)
        by_name = {e.name: e for e in exprs}
        assert by_name["quadp (p42, positive)"].params == ["a", "b", "c"]

    def test_parse_body_exists(self):
        with open("/app/benchmarks.fpcore") as f:
            text = f.read()
        exprs = fp_improver.parse_fpcore(text)
        for e in exprs:
            assert e.body is not None, f"{e.name} has no body"


# ============================================================
# Float64 evaluator tests
# ============================================================

class TestEvalFloat64:
    def setup_method(self):
        with open("/app/benchmarks.fpcore") as f:
            self.exprs = fp_improver.parse_fpcore(f.read())
        self.by_name = {e.name: e for e in self.exprs}

    def test_nmse_at_one(self):
        expr = self.by_name["NMSE example 3.1"]
        result = fp_improver.eval_float64(expr, {"x": 1.0})
        expected = math.sqrt(2.0) - 1.0
        assert abs(result - expected) < 1e-14, f"Got {result}, expected {expected}"

    def test_expm1_at_half(self):
        expr = self.by_name["expm1 (example 3.7)"]
        result = fp_improver.eval_float64(expr, {"x": 0.5})
        expected = math.exp(0.5) - 1.0
        assert abs(result - expected) < 1e-14

    def test_cos2_at_one(self):
        expr = self.by_name["cos2 (problem 3.4.1)"]
        result = fp_improver.eval_float64(expr, {"x": 1.0})
        expected = (1.0 - math.cos(1.0)) / 1.0
        assert abs(result - expected) < 1e-14

    def test_quadp_known_roots(self):
        # x^2 + 5x + 6 = (x+2)(x+3), roots -2 and -3
        # quadp = (-5 + sqrt(25-24))/2 = (-5+1)/2 = -2
        expr = self.by_name["quadp (p42, positive)"]
        result = fp_improver.eval_float64(expr, {"a": 1.0, "b": 5.0, "c": 6.0})
        assert abs(result - (-2.0)) < 1e-12, f"Got {result}, expected -2.0"

    def test_qlog_at_half(self):
        expr = self.by_name["qlog (example 3.10)"]
        result = fp_improver.eval_float64(expr, {"x": 0.5})
        expected = math.log(0.5) / math.log(1.5)
        assert abs(result - expected) < 1e-13

    def test_sqrtexp_at_one(self):
        expr = self.by_name["sqrtexp (problem 3.4.4)"]
        result = fp_improver.eval_float64(expr, {"x": 1.0})
        expected = math.sqrt((math.exp(2.0) - 1.0) / (math.exp(1.0) - 1.0))
        assert abs(result - expected) < 1e-12


# ============================================================
# Exact evaluator tests
# ============================================================

class TestEvalExact:
    def setup_method(self):
        with open("/app/benchmarks.fpcore") as f:
            self.exprs = fp_improver.parse_fpcore(f.read())
        self.by_name = {e.name: e for e in self.exprs}

    def test_nmse_exact(self):
        expr = self.by_name["NMSE example 3.1"]
        result = fp_improver.eval_exact(expr, {"x": 1.0})
        mp.prec = 200
        expected = mp.sqrt(mpf(2)) - mpf(1)
        assert abs(float(result) - float(expected)) < 1e-14

    def test_expm1_exact(self):
        expr = self.by_name["expm1 (example 3.7)"]
        result = fp_improver.eval_exact(expr, {"x": 0.5})
        mp.prec = 200
        expected = mp.exp(mpf("0.5")) - 1
        assert abs(float(result) - float(expected)) < 1e-14


# ============================================================
# get_improved existence tests
# ============================================================

class TestGetImproved:
    def test_all_expressions_have_improved(self):
        with open("/app/benchmarks.fpcore") as f:
            exprs = fp_improver.parse_fpcore(f.read())
        for expr in exprs:
            fn = fp_improver.get_improved(expr.name)
            assert callable(fn), f"{expr.name}: get_improved did not return a callable"


# ============================================================
# Accuracy tests for improved functions
# ============================================================

class TestImprovedNMSE:
    """sqrt(x+1) - sqrt(x): catastrophic cancellation for large x."""

    def test_accuracy_at_cancellation_region(self):
        improved = fp_improver.get_improved("NMSE example 3.1")
        mp.prec = 200
        test_points = [5e15, 1e16, 1e17, 7.3e15, 2.1e16]
        for x in test_points:
            computed = improved(x)
            exact = mp.sqrt(mpf(x) + 1) - mp.sqrt(mpf(x))
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"NMSE 3.1 at x={x}: {bits:.1f} bits accuracy, need >= 40"
            )


class TestImprovedExpm1:
    """exp(x) - 1: cancellation near x=0."""

    def test_accuracy_near_zero(self):
        improved = fp_improver.get_improved("expm1 (example 3.7)")
        mp.prec = 200
        test_points = [1e-15, 1e-16, -1e-15, 7.3e-16, -4.2e-17]
        for x in test_points:
            computed = improved(x)
            exact = mp.exp(mpf(x)) - 1
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"expm1 at x={x}: {bits:.1f} bits accuracy, need >= 40"
            )


class TestImprovedQlog:
    """log(1-x)/log(1+x): cancellation near x=0."""

    def test_accuracy_near_zero(self):
        improved = fp_improver.get_improved("qlog (example 3.10)")
        mp.prec = 200
        test_points = [1e-15, 3.1e-16, -2.7e-16, 1e-17, -5.5e-15]
        for x in test_points:
            computed = improved(x)
            exact = mp.log(1 - mpf(x)) / mp.log(1 + mpf(x))
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"qlog at x={x}: {bits:.1f} bits accuracy, need >= 40"
            )


class TestImprovedCos2:
    """(1-cos(x))/(x*x): cancellation near x=0."""

    def test_accuracy_near_zero(self):
        improved = fp_improver.get_improved("cos2 (problem 3.4.1)")
        mp.prec = 200
        test_points = [1e-7, 4.2e-8, 1e-9, 7.7e-10, 3.3e-8]
        for x in test_points:
            computed = improved(x)
            exact = (1 - mp.cos(mpf(x))) / (mpf(x) ** 2)
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"cos2 at x={x}: {bits:.1f} bits accuracy, need >= 40"
            )


class TestImprovedQuadp:
    """Quadratic formula positive root: cancellation when b > 0."""

    def test_accuracy_cancellation(self):
        improved = fp_improver.get_improved("quadp (p42, positive)")
        mp.prec = 200
        test_cases = [
            (1.0, 1e8, 1.0),
            (1.0, 5e10, 1.0),
            (1.0, 1e12, 1.0),
            (1.0, 3.3e9, 0.7),
        ]
        for a, b, c in test_cases:
            computed = improved(a, b, c)
            d = mp.sqrt(mpf(b) ** 2 - 4 * mpf(a) * mpf(c))
            exact = (-mpf(b) + d) / (2 * mpf(a))
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"quadp at a={a},b={b},c={c}: {bits:.1f} bits accuracy, need >= 40"
            )

    def test_no_cancellation_case(self):
        """Verify improved version also handles non-cancellation cases."""
        improved = fp_improver.get_improved("quadp (p42, positive)")
        mp.prec = 200
        # x^2 - 5x + 6 = (x-2)(x-3), quadp = (5+1)/2 = 3
        a, b, c = 1.0, -5.0, 6.0
        computed = improved(a, b, c)
        d = mp.sqrt(mpf(b) ** 2 - 4 * mpf(a) * mpf(c))
        exact = (-mpf(b) + d) / (2 * mpf(a))
        bits = accuracy_bits(computed, exact)
        assert bits >= 40, (
            f"quadp no-cancel case: {bits:.1f} bits accuracy, need >= 40"
        )


class TestImprovedSqrtexp:
    """sqrt((exp(2x)-1)/(exp(x)-1)): 0/0 indeterminate near x=0."""

    def test_accuracy_near_zero(self):
        improved = fp_improver.get_improved("sqrtexp (problem 3.4.4)")
        mp.prec = 200
        test_points = [1e-15, 2.3e-16, 1e-14, 5.5e-16, 1e-13]
        for x in test_points:
            computed = improved(x)
            exact = mp.sqrt((mp.exp(2 * mpf(x)) - 1) / (mp.exp(mpf(x)) - 1))
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"sqrtexp at x={x}: {bits:.1f} bits accuracy, need >= 40"
            )

    def test_accuracy_moderate_x(self):
        """Also check at moderate x where original works but improved should too."""
        improved = fp_improver.get_improved("sqrtexp (problem 3.4.4)")
        mp.prec = 200
        for x in [0.5, 1.0, 2.0]:
            computed = improved(x)
            exact = mp.sqrt((mp.exp(2 * mpf(x)) - 1) / (mp.exp(mpf(x)) - 1))
            bits = accuracy_bits(computed, exact)
            assert bits >= 40, (
                f"sqrtexp at x={x}: {bits:.1f} bits accuracy, need >= 40"
            )
