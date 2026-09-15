
"""
Physics-based and golden-value verification tests for the rectangular
prism gravity forward model.
"""

import json
import math
import sys

sys.path.insert(0, "/app")

import numpy as np
import pytest

from prism_gravity import (
    GRAVITATIONAL_CONST,
    kernel_e,
    kernel_ee,
    kernel_en,
    kernel_eu,
    kernel_n,
    kernel_nn,
    kernel_nu,
    kernel_pot,
    kernel_u,
    kernel_uu,
    prism_gravity,
    safe_atan2,
    safe_log,
)

# Load golden reference cases (task-specific DNA)
with open("/app/reference_cases.json") as _fh:
    _REF = json.load(_fh)
_CASES = _REF["cases"]

FIELDS = [
    "potential", "g_e", "g_n", "g_u",
    "g_ee", "g_nn", "g_uu", "g_en", "g_eu", "g_nu",
]


# ---------------------------------------------------------------------------
# Golden value tests — task-specific reference data
# ---------------------------------------------------------------------------
class TestGoldenAsymmetricIrregular:
    """Verify against reference case: asymmetric irregular prism, density=pi*1000."""

    CASE = _CASES["asymmetric_irregular"]

    @pytest.mark.parametrize("field", FIELDS)
    def test_field_value(self, field):
        c = self.CASE
        prism = tuple(c["prism"])
        obs = c["observation"]
        expected = c["expected"][field]
        result = prism_gravity(obs[0], obs[1], obs[2], prism, c["density"], field)
        assert result == pytest.approx(expected, rel=1e-10), (
            f"{field}: got {result:.15e}, expected {expected:.15e}"
        )


class TestGoldenThinElongated:
    """Verify against reference case: thin elongated prism, density=e*1000."""

    CASE = _CASES["thin_elongated"]

    @pytest.mark.parametrize("field", FIELDS)
    def test_field_value(self, field):
        c = self.CASE
        prism = tuple(c["prism"])
        obs = c["observation"]
        expected = c["expected"][field]
        result = prism_gravity(obs[0], obs[1], obs[2], prism, c["density"], field)
        if expected == 0.0:
            assert result == pytest.approx(0.0, abs=1e-25)
        else:
            assert result == pytest.approx(expected, rel=1e-10)


class TestGoldenDeepCubic:
    """Verify against reference case: deep cubic prism, density=sqrt(2)*1000."""

    CASE = _CASES["deep_cubic"]

    @pytest.mark.parametrize("field", FIELDS)
    def test_field_value(self, field):
        c = self.CASE
        prism = tuple(c["prism"])
        obs = c["observation"]
        expected = c["expected"][field]
        result = prism_gravity(obs[0], obs[1], obs[2], prism, c["density"], field)
        assert result == pytest.approx(expected, rel=1e-10)


class TestGoldenNearVertex:
    """Verify near-vertex numerical stability: observation at (0.001, 0.001, 0.001)."""

    CASE = _CASES["near_vertex"]

    @pytest.mark.parametrize("field", FIELDS)
    def test_field_value(self, field):
        c = self.CASE
        prism = tuple(c["prism"])
        obs = c["observation"]
        expected = c["expected"][field]
        result = prism_gravity(obs[0], obs[1], obs[2], prism, c["density"], field)
        assert result == pytest.approx(expected, rel=1e-9)


class TestGoldenSuperposition:
    """Verify superposition: full prism = left half + right half."""

    CASE = _CASES["superposition"]

    @pytest.mark.parametrize("field", FIELDS)
    def test_full_prism_value(self, field):
        c = self.CASE
        prism_full = tuple(c["prism_full"])
        obs = c["observation"]
        expected = c["expected_full"][field]
        result = prism_gravity(obs[0], obs[1], obs[2], prism_full, c["density"], field)
        assert result == pytest.approx(expected, rel=1e-10)

    @pytest.mark.parametrize("field", FIELDS)
    def test_additivity(self, field):
        c = self.CASE
        prism_left = tuple(c["prism_left"])
        prism_right = tuple(c["prism_right"])
        prism_full = tuple(c["prism_full"])
        obs = c["observation"]
        v_left = prism_gravity(obs[0], obs[1], obs[2], prism_left, c["density"], field)
        v_right = prism_gravity(obs[0], obs[1], obs[2], prism_right, c["density"], field)
        v_full = prism_gravity(obs[0], obs[1], obs[2], prism_full, c["density"], field)
        assert v_full == pytest.approx(v_left + v_right, rel=1e-11)


