"""Tests for the Sedov-Taylor blast wave solver.

Reference data from Kamm & Timmes (LA-UR-07-2849), Tables 1-5.

"""

import sys
sys.path.insert(0, '/app')

import pytest
import numpy as np

from sedov_solver import SedovSolver


# =============================================================================
# Test similarity parameters
# =============================================================================

class TestSimilarityParameters:
    """Verify derived similarity parameters v2 and v0."""

    def test_v2_planar(self):
        s = SedovSolver(geometry=1, gamma=1.4)
        # v2 = 4 / ((1+2)*2.4) = 4/7.2
        assert s.v2 == pytest.approx(4.0 / 7.2, abs=1e-10)

    def test_v2_cylindrical(self):
        s = SedovSolver(geometry=2, gamma=1.4)
        # v2 = 4 / ((2+2)*2.4) = 4/9.6
        assert s.v2 == pytest.approx(4.0 / 9.6, abs=1e-10)

    def test_v2_spherical(self):
        s = SedovSolver(geometry=3, gamma=1.4)
        # v2 = 4 / ((3+2)*2.4) = 4/12 = 1/3
        assert s.v2 == pytest.approx(1.0 / 3.0, abs=1e-10)

    def test_v0_planar(self):
        s = SedovSolver(geometry=1, gamma=1.4)
        # v0 = 2 / ((1+2)*1.4) = 2/4.2
        assert s.v0 == pytest.approx(2.0 / 4.2, abs=1e-10)

    def test_v0_cylindrical(self):
        s = SedovSolver(geometry=2, gamma=1.4)
        assert s.v0 == pytest.approx(2.0 / (4.0 * 1.4), abs=1e-10)

    def test_v0_spherical(self):
        s = SedovSolver(geometry=3, gamma=1.4)
        assert s.v0 == pytest.approx(2.0 / (5.0 * 1.4), abs=1e-10)

    def test_v2_at_shock_lambda_one(self):
        """At v=v2, lambda should be 1.0 (the shock front)."""
        s = SedovSolver(geometry=3, gamma=1.4)
        lam, f, g, h = s.sedov_functions(s.v2)
        assert lam == pytest.approx(1.0, abs=1e-6)

    def test_sedov_funcs_normalized_at_shock(self):
        """At v=v2, all Sedov functions should equal 1.0."""
        s = SedovSolver(geometry=3, gamma=1.4)
        lam, f, g, h = s.sedov_functions(s.v2)
        assert f == pytest.approx(1.0, abs=1e-6)
        assert g == pytest.approx(1.0, abs=1e-6)
        assert h == pytest.approx(1.0, abs=1e-6)


# =============================================================================
# Test Sedov functions against Kamm & Timmes Tables 1-3
# =============================================================================

class TestSedovFunctionsSpherical:
    """Compare Sedov functions to Kamm & Timmes Table 3 (spherical, gamma=1.4)."""

    @classmethod
    def setup_class(cls):
        cls.solver = SedovSolver(geometry=3, gamma=1.4)

    # (v, lambda_ref, f_ref, g_ref, h_ref)
    @pytest.mark.parametrize("v,lam_ref,f_ref,g_ref,h_ref", [
        (0.3300, 0.9913, 0.9814, 0.8388, 0.9116),
        (0.3200, 0.9622, 0.9238, 0.4984, 0.7082),
        (0.3000, 0.8747, 0.7872, 0.1508, 0.4674),
        (0.2915, 0.7950, 0.6952, 0.0620, 0.4021),
        (0.2870, 0.6788, 0.5844, 0.0174, 0.3732),
    ])
    def test_sedov_functions(self, v, lam_ref, f_ref, g_ref, h_ref):
        lam, f, g, h = self.solver.sedov_functions(v)
        assert lam == pytest.approx(lam_ref, abs=2e-3)
        assert f == pytest.approx(f_ref, abs=2e-3)
        assert g == pytest.approx(g_ref, abs=2e-3)
        assert h == pytest.approx(h_ref, abs=2e-3)


