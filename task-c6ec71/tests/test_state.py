"""Tests for the Bézier arc length computation engine."""

import sys
import os
import json
import math
import ctypes

sys.path.insert(0, '/app')

import pytest
from bezier import Point, QuadBez, CubicBez, make_quad, make_cubic


def load_reference():
    with open('/app/reference_curves.json') as f:
        return json.load(f)


# ===================================================================
# Helper: pure-Python GL quadrature for cross-checking
# ===================================================================

def python_gl_arclen(c, order=16):
    """Pure Python GL quadrature for cubic arc length (reference)."""
    from coefficients import GAUSS_LEGENDRE
    gl = GAUSS_LEGENDRE[order]
    total = 0.0
    for node, weight in zip(gl["nodes"], gl["weights"]):
        d = c.deriv_at(node)
        total += weight * d.norm()
    return total


def adaptive_simpson_arclen(curve, tol=1e-14, max_depth=50):
    """Adaptive Simpson's rule for arc length — independent reference."""
    def speed(t):
        d = curve.deriv_at(t)
        return d.norm()

    def _quad(a, b, fa, fm, fb, s, tol, depth):
        m = (a + b) / 2.0
        h = (b - a) / 2.0
        m1 = (a + m) / 2.0
        m2 = (m + b) / 2.0
        fm1 = speed(m1)
        fm2 = speed(m2)
        s1 = h / 6.0 * (fa + 4 * fm1 + fm)
        s2 = h / 6.0 * (fm + 4 * fm2 + fb)
        ss = s1 + s2
        if depth <= 0 or abs(ss - s) <= 15 * tol:
            return ss + (ss - s) / 15.0
        return (_quad(a, m, fa, fm1, fm, s1, tol / 2, depth - 1) +
                _quad(m, b, fm, fm2, fb, s2, tol / 2, depth - 1))

    fa = speed(0.0)
    fb = speed(1.0)
    fm = speed(0.5)
    s = (1.0) / 6.0 * (fa + 4 * fm + fb)
    return _quad(0.0, 1.0, fa, fm, fb, s, tol, max_depth)


# ===================================================================
# Test: C shared library exists and loads
# ===================================================================

class TestCLibrary:
    def test_shared_library_exists(self):
        assert os.path.isfile('/app/libquadrature.so'), \
            "C shared library /app/libquadrature.so not found. Run 'make -C /app'."

    def test_shared_library_loads(self):
        lib = ctypes.CDLL('/app/libquadrature.so')
        assert hasattr(lib, 'cubic_arclen_gl'), \
            "Function cubic_arclen_gl not found in libquadrature.so"
        assert hasattr(lib, 'cubic_arclen_gl_interval'), \
            "Function cubic_arclen_gl_interval not found in libquadrature.so"

    def test_c_gl_straight_line(self):
        """C GL quadrature on a straight line should give exactly 1.0."""
        from coefficients import GAUSS_LEGENDRE
        lib = ctypes.CDLL('/app/libquadrature.so')
        lib.cubic_arclen_gl.restype = ctypes.c_double

        gl = GAUSS_LEGENDRE[16]
        px = (ctypes.c_double * 4)(0.0, 1 / 3, 2 / 3, 1.0)
        py = (ctypes.c_double * 4)(0.0, 0.0, 0.0, 0.0)
        nodes = (ctypes.c_double * 16)(*gl["nodes"])
        weights = (ctypes.c_double * 16)(*gl["weights"])

        result = lib.cubic_arclen_gl(px, py, nodes, weights, 16)
        assert abs(result - 1.0) < 1e-14, \
            f"C GL on straight line: expected 1.0, got {result}"


# ===================================================================
# Test: arclength module imports and has required functions
# ===================================================================

class TestModuleInterface:
    def test_imports(self):
        from arclength import (quad_arclen_analytical, cubic_arclen_gl,
                               estimate_cubic_error, arclen_adaptive, arclen)

    def test_arclen_dispatches_quad(self):
        from arclength import arclen
        q = make_quad([0, 0.5, 1], [0, 0, 0])
        result = arclen(q)
        assert isinstance(result, float)
        assert abs(result - 1.0) < 1e-10

    def test_arclen_dispatches_cubic(self):
        from arclength import arclen
        c = make_cubic([0, 1 / 3, 2 / 3, 1], [0, 0, 0, 0])
        result = arclen(c)
        assert isinstance(result, float)
        assert abs(result - 1.0) < 1e-10


