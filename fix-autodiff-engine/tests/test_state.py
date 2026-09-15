"""
Tests for dual autodiff system audit and repair task.

Verifies correctness of:
- Mini autodiff framework (VJP rules, JVP rules, backward pass, grad/deriv APIs)
- JAX custom_vjp functions (forward values, gradients, numerical stability)
- Cross-system gradient agreement
- Audit report and cross-validation report structure

"""

import json
import math
import os
import sys
import pytest

# Enable float64 before any JAX import
os.environ['JAX_ENABLE_X64'] = '1'

import jax
import jax.numpy as jnp

jax.config.update("jax_enable_x64", True)

sys.path.insert(0, '/app')
from numerics import log1pexp, logsumexp, sigmoid, safe_sqrt, huber_loss, log_cosh

TOL = 1e-5
STABILITY_TOL = 1e-2


# ============================================================
# Mini autodiff framework correctness
# ============================================================

class TestAutodiffFramework:
    def test_mul_grad_distinct(self):
        """grad(x -> x*3) at x=2 should be 3 — catches swapped VJP cotangents."""
        from autodiff import grad
        result = grad(lambda x: x * 3)(2.0)
        assert abs(result - 3.0) < 1e-10, \
            f"mul VJP: grad(x*3)(2) = {result}, expected 3.0"

    def test_div_grad_denominator(self):
        """d/dy(x/y) at (6,3) should be -2/3 — catches missing y^2 in quotient rule."""
        from autodiff import grad
        result = grad(lambda x, y: x / y, argnums=1)(6.0, 3.0)
        expected = -6.0 / 9.0
        assert abs(result - expected) < 1e-10, \
            f"div VJP: d/dy(6/3) = {result}, expected {expected}"

    def test_exp_grad(self):
        """grad(exp) at x=1 should be e — catches missing exp VJP rule."""
        from autodiff import grad, exp as ad_exp
        result = grad(lambda x: ad_exp(x))(1.0)
        assert abs(result - math.e) < 1e-10, \
            f"exp VJP: grad(exp)(1) = {result}, expected {math.e}"

    def test_sub_deriv_forward(self):
        """deriv(x -> 1-x) should be -1 — catches wrong sub JVP sign."""
        from autodiff import deriv
        result = deriv(lambda x: 1.0 - x)(2.0)
        assert abs(result - (-1.0)) < 1e-10, \
            f"sub JVP: deriv(1-x)(2) = {result}, expected -1.0"

    def test_grad_accumulation(self):
        """grad(x -> x*x) at x=3 should be 6 — catches gradient overwrite bug."""
        from autodiff import grad
        result = grad(lambda x: x * x)(3.0)
        assert abs(result - 6.0) < 1e-10, \
            f"accumulation: grad(x*x)(3) = {result}, expected 6.0"

    def test_complex_composition(self):
        """grad(x -> exp(x*x - x) / x) at x=2 = exp(2)*5/4 — integration test."""
        from autodiff import grad, exp as ad_exp
        def f(x):
            return ad_exp(x * x - x) / x
        result = grad(f)(2.0)
        expected = math.exp(2.0) * 5.0 / 4.0
        assert abs(result - expected) < 1e-8, \
            f"complex grad: got {result}, expected {expected}"

    def test_forward_reverse_agree(self):
        """Forward and reverse mode must agree on f(x) = (1-x)^2."""
        from autodiff import grad, deriv
        def f(x):
            return (1.0 - x) * (1.0 - x)
        for x_val in [0.0, 2.0, 3.0]:
            fwd = deriv(f)(x_val)
            rev = grad(f)(x_val)
            assert abs(fwd - rev) < 1e-10, \
                f"fwd/rev disagree at x={x_val}: fwd={fwd}, rev={rev}"


# ============================================================
# Forward value correctness (JAX numerics)
# ============================================================

