"""
Constrained optimization problem suite.
Five problems of increasing difficulty (2D to 5D) with nonlinear
inequality constraints, evaluation budgets, and various landscape types.
"""
import numpy as np
from framework import ConstrainedOptimizationProblem



class Prob1(ConstrainedOptimizationProblem):
    """2D constrained product maximization with nonlinear constraints."""

    def __init__(self):
        self._xdim = 2
        self._cdim = 2
        self._prob = 'prob1'
        self._n = 300
        self._reset()

    def x0(self):
        return np.random.rand(2) * 2.0

    def _wrapped_f(self, x):
        return -x[0] * x[1] + 2.0 / (3.0 * np.sqrt(3.0))

    def _wrapped_g(self, x):
        return np.array([-x[1], -x[0]])

    def _wrapped_c(self, x):
        return np.array([
            x[0] + x[1]**2 - 1.0,
            -x[0] - x[1]
        ])


class Prob2(ConstrainedOptimizationProblem):
    """2D constrained Rosenbrock with both constraints active at optimum."""

    def __init__(self):
        self._xdim = 2
        self._cdim = 2
        self._prob = 'prob2'
        self._n = 300
        self._reset()

    def x0(self):
        return np.random.rand(2) * 2.0 - 1.0

    def _wrapped_f(self, x):
        return 100.0 * (x[1] - x[0]**2)**2 + (1.0 - x[0])**2

    def _wrapped_g(self, x):
        return np.array([
            2.0 * (-1.0 + x[0] + 200.0 * x[0]**3 - 200.0 * x[0] * x[1]),
            200.0 * (-x[0]**2 + x[1])
        ])

    def _wrapped_c(self, x):
        return np.array([
            (x[0] - 1.0)**3 - x[1] + 1.0,
            x[0] + x[1] - 2.0
        ])


class Prob3(ConstrainedOptimizationProblem):
    """3D linear objective on unit sphere constraint."""

    def __init__(self):
        self._xdim = 3
        self._cdim = 1
        self._prob = 'prob3'
        self._n = 400
        self._reset()

    def x0(self):
        b = 2.0 * np.array([1.0, -1.0, 0.0])
        a = -2.0 * np.array([1.0, -1.0, 0.0])
        return np.random.rand(3) * (b - a) + a

    def _wrapped_f(self, x):
        return x[0] - 2.0 * x[1] + x[2] + np.sqrt(6.0)

    def _wrapped_g(self, x):
        return np.array([1.0, -2.0, 1.0])

    def _wrapped_c(self, x):
        return np.array([x[0]**2 + x[1]**2 + x[2]**2 - 1.0])


class Prob4(ConstrainedOptimizationProblem):
    """4D constrained Powell function with mixed constraints."""

    def __init__(self):
        self._xdim = 4
        self._cdim = 3
        self._prob = 'prob4'
        self._n = 800
        self._reset()

    def x0(self):
        return np.clip(np.random.randn(4), -2.0, 2.0)

    def _wrapped_f(self, x):
        return ((x[0] + 10.0 * x[1])**2
                + 5.0 * (x[2] - x[3])**2
                + (x[1] - 2.0 * x[2])**4
                + 10.0 * (x[0] - x[3])**4)

    def _wrapped_g(self, x):
        return np.array([
            2.0 * (x[0] + 10.0 * x[1]) + 40.0 * (x[0] - x[3])**3,
            20.0 * (x[0] + 10.0 * x[1]) + 4.0 * (x[1] - 2.0 * x[2])**3,
            10.0 * (x[2] - x[3]) - 8.0 * (x[1] - 2.0 * x[2])**3,
            -10.0 * (x[2] - x[3]) - 40.0 * (x[0] - x[3])**3
        ])

    def _wrapped_c(self, x):
        return np.array([
            np.sum(x**2) - 4.0,
            x[0] + 2.0 * x[1] + x[2] + 2.0 * x[3] - 4.0,
            -x[0] + x[1] - x[2] + x[3] - 2.0
        ])


class Prob5(ConstrainedOptimizationProblem):
    """5D Rosenbrock chain with active sphere and sum constraints."""

    def __init__(self):
        self._xdim = 5
        self._cdim = 3
        self._prob = 'prob5'
        self._n = 1500
        self._reset()

    def x0(self):
        return np.clip(np.random.randn(5), -1.5, 1.5)

    def _wrapped_f(self, x):
        s = 0.0
        for i in range(4):
            s += 100.0 * (x[i + 1] - x[i]**2)**2 + (1.0 - x[i])**2
        return s

    def _wrapped_g(self, x):
        grad = np.zeros(5)
        for i in range(4):
            grad[i] += -400.0 * x[i] * (x[i + 1] - x[i]**2) - 2.0 * (1.0 - x[i])
            grad[i + 1] += 200.0 * (x[i + 1] - x[i]**2)
        return grad

    def _wrapped_c(self, x):
        return np.array([
            np.sum(x**2) - 4.0,
            np.sum(x) - 4.0,
            -np.sum(x) + 1.0
        ])


def get_all_problems():
    """Return list of all problem classes."""
    return [Prob1, Prob2, Prob3, Prob4, Prob5]