# ===================================================================
# Test: Quadratic arc length precision
# ===================================================================

class TestQuadraticArclen:
    @pytest.fixture
    def ref_data(self):
        return load_reference()["quadratic"]

    def test_straight_line(self, ref_data):
        from arclength import arclen
        entry = next(e for e in ref_data if e["name"] == "straight_line")
        curve = make_quad(entry["px"], entry["py"])
        result = arclen(curve)
        assert abs(result - 1.0) < 1e-14, \
            f"Straight line: expected 1.0, got {result}"

    def test_near_linear_stability(self, ref_data):
        """Near-degenerate curve must not produce NaN or large error."""
        from arclength import arclen
        entry = next(e for e in ref_data if e["name"] == "near_linear")
        curve = make_quad(entry["px"], entry["py"])
        result = arclen(curve)
        assert math.isfinite(result), f"Near-linear produced non-finite: {result}"
        assert abs(result - 1.0) < 1e-8, \
            f"Near-linear: expected ~1.0, got {result}"

    @pytest.mark.parametrize("curve_name", [
        "straight_line", "gentle_curve", "moderate_curve", "right_angle",
        "strong_curve", "near_linear", "extreme_curve", "asymmetric",
    ])
    def test_precision(self, ref_data, curve_name):
        from arclength import arclen
        entry = next(e for e in ref_data if e["name"] == curve_name)
        curve = make_quad(entry["px"], entry["py"])
        expected = entry["arclen"]
        tol = entry["tolerance"]
        result = arclen(curve)

        if expected == 0:
            err = abs(result)
        else:
            err = abs(result - expected) / abs(expected)

        assert err < tol, (
            f"Quad '{curve_name}': rel_err={err:.2e} exceeds tol={tol:.0e}  "
            f"(result={result:.15e}, expected={expected:.15e})"
        )


# ===================================================================
# Test: Cubic arc length precision
# ===================================================================

class TestCubicArclen:
    @pytest.fixture
    def ref_data(self):
        return load_reference()["cubic"]

    def test_straight_line(self, ref_data):
        from arclength import arclen
        entry = next(e for e in ref_data if e["name"] == "straight_line")
        curve = make_cubic(entry["px"], entry["py"])
        result = arclen(curve)
        assert abs(result - 1.0) < 1e-10, \
            f"Cubic straight line: expected 1.0, got {result}"

    @pytest.mark.parametrize("curve_name", [
        "straight_line", "c_curve", "s_curve", "quarter_circle",
        "near_linear", "deep_curve", "asymmetric", "self_intersecting",
        "cusp_like", "gentle_s", "wide_arc", "extreme_curvature",
    ])
    def test_precision(self, ref_data, curve_name):
        from arclength import arclen
        entry = next(e for e in ref_data if e["name"] == curve_name)
        curve = make_cubic(entry["px"], entry["py"])
        expected = entry["arclen"]
        tol = entry["tolerance"]
        result = arclen(curve)

        if expected == 0:
            err = abs(result)
        else:
            err = abs(result - expected) / abs(expected)

        assert err < tol, (
            f"Cubic '{curve_name}': rel_err={err:.2e} exceeds tol={tol:.0e}  "
            f"(result={result:.15e}, expected={expected:.15e})"
        )


# ===================================================================
# Test: C-backed GL matches pure-Python GL
# ===================================================================