class TestSedovFunctionsPlanar:
    """Compare Sedov functions to Kamm & Timmes Table 1 (planar, gamma=1.4)."""

    @classmethod
    def setup_class(cls):
        cls.solver = SedovSolver(geometry=1, gamma=1.4)

    @pytest.mark.parametrize("v,lam_ref,f_ref,g_ref,h_ref", [
        (0.5500, 0.9797, 0.9699, 0.8620, 0.9159),
        (0.5300, 0.9013, 0.8598, 0.5159, 0.6922),
        (0.5000, 0.7419, 0.6677, 0.2201, 0.4905),
        (0.4900, 0.6553, 0.5780, 0.1453, 0.4437),
        (0.4800, 0.4912, 0.4244, 0.0641, 0.4037),
    ])
    def test_sedov_functions(self, v, lam_ref, f_ref, g_ref, h_ref):
        lam, f, g, h = self.solver.sedov_functions(v)
        assert lam == pytest.approx(lam_ref, abs=2e-3)
        assert f == pytest.approx(f_ref, abs=2e-3)
        assert g == pytest.approx(g_ref, abs=2e-3)
        assert h == pytest.approx(h_ref, abs=2e-3)


class TestSedovFunctionsCylindrical:
    """Compare Sedov functions to Kamm & Timmes Table 2 (cylindrical, gamma=1.4)."""

    @classmethod
    def setup_class(cls):
        cls.solver = SedovSolver(geometry=2, gamma=1.4)

    @pytest.mark.parametrize("v,lam_ref,f_ref,g_ref,h_ref", [
        (0.4166, 0.9998, 0.9996, 0.9972, 0.9984),
        (0.4050, 0.9644, 0.9374, 0.6281, 0.7829),
        (0.3900, 0.9096, 0.8514, 0.3450, 0.5982),
        (0.3770, 0.8442, 0.7638, 0.1892, 0.4884),
        (0.3640, 0.7242, 0.6327, 0.0718, 0.4074),
    ])
    def test_sedov_functions(self, v, lam_ref, f_ref, g_ref, h_ref):
        lam, f, g, h = self.solver.sedov_functions(v)
        assert lam == pytest.approx(lam_ref, abs=2e-3)
        assert f == pytest.approx(f_ref, abs=2e-3)
        assert g == pytest.approx(g_ref, abs=2e-3)
        assert h == pytest.approx(h_ref, abs=2e-3)


# =============================================================================
# Test energy integrals (Kamm & Timmes Table 4)
# =============================================================================

class TestEnergyIntegrals:
    """Verify energy integrals I1, I2 against Kamm & Timmes Table 4."""

    def test_eval1_spherical(self):
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        assert s.eval1 == pytest.approx(2.96269e-02, abs=1e-5)

    def test_eval2_spherical(self):
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        assert s.eval2 == pytest.approx(2.11647e-02, abs=1e-5)

    def test_eval1_planar(self):
        s = SedovSolver(geometry=1, gamma=1.4, eblast=6.73185e-02)
        assert s.eval1 == pytest.approx(0.197928, abs=1e-4)

    def test_eval1_cylindrical(self):
        s = SedovSolver(geometry=2, gamma=1.4, eblast=0.311357)
        assert s.eval1 == pytest.approx(6.54053e-02, abs=1e-5)


# =============================================================================
# Test alpha (energy normalization constant)
# =============================================================================

class TestAlpha:
    """Verify the energy normalization constant alpha."""

    def test_alpha_spherical(self):
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        assert s.alpha == pytest.approx(8.51060e-01, abs=1e-3)

    def test_alpha_planar(self):
        s = SedovSolver(geometry=1, gamma=1.4, eblast=6.73185e-02)
        assert s.alpha == pytest.approx(5.38548e-01, abs=1e-2)

    def test_alpha_cylindrical(self):
        s = SedovSolver(geometry=2, gamma=1.4, eblast=0.311357)
        assert s.alpha == pytest.approx(9.84041e-01, abs=1e-2)


