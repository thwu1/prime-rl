"""
Black-Box Numerical Optimization Benchmark Suite

A property-controlled benchmark suite inspired by the GNBG (Generalized Numerical
Benchmark Generator) framework for evaluating global optimization algorithms.

The suite contains 12 problems spanning unimodal to multi-component multimodal
landscapes with controlled properties: conditioning, asymmetry, variable
interactions, basin shapes, and deceptiveness.

All problems are shifted and rotated to prevent exploitation of known optima.
Problems must be treated as black-box: use only the evaluate() interface.
"""


import numpy as np
from typing import Tuple, List, Optional


class Problem:
    """A black-box numerical optimization problem.

    Attributes:
        dim: Dimensionality of the search space.
        bounds: Tuple of (lower_bound, upper_bound) arrays.
        max_evals: Maximum number of function evaluations allowed.
        evals_used: Number of evaluations consumed so far.
        name: Human-readable problem identifier.
        fid: Integer problem ID (1-12).
        target_error: Error threshold for this problem.
    """

    def __init__(self, func, dim, bounds, max_evals, shift, rotation,
                 name, fid, target_error):
        self._func = func
        self.dim = dim
        self.bounds = bounds
        self.max_evals = max_evals
        self.__shift = shift
        self.__rotation = rotation
        self.name = name
        self.fid = fid
        self.target_error = target_error
        self.evals_used = 0
        self._best_value = float('inf')
        self._best_x = None

    def evaluate(self, x: np.ndarray) -> float:
        """Evaluate the objective function at point x.

        Args:
            x: A 1-D array of length self.dim.

        Returns:
            The function value at x. Returns +inf if budget is exhausted.
        """
        x = np.asarray(x, dtype=np.float64).ravel()
        if len(x) != self.dim:
            raise ValueError(
                f"Expected {self.dim}-dimensional input, got {len(x)}")
        if self.evals_used >= self.max_evals:
            return float('inf')
        self.evals_used += 1
        z = self.__rotation @ (x - self.__shift)
        val = float(self._func(z))
        if val < self._best_value:
            self._best_value = val
            self._best_x = x.copy()
        return val

    def get_best(self) -> Tuple[Optional[np.ndarray], float]:
        """Return (best_x, best_value) found so far."""
        if self._best_x is None:
            return None, float('inf')
        return self._best_x.copy(), self._best_value

    def _get_optimum(self) -> Tuple[np.ndarray, float]:
        """Internal method for test harness. Returns (optimum_pos, 0.0)."""
        return self.__shift.copy(), 0.0


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _random_rotation(dim: int, rng: np.random.Generator) -> np.ndarray:
    """Random orthogonal matrix via QR decomposition of a Gaussian matrix."""
    H = rng.standard_normal((dim, dim))
    Q, R = np.linalg.qr(H)
    Q = Q @ np.diag(np.sign(np.diag(R)))
    return Q


def _random_shift(dim: int, bounds: Tuple[np.ndarray, np.ndarray],
                  rng: np.random.Generator, margin: float = 0.2) -> np.ndarray:
    """Random shift vector within bounds, respecting a margin from edges."""
    lb, ub = bounds
    span = ub - lb
    return lb + margin * span + (1 - 2 * margin) * span * rng.random(dim)


# ---------------------------------------------------------------------------
# Benchmark functions  (all have global minimum 0 at z = 0)
# ---------------------------------------------------------------------------

def _sphere(z: np.ndarray) -> float:
    return float(np.sum(z ** 2))


def _ellipsoid(z: np.ndarray) -> float:
    d = len(z)
    weights = np.power(10.0, 6.0 * np.arange(d) / max(d - 1, 1))
    return float(np.sum(weights * z ** 2))


def _discus(z: np.ndarray) -> float:
    return float(1e6 * z[0] ** 2 + np.sum(z[1:] ** 2))


def _bent_cigar(z: np.ndarray) -> float:
    return float(z[0] ** 2 + 1e6 * np.sum(z[1:] ** 2))


def _rosenbrock(z: np.ndarray) -> float:
    # Shifted so that the Rosenbrock optimum (1,...,1) maps to z = 0
    w = z + 1.0
    return float(np.sum(100.0 * (w[1:] - w[:-1] ** 2) ** 2
                        + (w[:-1] - 1.0) ** 2))


def _ackley(z: np.ndarray) -> float:
    d = len(z)
    s1 = np.sum(z ** 2)
    s2 = np.sum(np.cos(2.0 * np.pi * z))
    return float(-20.0 * np.exp(-0.2 * np.sqrt(s1 / d))
                 - np.exp(s2 / d) + 20.0 + np.e)


def _rastrigin(z: np.ndarray) -> float:
    d = len(z)
    return float(10.0 * d + np.sum(z ** 2 - 10.0 * np.cos(2.0 * np.pi * z)))