class TestForwardValues:
    def test_log1pexp_moderate(self):
        x = jnp.float64(2.0)
        expected = math.log(1.0 + math.exp(2.0))
        assert jnp.allclose(log1pexp(x), expected, atol=TOL)

    def test_logsumexp_moderate(self):
        a, b = jnp.float64(1.0), jnp.float64(3.0)
        expected = math.log(math.exp(1.0) + math.exp(3.0))
        assert jnp.allclose(logsumexp(a, b), expected, atol=TOL)

    def test_sigmoid_at_zero(self):
        x = jnp.float64(0.0)
        assert jnp.allclose(sigmoid(x), 0.5, atol=TOL)

    def test_safe_sqrt_positive(self):
        x = jnp.float64(4.0)
        assert jnp.allclose(safe_sqrt(x), 2.0, atol=TOL)

    def test_huber_quadratic_value(self):
        x, delta = jnp.float64(0.5), jnp.float64(1.0)
        assert jnp.allclose(huber_loss(x, delta), 0.125, atol=TOL)

    def test_log_cosh_moderate(self):
        x = jnp.float64(1.0)
        expected = math.log(math.cosh(1.0))
        assert jnp.allclose(log_cosh(x), expected, atol=TOL)


# ============================================================
# Gradient correctness (against analytical derivatives)
# ============================================================

class TestGradientCorrectness:
    def test_log1pexp_grad(self):
        """d/dx log(1+exp(x)) = sigmoid(x) = 1/(1+exp(-x))"""
        for x_val in [0.0, 1.0, -2.0, 5.0]:
            x = jnp.float64(x_val)
            g = float(jax.grad(log1pexp)(x))
            expected = 1.0 / (1.0 + math.exp(-x_val))
            assert abs(g - expected) < TOL, \
                f"log1pexp grad wrong at x={x_val}: got {g}, expected {expected}"

    def test_logsumexp_grad_a(self):
        """d/da logsumexp(a,b) = exp(a)/(exp(a)+exp(b))"""
        a, b = jnp.float64(1.0), jnp.float64(2.0)
        ga = float(jax.grad(logsumexp, argnums=0)(a, b))
        expected = math.exp(1.0) / (math.exp(1.0) + math.exp(2.0))
        assert abs(ga - expected) < TOL

    def test_logsumexp_grad_b(self):
        """d/db logsumexp(a,b) = exp(b)/(exp(a)+exp(b))"""
        a, b = jnp.float64(1.0), jnp.float64(2.0)
        gb = float(jax.grad(logsumexp, argnums=1)(a, b))
        expected = math.exp(2.0) / (math.exp(1.0) + math.exp(2.0))
        assert abs(gb - expected) < TOL

    def test_sigmoid_grad(self):
        """d/dx sigmoid(x) = sigmoid(x) * (1 - sigmoid(x))"""
        for x_val in [0.0, 1.0, -1.0, 3.0]:
            x = jnp.float64(x_val)
            g = float(jax.grad(sigmoid)(x))
            s = 1.0 / (1.0 + math.exp(-x_val))
            expected = s * (1.0 - s)
            assert abs(g - expected) < TOL, \
                f"sigmoid grad wrong at x={x_val}: got {g}, expected {expected}"

    def test_safe_sqrt_grad_positive(self):
        """d/dx sqrt(x) = 0.5/sqrt(x) for x > 0"""
        for x_val in [1.0, 4.0, 9.0]:
            x = jnp.float64(x_val)
            g = float(jax.grad(safe_sqrt)(x))
            expected = 0.5 / math.sqrt(x_val)
            assert abs(g - expected) < TOL, \
                f"safe_sqrt grad wrong at x={x_val}: got {g}, expected {expected}"

    def test_safe_sqrt_grad_negative(self):
        """At x < 0, safe_sqrt is constant 0, so gradient must be 0."""
        x = jnp.float64(-1.0)
        g = float(jax.grad(safe_sqrt)(x))
        assert abs(g) < TOL, f"safe_sqrt grad at x=-1 should be 0, got {g}"

    def test_huber_quadratic_grad(self):
        """In quadratic region (|x|<=delta): d/dx = x"""
        x, delta = jnp.float64(0.5), jnp.float64(1.0)
        g = float(jax.grad(huber_loss)(x, delta))
        assert abs(g - 0.5) < TOL

    def test_huber_linear_positive_grad(self):
        """In linear region (|x|>delta): d/dx = delta * sign(x)"""
        x, delta = jnp.float64(3.0), jnp.float64(1.0)
        g = float(jax.grad(huber_loss)(x, delta))
        assert abs(g - 1.0) < TOL, f"huber linear grad at x=3: got {g}, expected 1.0"

    def test_huber_linear_negative_grad(self):
        """In linear region with negative x: d/dx = -delta"""
        x, delta = jnp.float64(-3.0), jnp.float64(1.0)
        g = float(jax.grad(huber_loss)(x, delta))
        assert abs(g - (-1.0)) < TOL, f"huber linear grad at x=-3: got {g}, expected -1.0"

    def test_log_cosh_grad(self):
        """d/dx log(cosh(x)) = tanh(x)"""
        for x_val in [0.0, 1.0, -1.0, 3.0]:
            x = jnp.float64(x_val)
            g = float(jax.grad(log_cosh)(x))
            expected = math.tanh(x_val)
            assert abs(g - expected) < TOL, \
                f"log_cosh grad wrong at x={x_val}: got {g}, expected {expected}"