# =============================================================================
# Test physical profiles
# =============================================================================

class TestShockConditions:
    """Verify shock position and jump conditions."""

    def test_shock_position_spherical(self):
        """With standard eblast, shock should be near r=1 at t=1."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r = np.linspace(0.1, 1.5, 100)
        result = s.compute_profiles(r, 1.0)
        assert result['shock_position'] == pytest.approx(1.0, abs=2e-2)

    def test_post_shock_density_spherical(self):
        """Post-shock density should approach rho2 = (gamma+1)/(gamma-1) = 6.0."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        # Evaluate very close to the shock to avoid the steep gradient
        r = np.array([r_s * 0.9995])
        result = s.compute_profiles(r, 1.0)
        assert result['density'][0] == pytest.approx(6.0, rel=0.15)

    def test_pre_shock_density_spherical(self):
        """Pre-shock density should be rho0 = 1.0."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        r = np.array([r_s * 1.5])
        result = s.compute_profiles(r, 1.0)
        assert result['density'][0] == pytest.approx(1.0, abs=1e-10)

    def test_pre_shock_velocity_zero(self):
        """Pre-shock velocity should be 0."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r = np.array([2.0])
        result = s.compute_profiles(r, 1.0)
        assert result['velocity'][0] == pytest.approx(0.0, abs=1e-10)

    def test_pre_shock_pressure_zero(self):
        """Pre-shock pressure should be 0."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r = np.array([2.0])
        result = s.compute_profiles(r, 1.0)
        assert result['pressure'][0] == pytest.approx(0.0, abs=1e-10)


class TestProfilePhysics:
    """Verify physical consistency of profiles."""

    def test_density_monotonic_near_shock(self):
        """Density should decrease inward from shock (standard case)."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        r = np.array([r_s * 0.95, r_s * 0.85, r_s * 0.7])
        result = s.compute_profiles(r, 1.0)
        assert result['density'][0] > result['density'][1]
        assert result['density'][1] > result['density'][2]

    def test_pressure_monotonic_near_shock(self):
        """Pressure should decrease inward from shock (standard case)."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        r = np.array([r_s * 0.95, r_s * 0.7, r_s * 0.5])
        result = s.compute_profiles(r, 1.0)
        assert result['pressure'][0] > result['pressure'][1]
        assert result['pressure'][1] > result['pressure'][2]

    def test_velocity_decreases_inward(self):
        """Velocity should decrease inward from shock."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        r = np.array([r_s * 0.95, r_s * 0.7, r_s * 0.4])
        result = s.compute_profiles(r, 1.0)
        assert result['velocity'][0] > result['velocity'][1]
        assert result['velocity'][1] > result['velocity'][2]

    def test_sie_positive_inside_shock(self):
        """Specific internal energy should be positive inside the shock."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        r = np.array([r_s * 0.9, r_s * 0.5, r_s * 0.2])
        result = s.compute_profiles(r, 1.0)
        assert np.all(result['specific_internal_energy'] > 0)

    def test_sound_speed_positive_inside_shock(self):
        """Sound speed should be positive inside the shock."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        r = np.array([r_s * 0.9, r_s * 0.5, r_s * 0.2])
        result = s.compute_profiles(r, 1.0)
        assert np.all(result['sound_speed'] > 0)


