
"""Tests for the reverse-mode AD framework.

Each test computes a gradient via the framework's grad() and compares it
against a centered finite-difference approximation.
"""
import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest

from autograd import grad, custom_logsumexp
import autograd.numpy as anp


# ---------- helpers ----------

def finite_diff_grad(fun, x, eps=1e-5):
    """Centered finite-difference gradient for scalar-valued fun."""
    x = np.asarray(x, dtype=np.float64)
    flat = x.ravel()
    g = np.zeros_like(flat)
    for i in range(len(flat)):
        flat_plus = flat.copy(); flat_plus[i] += eps
        flat_minus = flat.copy(); flat_minus[i] -= eps
        g[i] = (fun(flat_plus.reshape(x.shape)) - fun(flat_minus.reshape(x.shape))) / (2 * eps)
    return g.reshape(x.shape)


def check_grad(fun, x, rtol=1e-4, atol=1e-6):
    """Assert autograd gradient matches finite-difference gradient."""
    ag = grad(fun)(x)
    fd = finite_diff_grad(fun, x)
    np.testing.assert_allclose(ag, fd, rtol=rtol, atol=atol,
                               err_msg="Gradient mismatch for {}".format(fun.__name__))


# ---------- 1. Toposort / diamond graph tests ----------

class TestToposortDiamond:
    """Fan-out/fan-in graphs that require correct topological ordering."""

    def test_diamond_add(self):
        """f(x) = x + x => f'(x) = 2"""
        def f(x):
            return anp.sum(x + x)
        x = np.array([3.0, 4.0, 5.0])
        g = grad(f)(x)
        np.testing.assert_allclose(g, 2.0 * np.ones(3), rtol=1e-5)

    def test_diamond_mul_add(self):
        """f(x) = x*x + x  =>  f'(x) = 2x + 1"""
        def f(x):
            return anp.sum(x * x + x)
        x = np.array([1.0, 2.0, 3.0])
        g = grad(f)(x)
        np.testing.assert_allclose(g, 2 * x + 1, rtol=1e-5)

    def test_deep_diamond(self):
        """f(x) = (x^2 + x) * (x^2 - x)  =>  multiple fan-out/fan-in levels."""
        def f(x):
            a = x * x
            b = a + x
            c = a - x
            return anp.sum(b * c)
        x = np.array([2.0, 3.0])
        check_grad(f, x)

    def test_triple_reuse(self):
        """f(x) = x + x + x  =>  f'(x) = 3"""
        def f(x):
            return anp.sum(x + x + x)
        x = np.array([1.0, 2.0])
        g = grad(f)(x)
        np.testing.assert_allclose(g, 3.0 * np.ones(2), rtol=1e-5)


# ---------- 2. VJP: sum ----------

class TestSumVJP:
    def test_sum_full(self):
        def f(x): return anp.sum(x)
        x = np.array([1.0, 2.0, 3.0])
        check_grad(f, x)

    def test_sum_axis(self):
        def f(x): return anp.sum(anp.sum(x, axis=1) * np.array([1.0, 2.0]))
        x = np.random.RandomState(42).randn(2, 3)
        check_grad(f, x)

    def test_sum_keepdims(self):
        def f(x): return anp.sum(anp.sum(x, axis=0, keepdims=True))
        x = np.random.RandomState(43).randn(3, 4)
        check_grad(f, x)


# ---------- 3. VJP: matmul ----------

class TestMatmulVJP:
    def test_matmul_square(self):
        np.random.seed(50)
        A = np.random.randn(3, 3)
        def f(x): return anp.sum(anp.matmul(x, A))
        x = np.random.randn(3, 3)
        check_grad(f, x)

    def test_matmul_rect(self):
        np.random.seed(51)
        B = np.random.randn(4, 2)
        def f(x): return anp.sum(anp.matmul(x, B))
        x = np.random.randn(3, 4)
        check_grad(f, x)

    def test_matmul_both_args(self):
        """Differentiate w.r.t. first argument when second also varies."""
        np.random.seed(52)
        W = np.random.randn(4, 3)
        def f(x): return anp.sum(anp.matmul(x, W) ** 2)
        x = np.random.randn(2, 4)
        check_grad(f, x)