# ============================================================
# Numerical stability for extreme inputs
# ============================================================

class TestNumericalStability:
    def test_log1pexp_large_positive(self):
        """log1pexp(750) should be ~750, grad ~1 (not overflow)"""
        x = jnp.float64(750.0)
        val = float(log1pexp(x))
        assert math.isfinite(val), f"log1pexp(750) not finite: {val}"
        assert abs(val - 750.0) < 1.0
        g = float(jax.grad(log1pexp)(x))
        assert math.isfinite(g), f"log1pexp grad(750) not finite: {g}"
        assert abs(g - 1.0) < STABILITY_TOL

    def test_log1pexp_large_negative(self):
        """log1pexp(-750) should be ~0, grad ~0"""
        x = jnp.float64(-750.0)
        val = float(log1pexp(x))
        assert math.isfinite(val)
        g = float(jax.grad(log1pexp)(x))
        assert math.isfinite(g)

    def test_logsumexp_large(self):
        """logsumexp(750, 749) should not overflow"""
        a, b = jnp.float64(750.0), jnp.float64(749.0)
        val = float(logsumexp(a, b))
        assert math.isfinite(val), f"logsumexp(750,749) not finite: {val}"
        expected = 750.0 + math.log(1.0 + math.exp(-1.0))
        assert abs(val - expected) < 0.1
        ga = float(jax.grad(logsumexp, argnums=0)(a, b))
        assert math.isfinite(ga), f"logsumexp grad_a not finite: {ga}"

    def test_safe_sqrt_near_zero(self):
        """safe_sqrt gradient at small positive x should be finite"""
        x = jnp.float64(1e-10)
        val = float(safe_sqrt(x))
        assert math.isfinite(val)
        g = float(jax.grad(safe_sqrt)(x))
        assert math.isfinite(g), f"safe_sqrt grad at 1e-10 not finite: {g}"

    def test_log_cosh_large_positive(self):
        """log_cosh(750) ~= 750-log(2), grad ~= 1"""
        x = jnp.float64(750.0)
        val = float(log_cosh(x))
        assert math.isfinite(val), f"log_cosh(750) not finite: {val}"
        expected = 750.0 - math.log(2.0)
        assert abs(val - expected) < 0.1
        g = float(jax.grad(log_cosh)(x))
        assert math.isfinite(g), f"log_cosh grad(750) not finite: {g}"
        assert abs(g - 1.0) < STABILITY_TOL

    def test_log_cosh_large_negative(self):
        """log_cosh(-750) ~= 750-log(2), grad ~= -1"""
        x = jnp.float64(-750.0)
        val = float(log_cosh(x))
        assert math.isfinite(val), f"log_cosh(-750) not finite: {val}"
        expected = 750.0 - math.log(2.0)
        assert abs(val - expected) < 0.1
        g = float(jax.grad(log_cosh)(x))
        assert math.isfinite(g), f"log_cosh grad(-750) not finite: {g}"
        assert abs(g - (-1.0)) < STABILITY_TOL


