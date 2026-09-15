
"""
Verification tests for the singular perturbation BVP solver.
Tests accuracy against known exact solutions and qualitative properties.
"""

import json
import numpy as np
import pytest
from pathlib import Path
from scipy.special import erf

RESULTS_FILE = Path("/app/results.json")
N_EVAL = 201


def log_cosh_stable(x):
    """Numerically stable computation of log(cosh(x))."""
    x = np.asarray(x, dtype=float)
    ax = np.abs(x)
    return ax + np.log1p(np.exp(-2.0 * ax)) - np.log(2.0)


# ---------------------------------------------------------------------------
# Exact solutions (not provided to the agent — used only for verification)
# ---------------------------------------------------------------------------

def exact_exponential_layer(t, eps):
    """bvpT2: z(t) = (1 - exp((t-1)/eps)) / (1 - exp(-1/eps))"""
    return (1.0 - np.exp((t - 1.0) / eps)) / (1.0 - np.exp(-1.0 / eps))


def exact_turning_point_shock(t, eps):
    """bvpT6: z(t) = cos(pi*t) + erf(t/sqrt(2*eps)) / erf(1/sqrt(2*eps))"""
    return np.cos(np.pi * t) + erf(t / np.sqrt(2.0 * eps)) / erf(1.0 / np.sqrt(2.0 * eps))


def exact_dual_boundary_layers(t, eps):
    """bvpT14: z(t) = cos(pi*t) + exp((t-1)/sqrt(eps)) + exp(-(t+1)/sqrt(eps))"""
    sq = np.sqrt(eps)
    return np.cos(np.pi * t) + np.exp((t - 1.0) / sq) + np.exp(-(t + 1.0) / sq)


def exact_nonlinear_corner(t, eps):
    """bvpT20: z(t) = 1 + eps * log(cosh((t - 0.745)/eps))"""
    return 1.0 + eps * log_cosh_stable((t - 0.745) / eps)


EXACT_SOLUTIONS = {
    "exponential_layer": exact_exponential_layer,
    "turning_point_shock": exact_turning_point_shock,
    "dual_boundary_layers": exact_dual_boundary_layers,
    "nonlinear_corner": exact_nonlinear_corner,
}

DOMAINS = {
    "exponential_layer": (0.0, 1.0),
    "turning_point_shock": (-1.0, 1.0),
    "dual_boundary_layers": (-1.0, 1.0),
    "nonlinear_corner": (0.0, 1.0),
    "double_corner_layers": (0.0, 1.0),
}

BC_LEFT = {
    "exponential_layer": lambda eps: 1.0,
    "turning_point_shock": lambda eps: -2.0,
    "dual_boundary_layers": lambda eps: np.exp(-2.0 / np.sqrt(eps)),
    "nonlinear_corner": lambda eps: 1.0 + eps * float(log_cosh_stable(0.745 / eps)),
    "double_corner_layers": lambda eps: -1.0 / 3.0,
}

BC_RIGHT = {
    "exponential_layer": lambda eps: 0.0,
    "turning_point_shock": lambda eps: 0.0,
    "dual_boundary_layers": lambda eps: np.exp(-2.0 / np.sqrt(eps)),
    "nonlinear_corner": lambda eps: 1.0 + eps * float(log_cosh_stable(0.255 / eps)),
    "double_corner_layers": lambda eps: 1.0 / 3.0,
}

EPSILONS = [0.1, 0.01, 0.001, 0.0001]
ALL_PROBLEMS = list(DOMAINS.keys())
EXACT_PROBLEMS = list(EXACT_SOLUTIONS.keys())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def results():
    assert RESULTS_FILE.exists(), f"Results file {RESULTS_FILE} not found"
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_all_problems_present(self, results):
        for prob in ALL_PROBLEMS:
            assert prob in results, f"Missing problem '{prob}' in results"

    def test_all_epsilons_present(self, results):
        for prob in ALL_PROBLEMS:
            for eps in EPSILONS:
                eps_str = str(eps)
                assert eps_str in results[prob], \
                    f"Missing eps={eps_str} for '{prob}'"

    def test_correct_array_lengths(self, results):
        for prob in ALL_PROBLEMS:
            for eps in EPSILONS:
                entry = results[prob][str(eps)]
                assert "t" in entry, f"Missing 't' key for '{prob}', eps={eps}"
                assert "y" in entry, f"Missing 'y' key for '{prob}', eps={eps}"
                assert len(entry["t"]) == N_EVAL, \
                    f"Expected {N_EVAL} t-values for '{prob}', eps={eps}, got {len(entry['t'])}"
                assert len(entry["y"]) == N_EVAL, \
                    f"Expected {N_EVAL} y-values for '{prob}', eps={eps}, got {len(entry['y'])}"

    def test_values_finite(self, results):
        for prob in ALL_PROBLEMS:
            for eps in EPSILONS:
                y = np.array(results[prob][str(eps)]["y"])
                assert np.all(np.isfinite(y)), \
                    f"Non-finite values for '{prob}', eps={eps}"

    def test_evaluation_grid(self, results):
        """Check that t values are evenly spaced on the correct domain."""
        for prob in ALL_PROBLEMS:
            a, b = DOMAINS[prob]
            t_expected = np.linspace(a, b, N_EVAL)
            for eps in EPSILONS:
                t = np.array(results[prob][str(eps)]["t"])
                assert np.allclose(t, t_expected, atol=1e-8), \
                    f"Evaluation grid mismatch for '{prob}', eps={eps}"