def _schwefel(z: np.ndarray) -> float:
    # Normalised so f(0) = 0.  The standard Schwefel optimum at ~420.97 is
    # absorbed into the shift.
    c = 420.9687462275036
    x = z + c
    baseline = c * np.sin(np.sqrt(np.abs(c)))
    return float(np.sum(baseline - x * np.sin(np.sqrt(np.abs(x)))))


def _griewank(z: np.ndarray) -> float:
    d = len(z)
    return float(1.0 + np.sum(z ** 2) / 4000.0
                 - np.prod(np.cos(z / np.sqrt(np.arange(1, d + 1)))))


def _lunacek(z: np.ndarray) -> float:
    """Bi-Rastrigin (Lunacek) — deceptive two-basin landscape."""
    d = len(z)
    mu0 = 2.5
    s = 1.0 - 1.0 / (2.0 * np.sqrt(d + 20.0) - 8.2)
    mu1 = -np.sqrt(max(mu0 ** 2 - s, 0.0))
    delta = mu0 - mu1               # offset to the deceptive basin
    sum1 = np.sum(z ** 2)            # global basin centred at z = 0
    sum2 = d * s + np.sum((z + delta) ** 2)  # deceptive basin
    rastrigin = 10.0 * (d - np.sum(np.cos(2.0 * np.pi * z)))
    return float(min(sum1, sum2) + rastrigin)


def _katsuura(z: np.ndarray) -> float:
    d = len(z)
    powers = 2.0 ** np.arange(1, 33)                       # (32,)
    scaled = np.abs(np.outer(z, powers))                    # (d, 32)
    rounded = np.round(np.outer(z, powers))                 # (d, 32)
    inner = np.sum(np.abs(np.outer(z, powers) - rounded)
                   / powers[np.newaxis, :], axis=1)         # (d,)
    exponent = 10.0 / d ** 1.2
    product = np.prod((1.0 + np.arange(1, d + 1) * inner) ** exponent)
    return float(10.0 / d ** 2 * product - 10.0 / d ** 2)


def _schaffer_f7(z: np.ndarray) -> float:
    d = len(z)
    if d < 2:
        return 0.0
    s = np.sqrt(z[:-1] ** 2 + z[1:] ** 2)
    return float(
        (np.sum(np.sqrt(s) * (np.sin(50.0 * s ** 0.2) + 1.0))
         / (d - 1)) ** 2)


# ---------------------------------------------------------------------------
# Suite generator
# ---------------------------------------------------------------------------

_CONFIGS = [
    # (func,          name,               dim, budget,  threshold, bound_range)
    (_sphere,         "F01_Sphere",        10,   50_000, 1e-6,  100.0),
    (_ellipsoid,      "F02_Ellipsoid",     20,  200_000, 1e-3,  100.0),
    (_discus,         "F03_Discus",        20,  200_000, 1e-3,  100.0),
    (_bent_cigar,     "F04_BentCigar",     20,  200_000, 1e-3,  100.0),
    (_rosenbrock,     "F05_Rosenbrock",    10,  100_000, 1e-1,  100.0),
    (_ackley,         "F06_Ackley",        10,  100_000, 1e-1,   30.0),
    (_rastrigin,      "F07_Rastrigin",     10,  200_000, 5e-1,  100.0),
    (_schwefel,       "F08_Schwefel",      10,  200_000, 1.0,   100.0),
    (_griewank,       "F09_Griewank",      10,  100_000, 1e-1,  100.0),
    (_lunacek,        "F10_Lunacek",       10,  200_000, 5e-1,  100.0),
    (_katsuura,       "F11_Katsuura",      10,  200_000, 5.0,   100.0),
    (_schaffer_f7,    "F12_SchafferF7",    10,  200_000, 5e-1,  100.0),
]


def get_suite(seed: int = 0) -> List[Problem]:
    """Generate a suite of 12 benchmark problems.

    Args:
        seed: Master random seed for reproducible shift / rotation generation.

    Returns:
        A list of 12 Problem instances.
    """
    master_rng = np.random.default_rng(seed)
    problems: List[Problem] = []

    for fid, (func, name, dim, budget, threshold, bound_range) in enumerate(
            _CONFIGS, 1):
        rng = np.random.default_rng(master_rng.integers(0, 2 ** 63))
        lb = -bound_range * np.ones(dim)
        ub =  bound_range * np.ones(dim)
        bounds = (lb, ub)
        rotation = _random_rotation(dim, rng)
        shift = _random_shift(dim, bounds, rng, margin=0.2)
        problems.append(
            Problem(func, dim, bounds, budget, shift, rotation,
                    name, fid, threshold))

    return problems