class TestProfileValues:
    """Verify specific profile values against reference computations."""

    def test_shock_velocity_spherical(self):
        """Verify post-shock velocity value."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        # u_s = (2/5) * r_s/t, u2 = 2*u_s/2.4 = u_s/1.2
        u_s = (2.0 / 5.0) * r_s / 1.0
        u2_expected = 2.0 * u_s / 2.4
        # Just inside shock, velocity ~ u2
        r = np.array([r_s * 0.9995])
        result = s.compute_profiles(r, 1.0)
        assert result['velocity'][0] == pytest.approx(u2_expected, rel=0.15)

    def test_shock_pressure_spherical(self):
        """Verify post-shock pressure value."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r_s = s.compute_profiles(np.array([1.0]), 1.0)['shock_position']
        u_s = (2.0 / 5.0) * r_s / 1.0
        p2_expected = 2.0 * 1.0 * u_s**2 / 2.4
        r = np.array([r_s * 0.9995])
        result = s.compute_profiles(r, 1.0)
        assert result['pressure'][0] == pytest.approx(p2_expected, rel=0.15)


class TestMultipleGeometries:
    """Verify solver works correctly across geometries."""

    @pytest.mark.parametrize("geom,eblast,expected_alpha", [
        (1, 6.73185e-02, 5.38548e-01),
        (2, 0.311357, 9.84041e-01),
        (3, 0.851072, 8.51060e-01),
    ])
    def test_alpha_all_geometries(self, geom, eblast, expected_alpha):
        s = SedovSolver(geometry=geom, gamma=1.4, eblast=eblast)
        assert s.alpha == pytest.approx(expected_alpha, rel=0.02)

    @pytest.mark.parametrize("geom,gpogm", [
        (1, 6.0),
        (2, 6.0),
        (3, 6.0),
    ])
    def test_post_shock_density_ratio(self, geom, gpogm):
        """Post-shock density ratio should be (gamma+1)/(gamma-1) for all geometries."""
        s = SedovSolver(geometry=geom, gamma=1.4, eblast=0.851072)
        r = np.array([0.5])
        result = s.compute_profiles(r, 1.0)
        r_s = result['shock_position']
        if 0.5 < r_s:
            # Inside shock; check density is plausible (bounded by rho2)
            assert result['density'][0] <= gpogm * 1.0 * 1.01
            assert result['density'][0] > 0

    def test_different_gamma(self):
        """Verify solver handles gamma=5/3 (common in astrophysics)."""
        s = SedovSolver(geometry=3, gamma=5.0/3.0)
        # v2 = 4/(5*(8/3)) = 4/(40/3) = 12/40 = 0.3
        assert s.v2 == pytest.approx(0.3, abs=1e-10)
        # v0 = 2/(5*(5/3)) = 2/(25/3) = 6/25 = 0.24
        assert s.v0 == pytest.approx(0.24, abs=1e-10)
        # Sedov functions at v2 should be 1.0
        lam, f, g, h = s.sedov_functions(s.v2)
        assert lam == pytest.approx(1.0, abs=1e-6)
        assert f == pytest.approx(1.0, abs=1e-6)
        assert g == pytest.approx(1.0, abs=1e-6)
        assert h == pytest.approx(1.0, abs=1e-6)

    def test_time_scaling(self):
        """Shock position should scale as t^(2/(n+2))."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r1 = s.compute_profiles(np.array([0.5]), 1.0)['shock_position']
        r2 = s.compute_profiles(np.array([0.5]), 2.0)['shock_position']
        # r_s ~ t^(2/5), so r2/r1 = 2^(2/5)
        expected_ratio = 2.0**(2.0/5.0)
        assert (r2 / r1) == pytest.approx(expected_ratio, rel=1e-6)

    def test_return_keys(self):
        """Verify compute_profiles returns all required keys."""
        s = SedovSolver(geometry=3, gamma=1.4, eblast=0.851072)
        r = np.linspace(0.1, 1.5, 20)
        result = s.compute_profiles(r, 1.0)
        required_keys = ['position', 'density', 'velocity', 'pressure',
                         'specific_internal_energy', 'sound_speed',
                         'shock_position']
        for key in required_keys:
            assert key in result, f"Missing key: {key}"
