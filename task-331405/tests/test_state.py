
"""
Tests for reverse-mode automatic differentiation implementation.
Verifies grad and vjp produce correct gradients for various functions.
"""

import sys
sys.path.insert(0, '/app')
import numpy as np
import pytest


def finite_difference(f, x, eps=1e-5):
    """Compute gradient via central finite differences."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 0:
        return (f(float(x + eps)) - f(float(x - eps))) / (2 * eps)
    grad = np.zeros_like(x)
    for i in range(x.size):
        x_plus = x.copy()
        x_minus = x.copy()
        x_plus.flat[i] += eps
        x_minus.flat[i] -= eps
        grad.flat[i] = (f(x_plus) - f(x_minus)) / (2 * eps)
    return grad


class TestGradBasic:
    """Test basic gradient computations."""

    def test_grad_sin(self):
        from autodiff import grad
        from minijax import sin
        for x_val in [0.5, 1.0, 2.0, 3.0]:
            result = float(grad(sin)(x_val))
            expected = float(np.cos(x_val))
            assert abs(result - expected) < 1e-5, f"grad(sin)({x_val})={result}, expected {expected}"

    def test_grad_cos(self):
        from autodiff import grad
        from minijax import cos
        for x_val in [0.5, 1.0, 2.0]:
            result = float(grad(cos)(x_val))
            expected = float(-np.sin(x_val))
            assert abs(result - expected) < 1e-5, f"grad(cos)({x_val})={result}, expected {expected}"

    def test_grad_exp(self):
        from autodiff import grad
        from minijax import exp
        for x_val in [0.0, 1.0, -1.0, 2.0]:
            result = float(grad(exp)(x_val))
            expected = float(np.exp(x_val))
            assert abs(result - expected) < 1e-5, f"grad(exp)({x_val})={result}, expected {expected}"

    def test_grad_log(self):
        from autodiff import grad
        from minijax import log
        for x_val in [0.5, 1.0, 2.0, 5.0]:
            result = float(grad(log)(x_val))
            expected = 1.0 / x_val
            assert abs(result - expected) < 1e-5, f"grad(log)({x_val})={result}, expected {expected}"

    def test_grad_neg(self):
        from autodiff import grad
        from minijax import neg
        f = lambda x: neg(x)
        result = float(grad(f)(3.0))
        assert abs(result - (-1.0)) < 1e-5

    def test_grad_quadratic(self):
        from autodiff import grad
        f = lambda x: x * x
        result = float(grad(f)(3.0))
        assert abs(result - 6.0) < 1e-5, f"grad(x^2)(3)={result}, expected 6.0"

    def test_grad_cubic(self):
        from autodiff import grad
        f = lambda x: x * x * x
        result = float(grad(f)(2.0))
        expected = 12.0  # 3x^2 at x=2
        assert abs(result - expected) < 1e-5, f"grad(x^3)(2)={result}, expected {expected}"


class TestGradComposition:
    """Test gradient through function compositions (chain rule, product rule)."""

    def test_product_rule(self):
        from autodiff import grad
        from minijax import sin, cos
        f = lambda x: sin(x) * cos(x)
        x_val = 1.0
        result = float(grad(f)(x_val))
        expected = float(np.cos(x_val)**2 - np.sin(x_val)**2)
        assert abs(result - expected) < 1e-5

    def test_chain_rule_sin_of_sin(self):
        from autodiff import grad
        from minijax import sin, cos
        f = lambda x: sin(sin(x))
        x_val = 1.5
        result = float(grad(f)(x_val))
        expected = float(np.cos(np.sin(x_val)) * np.cos(x_val))
        assert abs(result - expected) < 1e-5

    def test_chain_rule_exp_neg_square(self):
        from autodiff import grad
        from minijax import exp, neg
        f = lambda x: exp(neg(x * x))
        x_val = 1.0
        result = float(grad(f)(x_val))
        fd = finite_difference(lambda v: float(np.exp(-v*v)), x_val)
        assert abs(result - fd) < 1e-4, f"grad(exp(-x^2))(1)={result}, fd={fd}"

    def test_complex_composition(self):
        from autodiff import grad
        from minijax import sin, cos
        f = lambda x: sin(x) * 2.0 + cos(x) * x
        x_val = 2.0
        result = float(grad(f)(x_val))
        fd = finite_difference(
            lambda v: float(np.sin(v) * 2.0 + np.cos(v) * v), x_val)
        assert abs(result - fd) < 1e-4

    def test_division(self):
        from autodiff import grad
        f = lambda x: x / (x + 1.0)
        x_val = 2.0
        result = float(grad(f)(x_val))
        # d/dx [x/(x+1)] = 1/(x+1)^2
        expected = 1.0 / (x_val + 1.0)**2
        assert abs(result - expected) < 1e-5

    def test_log_composition(self):
        from autodiff import grad
        from minijax import log
        f = lambda x: log(x * x)
        x_val = 3.0
        result = float(grad(f)(x_val))
        # d/dx log(x^2) = 2/x
        expected = 2.0 / x_val
        assert abs(result - expected) < 1e-5

    def test_mixed_expression(self):
        from autodiff import grad
        from minijax import sin, exp, log
        f = lambda x: log(exp(sin(x)) + 1.0)
        x_val = 0.5
        result = float(grad(f)(x_val))
        fd = finite_difference(
            lambda v: float(np.log(np.exp(np.sin(v)) + 1.0)), x_val)
        assert abs(result - fd) < 1e-4


class TestHigherOrderGrad:
    """Test higher-order derivatives (grad of grad)."""

    def test_grad_grad_sin(self):
        from autodiff import grad
        from minijax import sin
        f = grad(grad(sin))
        for x_val in [1.0, 2.0, 3.0]:
            result = float(f(x_val))
            expected = float(-np.sin(x_val))
            assert abs(result - expected) < 1e-4, \
                f"grad(grad(sin))({x_val})={result}, expected {expected}"

    def test_grad_grad_exp(self):
        from autodiff import grad
        from minijax import exp
        f = grad(grad(exp))
        x_val = 1.0
        result = float(f(x_val))
        expected = float(np.exp(x_val))
        assert abs(result - expected) < 1e-4

    def test_grad_grad_quadratic(self):
        from autodiff import grad
        f = lambda x: x * x * x  # x^3
        g = grad(grad(f))  # should be 6x
        result = float(g(2.0))
        assert abs(result - 12.0) < 1e-4

    def test_grad_grad_complex(self):
        from autodiff import grad
        from minijax import sin, cos
        f = lambda x: sin(x) * cos(x)
        g = grad(grad(f))
        x_val = 1.0
        result = float(g(x_val))
        # f(x) = sin(x)cos(x) = sin(2x)/2
        # f'(x) = cos(2x)
        # f''(x) = -2sin(2x)
        expected = float(-2 * np.sin(2 * x_val))
        assert abs(result - expected) < 1e-3


class TestVJP:
    """Test VJP function directly."""

    def test_vjp_sin(self):
        from autodiff import vjp
        from minijax import sin
        y, f_vjp = vjp(sin, 3.0)
        assert abs(float(y) - float(np.sin(3.0))) < 1e-5
        ct, = f_vjp(1.0)
        assert abs(float(ct) - float(np.cos(3.0))) < 1e-5

    def test_vjp_mul(self):
        from autodiff import vjp
        f = lambda x: x * x
        y, f_vjp = vjp(f, 4.0)
        assert abs(float(y) - 16.0) < 1e-5
        ct, = f_vjp(1.0)
        assert abs(float(ct) - 8.0) < 1e-5

    def test_vjp_scaled_cotangent(self):
        from autodiff import vjp
        from minijax import sin
        y, f_vjp = vjp(sin, 2.0)
        ct, = f_vjp(3.0)
        expected = 3.0 * float(np.cos(2.0))
        assert abs(float(ct) - expected) < 1e-5


class TestArrayGrad:
    """Test gradient with array-valued inputs."""

    def test_grad_reduce_sum_square(self):
        from autodiff import grad
        from minijax import reduce_sum
        f = lambda x: reduce_sum(x * x)
        x = np.array([1.0, 2.0, 3.0])
        result = grad(f)(x)
        expected = 2 * x
        np.testing.assert_allclose(result, expected, atol=1e-5)

    def test_grad_dot_product(self):
        from autodiff import grad
        from minijax import reduce_sum
        w = np.array([1.0, -1.0, 2.0])
        f = lambda x: reduce_sum(x * w)
        x = np.array([3.0, 4.0, 5.0])
        result = grad(f)(x)
        np.testing.assert_allclose(result, w, atol=1e-5)


class TestFiniteDifferences:
    """Cross-validate gradients against finite differences for complex functions."""

    def _check_grad(self, f_mini, f_numpy, x_val):
        from autodiff import grad
        result = float(grad(f_mini)(x_val))
        fd = finite_difference(lambda v: float(f_numpy(v)), x_val)
        assert abs(result - fd) < 1e-4, \
            f"grad={result}, finite_diff={fd}, diff={abs(result-fd)}"

    def test_fd_sin_squared(self):
        from minijax import sin
        self._check_grad(lambda x: sin(x) * sin(x),
                        lambda x: np.sin(x)**2, 1.5)

    def test_fd_exp_of_neg(self):
        from minijax import exp, neg
        self._check_grad(lambda x: exp(neg(x)),
                        lambda x: np.exp(-x), 2.0)

    def test_fd_log_of_exp(self):
        from minijax import log, exp
        self._check_grad(lambda x: log(exp(x) + 1.0),
                        lambda x: np.log(np.exp(x) + 1.0), 0.5)

    def test_fd_ratio(self):
        from minijax import sin, cos
        self._check_grad(lambda x: sin(x) / (cos(x) + 2.0),
                        lambda x: np.sin(x) / (np.cos(x) + 2.0), 1.0)