# ============================================================
# Cross-system gradient agreement (independent verification)
# ============================================================

class TestAutodiffCrossCheck:
    def test_log1pexp_cross(self):
        """log1pexp gradient: mini AD vs JAX must agree."""
        from autodiff import grad as ad_grad, exp as ad_exp, log as ad_log
        def log1pexp_ad(x):
            return ad_log(1.0 + ad_exp(x))
        for x_val in [0.0, 1.0, -2.0, 5.0]:
            ad_g = ad_grad(log1pexp_ad)(x_val)
            jax_g = float(jax.grad(log1pexp)(jnp.float64(x_val)))
            assert abs(ad_g - jax_g) < 1e-6, \
                f"log1pexp cross x={x_val}: AD={ad_g}, JAX={jax_g}"

    def test_sigmoid_cross(self):
        """sigmoid gradient: mini AD vs JAX must agree."""
        from autodiff import grad as ad_grad, exp as ad_exp
        def sigmoid_ad(x):
            return 1.0 / (1.0 + ad_exp(-x))
        for x_val in [0.0, 1.0, -1.0, 3.0]:
            ad_g = ad_grad(sigmoid_ad)(x_val)
            jax_g = float(jax.grad(sigmoid)(jnp.float64(x_val)))
            assert abs(ad_g - jax_g) < 1e-6, \
                f"sigmoid cross x={x_val}: AD={ad_g}, JAX={jax_g}"

    def test_log_cosh_cross(self):
        """log_cosh gradient: mini AD vs JAX must agree."""
        from autodiff import grad as ad_grad, exp as ad_exp, log as ad_log
        def log_cosh_ad(x):
            return ad_log((ad_exp(x) + ad_exp(-x)) / 2.0)
        for x_val in [0.0, 1.0, -1.0, 3.0]:
            ad_g = ad_grad(log_cosh_ad)(x_val)
            jax_g = float(jax.grad(log_cosh)(jnp.float64(x_val)))
            assert abs(ad_g - jax_g) < 1e-5, \
                f"log_cosh cross x={x_val}: AD={ad_g}, JAX={jax_g}"


# ============================================================
# Audit report validation
# ============================================================