# ---------------------------------------------------------------------------
# Boundary condition tests
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    @pytest.mark.parametrize("prob", ALL_PROBLEMS)
    @pytest.mark.parametrize("eps", EPSILONS)
    def test_left_bc(self, results, prob, eps):
        y = np.array(results[prob][str(eps)]["y"])
        expected = BC_LEFT[prob](eps)
        assert abs(y[0] - expected) < 1e-3, \
            f"Left BC: got {y[0]:.8f}, expected {expected:.8f} for '{prob}', eps={eps}"

    @pytest.mark.parametrize("prob", ALL_PROBLEMS)
    @pytest.mark.parametrize("eps", EPSILONS)
    def test_right_bc(self, results, prob, eps):
        y = np.array(results[prob][str(eps)]["y"])
        expected = BC_RIGHT[prob](eps)
        assert abs(y[-1] - expected) < 1e-3, \
            f"Right BC: got {y[-1]:.8f}, expected {expected:.8f} for '{prob}', eps={eps}"


# ---------------------------------------------------------------------------
# Exact solution accuracy tests
# ---------------------------------------------------------------------------

class TestExactSolutions:
    @pytest.mark.parametrize("prob", EXACT_PROBLEMS)
    @pytest.mark.parametrize("eps", EPSILONS)
    def test_accuracy(self, results, prob, eps):
        entry = results[prob][str(eps)]
        t = np.array(entry["t"])
        y = np.array(entry["y"])
        y_exact = EXACT_SOLUTIONS[prob](t, eps)

        max_err = np.max(np.abs(y - y_exact))
        threshold = 5e-2

        assert max_err < threshold, \
            f"Max error {max_err:.6e} exceeds {threshold} for '{prob}', eps={eps}"


# ---------------------------------------------------------------------------
# Qualitative tests for double_corner_layers (no exact solution)
# ---------------------------------------------------------------------------

class TestDoubleCornerQualitative:
    @pytest.mark.parametrize("eps", EPSILONS)
    def test_bounded(self, results, eps):
        y = np.array(results["double_corner_layers"][str(eps)]["y"])
        assert np.max(np.abs(y)) < 5.0, \
            f"Solution unbounded for double_corner_layers, eps={eps}"

    @pytest.mark.parametrize("eps", EPSILONS)
    def test_overall_increase(self, results, eps):
        """Solution should increase overall from -1/3 to +1/3."""
        y = np.array(results["double_corner_layers"][str(eps)]["y"])
        assert y[-1] > y[0], \
            f"Solution not increasing overall for eps={eps}: y[0]={y[0]:.4f}, y[-1]={y[-1]:.4f}"

    @pytest.mark.parametrize("eps", [0.01, 0.001, 0.0001])
    def test_midpoint_near_zero(self, results, eps):
        """For small eps, solution near t=0.5 should be close to 0."""
        y = np.array(results["double_corner_layers"][str(eps)]["y"])
        mid_idx = N_EVAL // 2  # t = 0.5
        assert abs(y[mid_idx]) < 0.15, \
            f"Midpoint y({0.5})={y[mid_idx]:.4f} should be near 0 for eps={eps}"

    @pytest.mark.parametrize("eps", [0.001, 0.0001])
    def test_left_outer_solution(self, results, eps):
        """In the left outer region (t < 0.2), z ≈ t - 1/3."""
        entry = results["double_corner_layers"][str(eps)]
        t = np.array(entry["t"])
        y = np.array(entry["y"])

        mask = t < 0.2
        expected = t[mask] - 1.0 / 3.0
        err = np.max(np.abs(y[mask] - expected))
        assert err < 0.1, \
            f"Left outer solution error {err:.4f} for eps={eps}"

    @pytest.mark.parametrize("eps", [0.001, 0.0001])
    def test_right_outer_solution(self, results, eps):
        """In the right outer region (t > 0.8), z ≈ t - 2/3."""
        entry = results["double_corner_layers"][str(eps)]
        t = np.array(entry["t"])
        y = np.array(entry["y"])

        mask = t > 0.8
        expected = t[mask] - 2.0 / 3.0
        err = np.max(np.abs(y[mask] - expected))
        assert err < 0.1, \
            f"Right outer solution error {err:.4f} for eps={eps}"
