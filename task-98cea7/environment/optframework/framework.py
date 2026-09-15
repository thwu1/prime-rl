"""
Base classes for constrained optimization problems.
Provides evaluation counting and function wrapping.
"""
import numpy as np



class ConstrainedOptimizationProblem:
    """
    Base class for constrained optimization problems.

    Interface:
        f(x) -> float:    objective function (costs 1 evaluation)
        g(x) -> ndarray:  gradient of f (costs 2 evaluations)
        c(x) -> ndarray:  constraint values (costs 1 evaluation)
        count() -> int:   current evaluation count
        n -> int:         evaluation budget
        xdim -> int:      dimension of decision variable
        cdim -> int:      number of constraints
        prob -> str:      problem identifier

    Constraints are of the form c_i(x) <= 0 for all i.
    """

    @property
    def xdim(self):
        return self._xdim

    @property
    def cdim(self):
        return self._cdim

    @property
    def prob(self):
        return self._prob

    @property
    def n(self):
        return self._n

    def _reset(self):
        self._ctr = 0

    def count(self):
        return self._ctr

    def nolimit(self):
        self._n = float('inf')

    def x0(self):
        return np.random.randn(self.xdim)

    def f(self, x):
        assert isinstance(x, np.ndarray) and x.ndim == 1
        self._ctr += 1
        return self._wrapped_f(x)

    def g(self, x):
        assert isinstance(x, np.ndarray) and x.ndim == 1
        self._ctr += 2
        return self._wrapped_g(x)

    def c(self, x):
        assert isinstance(x, np.ndarray) and x.ndim == 1
        self._ctr += 1
        return self._wrapped_c(x)

    def _wrapped_f(self, x):
        raise NotImplementedError

    def _wrapped_g(self, x):
        raise NotImplementedError

    def _wrapped_c(self, x):
        raise NotImplementedError