# ---------- 4. VJP: transpose ----------

class TestTransposeVJP:
    def test_transpose_basic(self):
        W = np.random.RandomState(60).randn(3, 2)
        def f(x): return anp.sum(anp.transpose(x) * W)
        x = np.random.RandomState(61).randn(2, 3)
        check_grad(f, x)

    def test_transpose_in_matmul(self):
        np.random.seed(62)
        W = np.random.randn(3, 3)
        def f(x): return anp.sum(anp.matmul(anp.transpose(x), W))
        x = np.random.RandomState(63).randn(3, 3)
        check_grad(f, x)


# ---------- 5. VJP: __getitem__ ----------

class TestGetitemVJP:
    def test_slice(self):
        def f(x): return anp.sum(x[1:3])
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        check_grad(f, x)

    def test_integer_index(self):
        def f(x): return x[2] * x[2]
        x = np.array([1.0, 2.0, 3.0, 4.0])
        g = grad(f)(x)
        expected = np.array([0.0, 0.0, 6.0, 0.0])
        np.testing.assert_allclose(g, expected, rtol=1e-5)

    def test_fancy_index(self):
        def f(x): return anp.sum(x[np.array([0, 2, 4])])
        x = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        check_grad(f, x)

    def test_2d_slice(self):
        def f(x): return anp.sum(x[:, 1])
        x = np.random.RandomState(70).randn(3, 4)
        check_grad(f, x)


# ---------- 6. VJP: logabsdet ----------

class TestLogabsdetVJP:
    def test_logabsdet_2x2(self):
        """log|det(A)| for a 2x2 diagonally-dominant matrix."""
        np.random.seed(100)
        A = np.random.randn(2, 2) + 3.0 * np.eye(2)
        def f(A): return anp.logabsdet(A)
        check_grad(f, A)

    def test_logabsdet_3x3(self):
        """log|det(A)| for a 3x3 diagonally-dominant matrix."""
        np.random.seed(101)
        A = np.random.randn(3, 3) + 4.0 * np.eye(3)
        def f(A): return anp.logabsdet(A)
        check_grad(f, A)

    def test_logabsdet_in_composition(self):
        """logabsdet composed with element-wise operations."""
        np.random.seed(102)
        A = np.random.randn(3, 3) + 5.0 * np.eye(3)
        def f(A): return anp.logabsdet(A) ** 2
        check_grad(f, A)


# ---------- 7. VJP: solve ----------

class TestSolveVJP:
    def test_solve_wrt_b(self):
        """Differentiate solve(A, b) w.r.t. b."""
        np.random.seed(110)
        A = np.random.randn(3, 3) + 4.0 * np.eye(3)
        b = np.random.randn(3)
        def f(b): return anp.sum(anp.solve(A, b))
        check_grad(f, b)

    def test_solve_wrt_A(self):
        """Differentiate solve(A, b) w.r.t. A."""
        np.random.seed(111)
        A = np.random.randn(3, 3) + 4.0 * np.eye(3)
        b = np.random.randn(3)
        def f(A): return anp.sum(anp.solve(A, b))
        check_grad(f, A)

    def test_solve_wrt_b_quadratic(self):
        """Quadratic in solve output to test gradient magnitude."""
        np.random.seed(112)
        A = np.random.randn(3, 3) + 5.0 * np.eye(3)
        b = np.random.randn(3)
        def f(b): return anp.sum(anp.solve(A, b) ** 2)
        check_grad(f, b)


# ---------- 8. VJP: custom_logsumexp (C-accelerated) ----------