# ---------------------------------------------------------------------------
# Test safe_atan2
# ---------------------------------------------------------------------------
class TestSafeAtan2:
    def test_positive_y_zero_x(self):
        assert safe_atan2(1.0, 0.0) == pytest.approx(math.pi / 2)

    def test_negative_y_zero_x(self):
        assert safe_atan2(-1.0, 0.0) == pytest.approx(-math.pi / 2)

    def test_zero_y_zero_x(self):
        assert safe_atan2(0.0, 0.0) == 0.0

    def test_normal_positive(self):
        assert safe_atan2(3.0, 4.0) == pytest.approx(math.atan(3.0 / 4.0))

    def test_normal_negative_y(self):
        assert safe_atan2(-3.0, 4.0) == pytest.approx(math.atan(-3.0 / 4.0))


# ---------------------------------------------------------------------------
# Test safe_log
# ---------------------------------------------------------------------------
class TestSafeLog:
    def test_r_zero(self):
        assert safe_log(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_x_positive(self):
        x, y, z = 5.0, 3.0, 4.0
        r = math.sqrt(x**2 + y**2 + z**2)
        assert safe_log(x, y, z, r) == pytest.approx(math.log(x + r))

    def test_x_negative_yz_nonzero(self):
        x, y, z = -5.0, 3.0, 4.0
        r = math.sqrt(x**2 + y**2 + z**2)
        expected = math.log((y**2 + z**2) / (r - x))
        assert safe_log(x, y, z, r) == pytest.approx(expected)

    def test_x_negative_r_equals_abs_x(self):
        x = -3.0
        r = 3.0
        expected = -math.log(-2 * x)
        assert safe_log(x, 0.0, 0.0, r) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Laplace's equation: g_ee + g_nn + g_uu = 0 at external points
# ---------------------------------------------------------------------------
class TestLaplaceEquation:
    @pytest.mark.parametrize("obs_point", [
        (0.0, 0.0, 500.0),
        (1000.0, 2000.0, 300.0),
        (-500.0, 750.0, 1000.0),
        (300.0, -400.0, 250.0),
    ])
    def test_laplace(self, obs_point):
        prism = (-100.0, 100.0, -200.0, 200.0, -500.0, -100.0)
        density = 2670.0
        e, n, u = obs_point
        g_ee = prism_gravity(e, n, u, prism, density, "g_ee")
        g_nn = prism_gravity(e, n, u, prism, density, "g_nn")
        g_uu = prism_gravity(e, n, u, prism, density, "g_uu")
        assert g_ee + g_nn + g_uu == pytest.approx(0.0, abs=1e-20)


# ---------------------------------------------------------------------------
# Finite-difference: gradient matches numerical derivative of potential
# ---------------------------------------------------------------------------
class TestFiniteDifferenceGradient:
    PRISM = (-100.0, 100.0, -200.0, 200.0, -500.0, -100.0)
    DENSITY = 2670.0

    def _fd_gradient(self, e, n, u, coord_idx, delta=0.01):
        coords = [e, n, u]
        coords_plus = list(coords)
        coords_minus = list(coords)
        coords_plus[coord_idx] += delta
        coords_minus[coord_idx] -= delta
        v_plus = prism_gravity(*coords_plus, self.PRISM, self.DENSITY, "potential")
        v_minus = prism_gravity(*coords_minus, self.PRISM, self.DENSITY, "potential")
        return (v_plus - v_minus) / (2 * delta)

    def test_g_e(self):
        e, n, u = 300.0, 150.0, 200.0
        numerical = self._fd_gradient(e, n, u, 0)
        analytical = prism_gravity(e, n, u, self.PRISM, self.DENSITY, "g_e")
        assert analytical == pytest.approx(numerical, rel=1e-5)

    def test_g_n(self):
        e, n, u = 300.0, 150.0, 200.0
        numerical = self._fd_gradient(e, n, u, 1)
        analytical = prism_gravity(e, n, u, self.PRISM, self.DENSITY, "g_n")
        assert analytical == pytest.approx(numerical, rel=1e-5)

    def test_g_u(self):
        e, n, u = 300.0, 150.0, 200.0
        numerical = self._fd_gradient(e, n, u, 2)
        analytical = prism_gravity(e, n, u, self.PRISM, self.DENSITY, "g_u")
        assert analytical == pytest.approx(numerical, rel=1e-5)


# ---------------------------------------------------------------------------
# Finite-difference: tensor matches numerical derivative of gradient
# ---------------------------------------------------------------------------
class TestFiniteDifferenceTensor:
    PRISM = (-150.0, 50.0, -200.0, 100.0, -600.0, -200.0)
    DENSITY = 2900.0

    def _fd_tensor(self, e, n, u, grad_field, coord_idx, delta=0.1):
        coords = [e, n, u]
        coords_plus = list(coords)
        coords_minus = list(coords)
        coords_plus[coord_idx] += delta
        coords_minus[coord_idx] -= delta
        g_plus = prism_gravity(*coords_plus, self.PRISM, self.DENSITY, grad_field)
        g_minus = prism_gravity(*coords_minus, self.PRISM, self.DENSITY, grad_field)
        return (g_plus - g_minus) / (2 * delta)

    def test_g_ee(self):
        e, n, u = 200.0, -100.0, 300.0
        numerical = self._fd_tensor(e, n, u, "g_e", 0)
        analytical = prism_gravity(e, n, u, self.PRISM, self.DENSITY, "g_ee")
        assert analytical == pytest.approx(numerical, rel=1e-4)

    def test_g_nn(self):
        e, n, u = 200.0, -100.0, 300.0
        numerical = self._fd_tensor(e, n, u, "g_n", 1)
        analytical = prism_gravity(e, n, u, self.PRISM, self.DENSITY, "g_nn")
        assert analytical == pytest.approx(numerical, rel=1e-4)

    def test_g_en(self):
        e, n, u = 200.0, -100.0, 300.0
        numerical = self._fd_tensor(e, n, u, "g_e", 1)
        analytical = prism_gravity(e, n, u, self.PRISM, self.DENSITY, "g_en")
        assert analytical == pytest.approx(numerical, rel=1e-4)


# ---------------------------------------------------------------------------
# Bouguer convergence: large prism -> 2*pi*G*rho*h
# ---------------------------------------------------------------------------
class TestBouguerConvergence:
    def test_convergence_to_infinite_slab(self):
        density = 2670.0
        thickness = 100.0
        sizes = [1e3, 1e4, 1e5, 1e6, 1e7, 1e8]
        results = []
        for size in sizes:
            prism = (-size / 2, size / 2, -size / 2, size / 2, -thickness, 0.0)
            g_u = prism_gravity(0.0, 0.0, 0.0, prism, density, "g_u")
            results.append(g_u)

        expected = -2 * math.pi * GRAVITATIONAL_CONST * density * thickness

        errors = [abs(expected - r) for r in results]
        for i in range(1, len(errors)):
            assert errors[i] < errors[i - 1]

        assert results[-1] == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# Symmetry
# ---------------------------------------------------------------------------
class TestSymmetry:
    def test_symmetric_potential_cube(self):
        half = 100.0
        prism = (-half, half, -half, half, -half, half)
        density = 2670.0
        d = 500.0
        pots = []
        for point in [(d, 0, 0), (-d, 0, 0), (0, d, 0), (0, -d, 0), (0, 0, d), (0, 0, -d)]:
            pots.append(prism_gravity(*point, prism, density, "potential"))
        for p in pots[1:]:
            assert p == pytest.approx(pots[0], rel=1e-12)

    def test_gradient_antisymmetry(self):
        prism = (-100.0, 100.0, -100.0, 100.0, -100.0, 100.0)
        density = 2670.0
        d = 500.0
        g_e_pos = prism_gravity(d, 0, 0, prism, density, "g_e")
        g_e_neg = prism_gravity(-d, 0, 0, prism, density, "g_e")
        assert g_e_pos == pytest.approx(-g_e_neg, rel=1e-12)


# ---------------------------------------------------------------------------
# Tensor NaN on prism vertices
# ---------------------------------------------------------------------------
class TestTensorSingularity:
    def test_nan_on_vertex(self):
        prism = (-100.0, 100.0, -100.0, 100.0, -200.0, 0.0)
        density = 2670.0
        e, n, u = 100.0, 100.0, 0.0
        for field in ["g_ee", "g_nn", "g_uu", "g_en", "g_eu", "g_nu"]:
            val = prism_gravity(e, n, u, prism, density, field)
            assert np.isnan(val), f"{field} should be NaN on vertex, got {val}"

    def test_potential_finite_on_vertex(self):
        prism = (-100.0, 100.0, -100.0, 100.0, -200.0, 0.0)
        density = 2670.0
        e, n, u = 100.0, 100.0, 0.0
        pot = prism_gravity(e, n, u, prism, density, "potential")
        assert np.isfinite(pot)


# ---------------------------------------------------------------------------
# Field name dispatch
# ---------------------------------------------------------------------------
class TestFieldNames:
    def test_invalid_field_raises(self):
        prism = (-50.0, 50.0, -50.0, 50.0, -100.0, -10.0)
        with pytest.raises((ValueError, KeyError)):
            prism_gravity(0, 0, 100, prism, 2670.0, "invalid_field")