class TestCPythonConsistency:
    """Verify the C library produces the same results as pure-Python GL."""

    @pytest.mark.parametrize("curve_name", [
        "c_curve", "s_curve", "deep_curve", "self_intersecting",
        "extreme_curvature",
    ])
    def test_gl_consistency(self, curve_name):
        from arclength import cubic_arclen_gl
        ref = load_reference()["cubic"]
        entry = next(e for e in ref if e["name"] == curve_name)
        curve = make_cubic(entry["px"], entry["py"])

        c_result = cubic_arclen_gl(curve, order=16)
        py_result = python_gl_arclen(curve, order=16)

        assert abs(c_result - py_result) < 1e-14, (
            f"C vs Python GL mismatch on '{curve_name}': "
            f"C={c_result:.15e}, Python={py_result:.15e}"
        )

    @pytest.mark.parametrize("order", [4, 8, 16, 24])
    def test_orders(self, order):
        from arclength import cubic_arclen_gl
        curve = make_cubic([0, 0, 1, 1], [0, 1, 1, 0])
        c_result = cubic_arclen_gl(curve, order=order)
        py_result = python_gl_arclen(curve, order=order)
        assert abs(c_result - py_result) < 1e-13, (
            f"Order {order}: C={c_result:.15e}, Python={py_result:.15e}"
        )


# ===================================================================
# Test: Error bound conservatism
# ===================================================================

class TestErrorBound:
    """Verify the error bound never underestimates actual GL error."""

    @pytest.mark.parametrize("curve_name", [
        "c_curve", "s_curve", "quarter_circle", "deep_curve",
        "asymmetric", "self_intersecting", "cusp_like",
        "extreme_curvature", "wide_arc",
    ])
    def test_conservative_bound(self, curve_name):
        from arclength import estimate_cubic_error, cubic_arclen_gl
        ref = load_reference()["cubic"]
        entry = next(e for e in ref if e["name"] == curve_name)
        curve = make_cubic(entry["px"], entry["py"])
        expected = entry["arclen"]

        gl_result = cubic_arclen_gl(curve, order=16)
        actual_error = abs(gl_result - expected)
        estimated_error = estimate_cubic_error(curve)

        assert estimated_error >= 0, \
            f"Error bound must be non-negative, got {estimated_error}"
        assert estimated_error >= actual_error * 0.99, (
            f"Error bound underestimates on '{curve_name}': "
            f"estimated={estimated_error:.2e}, actual={actual_error:.2e}"
        )

    def test_low_error_for_gentle_curve(self):
        """Gentle curves should have small estimated error."""
        from arclength import estimate_cubic_error
        curve = make_cubic(
            [0, 0.3333, 0.6667, 1],
            [0, 0.001, 0.001, 0]
        )
        err = estimate_cubic_error(curve)
        assert err < 0.01, f"Gentle curve error too large: {err}"


# ===================================================================
# Test: Adaptive convergence
# ===================================================================

class TestAdaptiveConvergence:
    def test_converges_on_all_cubics(self):
        """Adaptive method must converge on every reference cubic."""
        from arclength import arclen_adaptive
        ref = load_reference()["cubic"]
        for entry in ref:
            curve = make_cubic(entry["px"], entry["py"])
            result = arclen_adaptive(curve, tolerance=1e-8)
            expected = entry["arclen"]
            err = abs(result - expected) / max(abs(expected), 1e-30)
            assert err < 1e-7, (
                f"Adaptive failed on '{entry['name']}': "
                f"rel_err={err:.2e}"
            )

    def test_tighter_tolerance(self):
        """Tighter tolerance should give more accurate results."""
        from arclength import arclen_adaptive
        curve = make_cubic([0, 0, 1, 1], [0, 1, 1, 0])
        r1 = arclen_adaptive(curve, tolerance=1e-4)
        r2 = arclen_adaptive(curve, tolerance=1e-10)
        expected = 2.0
        err1 = abs(r1 - expected)
        err2 = abs(r2 - expected)
        assert err2 <= err1 + 1e-15, (
            f"Tighter tolerance didn't improve: "
            f"err(1e-4)={err1:.2e}, err(1e-10)={err2:.2e}"
        )


# ===================================================================
# Test: Uses C library (not pure Python reimplementation)
# ===================================================================

class TestUsesClibrary:
    def test_arclength_module_uses_ctypes(self):
        """Verify arclength.py actually uses ctypes to load the C lib."""
        with open('/app/arclength.py', 'r') as f:
            source = f.read()
        assert 'ctypes' in source, \
            "arclength.py must use ctypes to call the C shared library"
        assert 'libquadrature' in source or 'quadrature' in source, \
            "arclength.py must reference the quadrature shared library"