class TestCustomLogsumexpVJP:
    def test_basic_1d(self):
        """C-based logsumexp on a 1-D input."""
        def f(x): return custom_logsumexp(x)
        x = np.array([1.0, 2.0, 3.0, 4.0])
        check_grad(f, x)

    def test_2d_input(self):
        """C-based logsumexp on a 2-D input (reduces all elements)."""
        def f(x): return custom_logsumexp(x)
        x = np.random.RandomState(120).randn(2, 3)
        check_grad(f, x)

    def test_logsumexp_composition(self):
        """Logsumexp composed with arithmetic."""
        def f(x): return custom_logsumexp(x * 2.0 + 1.0)
        x = np.array([0.5, 1.0, 1.5, 2.0])
        check_grad(f, x)


# ---------- 9. Composite / integration tests ----------

class TestComposite:
    def test_neural_net_layer(self):
        """Single dense layer with softmax-like normalization."""
        np.random.seed(80)
        W = np.random.randn(4, 3)
        b = np.random.randn(3)
        inp = np.random.randn(4)
        def f(x):
            h = anp.matmul(anp.reshape(x, (1, 4)), W) + b
            return anp.sum(anp.exp(h) / anp.sum(anp.exp(h)))
        check_grad(f, inp)

    def test_log_sum_exp_manual(self):
        """Manual logsumexp using framework primitives."""
        def f(x):
            return anp.log(anp.sum(anp.exp(x)))
        x = np.array([1.0, 2.0, 3.0, 0.5])
        check_grad(f, x)

    def test_norm(self):
        """L2 norm: sqrt(sum(x^2))"""
        def f(x):
            return anp.sqrt(anp.sum(x * x))
        x = np.array([3.0, 4.0])
        check_grad(f, x)

    def test_complex_composition(self):
        """Mix of reductions, trig, and arithmetic."""
        def f(x):
            a = anp.sin(x) * anp.cos(x)
            b = anp.sum(a, axis=0)
            return anp.sum(anp.sqrt(anp.abs(b) + 0.1))
        x = np.random.RandomState(90).randn(3, 4)
        check_grad(f, x)


# ---------- 10. Higher-order derivatives ----------

class TestHigherOrder:
    def test_grad_of_grad_poly(self):
        """f(x) = x^4, f'(x) = 4x^3, f''(x) = 12x^2"""
        def f(x): return x ** 4
        df = grad(f)
        ddf = grad(df)
        x = np.float64(2.0)
        np.testing.assert_allclose(df(x), 4 * 2.0**3, rtol=1e-5)
        np.testing.assert_allclose(ddf(x), 12 * 2.0**2, rtol=1e-5)

    def test_grad_of_grad_exp(self):
        """f(x) = exp(x), all derivatives are exp(x)"""
        def f(x): return anp.exp(x)
        df = grad(f)
        ddf = grad(df)
        dddf = grad(ddf)
        x = np.float64(1.0)
        expected = np.exp(1.0)
        np.testing.assert_allclose(df(x), expected, rtol=1e-5)
        np.testing.assert_allclose(ddf(x), expected, rtol=1e-5)
        np.testing.assert_allclose(dddf(x), expected, rtol=1e-5)

    def test_grad_of_grad_tanh(self):
        """Second derivative of tanh."""
        def f(x): return anp.tanh(x)
        ddf = grad(grad(f))
        x = np.float64(1.0)
        eps = 1e-5
        fd_ddf = (grad(f)(x + eps) - grad(f)(x - eps)) / (2 * eps)
        np.testing.assert_allclose(ddf(x), fd_ddf, rtol=1e-4)

    def test_grad_of_grad_sin(self):
        """f(x) = sin(x), f''(x) = -sin(x)"""
        def f(x): return anp.sin(x)
        ddf = grad(grad(f))
        x = np.float64(1.5)
        np.testing.assert_allclose(ddf(x), -np.sin(1.5), rtol=1e-4)