class TestAuditReport:
    @pytest.fixture
    def report(self):
        report_path = '/app/audit_report.json'
        assert os.path.exists(report_path), "audit_report.json not found at /app/"
        with open(report_path) as f:
            return json.load(f)

    def test_report_has_autodiff_section(self, report):
        """Report must include autodiff_bugs section."""
        assert "autodiff_bugs" in report, "Report missing 'autodiff_bugs' key"

    def test_autodiff_bugs_diagnosed(self, report):
        """At least 3 distinct autodiff bugs must be identified."""
        bugs = report["autodiff_bugs"]
        assert len(bugs) >= 3, \
            f"Expected >= 3 autodiff bugs diagnosed, got {len(bugs)}: {list(bugs.keys())}"

    def test_report_has_numerics_section(self, report):
        """Report must have numerics_bugs with all 6 functions."""
        assert "numerics_bugs" in report, "Report missing 'numerics_bugs' key"
        for fn_name in ["log1pexp", "logsumexp", "sigmoid",
                        "safe_sqrt", "huber_loss", "log_cosh"]:
            assert fn_name in report["numerics_bugs"], \
                f"Missing {fn_name} in numerics_bugs"

    def test_log1pexp_diagnosed(self, report):
        """log1pexp must be diagnosed with gradient error and/or instability."""
        issues = [i.lower() for i in report["numerics_bugs"]["log1pexp"]["issues"]]
        issues_str = " ".join(issues)
        has_issue = any(kw in issues_str for kw in
            ["gradient", "incorrect", "wrong", "derivative", "exp(x)",
             "sigmoid", "stab", "overflow", "numer", "inf", "large"])
        assert has_issue, \
            f"log1pexp issues not properly identified: {issues}"

    def test_sigmoid_diagnosed(self, report):
        """sigmoid must be diagnosed with incorrect gradient."""
        issues = [i.lower() for i in report["numerics_bugs"]["sigmoid"]["issues"]]
        issues_str = " ".join(issues)
        assert any(kw in issues_str for kw in
            ["gradient", "incorrect", "wrong", "derivative", "formula",
             "(1-y)", "y*(1-y)", "missing"]), \
            f"sigmoid gradient issue not identified: {issues}"

    def test_log_cosh_diagnosed(self, report):
        """log_cosh must be diagnosed with missing custom_vjp or instability."""
        issues = [i.lower() for i in report["numerics_bugs"]["log_cosh"]["issues"]]
        issues_str = " ".join(issues)
        assert any(kw in issues_str for kw in
            ["missing", "custom_vjp", "custom vjp", "overflow", "stab",
             "no custom", "cosh", "inf", "nan"]), \
            f"log_cosh issue not identified: {issues}"

    def test_jaxpr_analysis_present(self, report):
        """Report must include jaxpr_analysis section with all functions."""
        assert "jaxpr_analysis" in report, "Missing jaxpr_analysis section"
        for fn_name in ["log1pexp", "logsumexp", "sigmoid",
                        "safe_sqrt", "huber_loss", "log_cosh"]:
            assert fn_name in report["jaxpr_analysis"], \
                f"Missing {fn_name} in jaxpr_analysis"

    def test_jaxpr_analysis_content(self, report):
        """Each jaxpr entry must have primitives and equation count."""
        for fn_name, entry in report["jaxpr_analysis"].items():
            prims = entry.get("primitives_used", entry.get("primitives", []))
            assert isinstance(prims, list) and len(prims) >= 1, \
                f"{fn_name} has empty or missing primitives list: {prims}"
            num_eqs = entry.get("num_equations", 0)
            assert isinstance(num_eqs, int) and num_eqs >= 1, \
                f"{fn_name} has invalid num_equations: {num_eqs}"


# ============================================================
# Cross-validation report
# ============================================================

class TestCrossValidation:
    @pytest.fixture
    def cv_report(self):
        cv_path = '/app/cross_validation.json'
        assert os.path.exists(cv_path), "cross_validation.json not found at /app/"
        with open(cv_path) as f:
            return json.load(f)

    def test_cv_has_functions(self, cv_report):
        """At least 3 functions should be cross-validated."""
        assert len(cv_report) >= 3, \
            f"Expected >= 3 cross-validated functions, got {len(cv_report)}"

    def test_cv_structure(self, cv_report):
        """Each entry should have test_points with expected fields."""
        for fn, data in cv_report.items():
            assert "test_points" in data, f"{fn} missing test_points"
            assert len(data["test_points"]) >= 2, f"{fn} has <2 test points"
            for pt in data["test_points"]:
                assert "x" in pt, f"{fn} test point missing 'x'"
                assert "jax_grad" in pt, f"{fn} test point missing 'jax_grad'"
                assert "autodiff_grad" in pt, f"{fn} test point missing 'autodiff_grad'"
                assert "match" in pt, f"{fn} test point missing 'match'"

    def test_cv_all_match(self, cv_report):
        """All cross-validated functions should show gradient agreement."""
        for fn, data in cv_report.items():
            assert data.get("all_match", False), \
                f"{fn} cross-validation failed: gradients do not match"
