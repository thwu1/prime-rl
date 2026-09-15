
"""Tests for the Sedov blast wave solver.

Verifies similarity exponents, similarity functions, energy integrals,
post-shock Rankine-Hugoniot conditions, and full radial profiles against
Kamm & Timmes (2007) reference data (Tables 1-4).
"""

import sys
sys.path.insert(0, '/app')

import pytest
import numpy as np


class TestSedovExponents:
    """Verify similarity exponents for known parameter combinations.

    These are exact algebraic values derivable from the Kamm equations,
    so tolerances are set to machine precision.
    """

    def test_spherical_gamma14_a0(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(3, 1.4, 0.0)
        # a0 = 2/xg2 = 2/5 = 0.4
        assert exps['a0'] == pytest.approx(0.4, abs=1e-10)

    def test_spherical_gamma14_v2(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(3, 1.4, 0.0)
        # v2 = 4/(xg2*gamp1) = 4/(5*2.4) = 1/3
        assert exps['v2'] == pytest.approx(1.0 / 3.0, abs=1e-10)

    def test_spherical_gamma14_v0(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(3, 1.4, 0.0)
        # v0 = 2/(xg2*gamma) = 2/(5*1.4) = 2/7
        assert exps['v0'] == pytest.approx(2.0 / 7.0, abs=1e-10)

    def test_planar_gamma14_a0(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(1, 1.4, 0.0)
        # a0 = 2/xg2 = 2/3
        assert exps['a0'] == pytest.approx(2.0 / 3.0, abs=1e-10)

    def test_planar_gamma14_v2(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(1, 1.4, 0.0)
        # v2 = 4/(3*2.4)
        assert exps['v2'] == pytest.approx(4.0 / (3.0 * 2.4), abs=1e-10)

    def test_cylindrical_gamma14_a0(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(2, 1.4, 0.0)
        # a0 = 2/xg2 = 2/4 = 0.5
        assert exps['a0'] == pytest.approx(0.5, abs=1e-10)

    def test_cylindrical_gamma14_v2(self):
        from sedov import compute_sedov_exponents
        exps = compute_sedov_exponents(2, 1.4, 0.0)
        # v2 = 4/(4*2.4) = 5/12
        assert exps['v2'] == pytest.approx(5.0 / 12.0, abs=1e-10)

    def test_spherical_gamma53_gpogm(self):
        from sedov import compute_sedov_exponents
        gamma = 5.0 / 3.0
        exps = compute_sedov_exponents(3, gamma, 0.0)
        # gpogm = (gamma+1)/(gamma-1) = (8/3)/(2/3) = 4
        assert exps['gpogm'] == pytest.approx(4.0, abs=1e-10)

    def test_spherical_gamma53_v2(self):
        from sedov import compute_sedov_exponents
        gamma = 5.0 / 3.0
        exps = compute_sedov_exponents(3, gamma, 0.0)
        # v2 = 4/(5 * 8/3) = 12/40 = 0.3
        assert exps['v2'] == pytest.approx(0.3, abs=1e-10)


class TestSedovFunctions:
    """Verify Sedov similarity functions against Kamm & Timmes reference tables.

    Reference: Kamm & Timmes (2007) Tables 1-3.
    Each row gives (v, lambda, f, g, h) for gamma=1.4, omega=0.
    """

    def test_spherical_v0p33(self):
        """Table 3, row 1: v=0.33, lambda=0.9913"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.33, 3, 1.4, 0.0)
        assert lam == pytest.approx(0.9913, abs=1e-3)
        assert f == pytest.approx(0.9814, abs=1e-3)
        assert g == pytest.approx(0.8388, abs=1e-3)
        assert h == pytest.approx(0.9116, abs=1e-3)

    def test_spherical_v0p32(self):
        """Table 3, row 3: v=0.32, lambda=0.9622"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.32, 3, 1.4, 0.0)
        assert lam == pytest.approx(0.9622, abs=1e-3)
        assert f == pytest.approx(0.9238, abs=1e-3)
        assert g == pytest.approx(0.4984, abs=1e-3)
        assert h == pytest.approx(0.7082, abs=1e-3)

    def test_spherical_v0p30(self):
        """Table 3, row 6: v=0.30, lambda=0.8747"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.30, 3, 1.4, 0.0)
        assert lam == pytest.approx(0.8747, abs=1e-3)
        assert f == pytest.approx(0.7872, abs=1e-3)
        assert g == pytest.approx(0.1508, abs=1e-3)
        assert h == pytest.approx(0.4674, abs=1e-3)

    def test_spherical_v0p286(self):
        """Table 3, deep interior: v=0.286, lambda~0.6788"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.287, 3, 1.4, 0.0)
        assert lam == pytest.approx(0.6788, abs=2e-2)
        assert g == pytest.approx(0.0174, abs=5e-3)

    def test_planar_v0p55(self):
        """Table 1, row 1: v=0.55, lambda=0.9797"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.55, 1, 1.4, 0.0)
        assert lam == pytest.approx(0.9797, abs=1e-3)
        assert f == pytest.approx(0.9699, abs=1e-3)
        assert g == pytest.approx(0.8620, abs=1e-3)
        assert h == pytest.approx(0.9159, abs=1e-3)

    def test_planar_v0p50(self):
        """Table 1, row 6: v=0.50, lambda=0.7419"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.50, 1, 1.4, 0.0)
        assert lam == pytest.approx(0.7419, abs=1e-3)
        assert f == pytest.approx(0.6677, abs=1e-3)
        assert g == pytest.approx(0.2201, abs=1e-3)
        assert h == pytest.approx(0.4905, abs=1e-3)

    def test_cylindrical_v0p41(self):
        """Table 2, row 2: v=0.41, lambda=0.9802"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.41, 2, 1.4, 0.0)
        assert lam == pytest.approx(0.9802, abs=1e-3)
        assert f == pytest.approx(0.9645, abs=1e-3)
        assert g == pytest.approx(0.7651, abs=1e-3)
        assert h == pytest.approx(0.8658, abs=1e-3)

    def test_cylindrical_v0p39(self):
        """Table 2, row 6: v=0.39, lambda=0.9096"""
        from sedov import compute_sedov_functions
        lam, dlamdv, f, g, h = compute_sedov_functions(0.39, 2, 1.4, 0.0)
        assert lam == pytest.approx(0.9096, abs=1e-3)
        assert f == pytest.approx(0.8514, abs=1e-3)
        assert g == pytest.approx(0.3450, abs=1e-3)
        assert h == pytest.approx(0.5982, abs=1e-3)

    def test_at_shock_boundary_all_geometries(self):
        """At v=v2 (the shock), all similarity functions equal 1.0."""
        from sedov import compute_sedov_exponents, compute_sedov_functions
        for geom in [1, 2, 3]:
            exps = compute_sedov_exponents(geom, 1.4, 0.0)
            v2 = exps['v2']
            lam, dlamdv, f, g, h = compute_sedov_functions(
                v2, geom, 1.4, 0.0)
            assert lam == pytest.approx(1.0, abs=1e-6), \
                f"lambda at v2 for geom={geom}"
            assert f == pytest.approx(1.0, abs=1e-6), \
                f"f at v2 for geom={geom}"
            assert g == pytest.approx(1.0, abs=1e-6), \
                f"g at v2 for geom={geom}"
            assert h == pytest.approx(1.0, abs=1e-6), \
                f"h at v2 for geom={geom}"

    def test_dlamdv_positive(self):
        """dlambda/dv should be positive in [v0, v2] (lambda increases with v)."""
        from sedov import compute_sedov_exponents, compute_sedov_functions
        for geom in [1, 2, 3]:
            exps = compute_sedov_exponents(geom, 1.4, 0.0)
            v0 = exps['v0']
            v2 = exps['v2']
            v_mid = 0.5 * (v0 + v2)
            _, dlamdv, _, _, _ = compute_sedov_functions(
                v_mid, geom, 1.4, 0.0)
            assert dlamdv > 0, \
                f"dlamdv should be > 0 for geom={geom}, got {dlamdv}"


class TestEnergyIntegrals:
    """Verify energy integrals against Kamm & Timmes Table 4.

    Reference values for gamma=1.4, omega=0, all three geometries.
    """

    def test_spherical_eval1(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(3, 1.4, 0.0)
        assert e1 == pytest.approx(2.96269e-02, abs=1e-5)

    def test_spherical_eval2(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(3, 1.4, 0.0)
        assert e2 == pytest.approx(2.11647e-02, abs=1e-5)

    def test_spherical_alpha(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(3, 1.4, 0.0)
        assert alpha == pytest.approx(8.51060e-01, abs=1e-3)

    def test_cylindrical_eval1(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(2, 1.4, 0.0)
        assert e1 == pytest.approx(6.54053e-02, abs=1e-5)

    def test_cylindrical_eval2(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(2, 1.4, 0.0)
        assert e2 == pytest.approx(4.95650e-02, abs=1e-3)

    def test_cylindrical_alpha(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(2, 1.4, 0.0)
        assert alpha == pytest.approx(9.84041e-01, abs=1e-3)

    def test_planar_eval1(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(1, 1.4, 0.0)
        assert e1 == pytest.approx(0.197928, abs=1e-5)

    def test_planar_eval2(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(1, 1.4, 0.0)
        assert e2 == pytest.approx(0.175834, abs=1e-3)

    def test_planar_alpha(self):
        from sedov import compute_energy_integrals
        e1, e2, alpha = compute_energy_integrals(1, 1.4, 0.0)
        assert alpha == pytest.approx(0.538548, abs=1e-3)

    def test_integrals_positive(self):
        """Both energy integrals must be positive for all geometries."""
        from sedov import compute_energy_integrals
        for geom in [1, 2, 3]:
            e1, e2, alpha = compute_energy_integrals(geom, 1.4, 0.0)
            assert e1 > 0, f"eval1 for geom={geom}"
            assert e2 > 0, f"eval2 for geom={geom}"
            assert alpha > 0, f"alpha for geom={geom}"


class TestPostShock:
    """Verify post-shock Rankine-Hugoniot conditions.

    Reference: Kamm & Timmes (2007) equations 13-18 for the spherical case.
    """

    def test_spherical_rho2(self):
        """Post-shock density = (gamma+1)/(gamma-1) * rho0 = 6.0"""
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
        ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
        assert ps['rho2'] == pytest.approx(6.0, abs=1e-2)

    def test_spherical_u2(self):
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
        ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
        assert ps['u2'] == pytest.approx(3.33333e-1, abs=1e-3)

    def test_spherical_p2(self):
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
        ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
        assert ps['p2'] == pytest.approx(1.33333e-1, abs=1e-3)

    def test_spherical_e2(self):
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
        ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
        assert ps['e2'] == pytest.approx(5.5555e-2, abs=1e-3)

    def test_spherical_cs2(self):
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
        ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
        assert ps['cs2'] == pytest.approx(1.76383e-1, abs=1e-3)

    def test_spherical_r2(self):
        """Shock position near r=1.0 for the standard test case."""
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(3, 1.4, 0.0)
        ps = compute_postshock(3, 1.4, 1.0, 0.851072, alpha, 1.0)
        assert ps['r2'] == pytest.approx(1.0, abs=2e-2)

    def test_planar_r2(self):
        """Planar shock near r=0.5."""
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(1, 1.4, 0.0)
        ps = compute_postshock(1, 1.4, 1.0, 6.73185e-02, alpha, 1.0)
        assert ps['r2'] == pytest.approx(0.5, abs=5e-2)

    def test_cylindrical_r2(self):
        """Cylindrical shock near r=0.75."""
        from sedov import compute_energy_integrals, compute_postshock
        _, _, alpha = compute_energy_integrals(2, 1.4, 0.0)
        ps = compute_postshock(2, 1.4, 1.0, 0.311357, alpha, 1.0)
        assert ps['r2'] == pytest.approx(0.75, abs=1e-2)

    def test_gamma53_rho2(self):
        """For gamma=5/3: rho2 = (8/3)/(2/3) * rho0 = 4.0"""
        from sedov import compute_energy_integrals, compute_postshock
        gamma = 5.0 / 3.0
        _, _, alpha = compute_energy_integrals(3, gamma, 0.0)
        ps = compute_postshock(3, gamma, 1.0, 1.0, alpha, 1.0)
        assert ps['rho2'] == pytest.approx(4.0, abs=1e-2)


class TestFullProfile:
    """Verify full spatial profile properties.

    Tests qualitative and quantitative properties of the complete
    Sedov solution profile.
    """

    def test_density_outside_shock(self):
        """Outside the shock, density equals the initial density rho0."""
        from sedov import solve_sedov
        r = np.linspace(0.1, 1.5, 200)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        outside = r > result['r2'] + 0.05
        assert np.sum(outside) > 0
        np.testing.assert_allclose(
            result['density'][outside], 1.0, atol=1e-3)

    def test_velocity_outside_shock(self):
        """Outside the shock, velocity is zero."""
        from sedov import solve_sedov
        r = np.linspace(0.1, 1.5, 200)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        outside = r > result['r2'] + 0.05
        np.testing.assert_allclose(
            result['velocity'][outside], 0.0, atol=1e-3)

    def test_pressure_outside_shock(self):
        """Outside the shock, pressure is zero."""
        from sedov import solve_sedov
        r = np.linspace(0.1, 1.5, 200)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        outside = r > result['r2'] + 0.05
        np.testing.assert_allclose(
            result['pressure'][outside], 0.0, atol=1e-3)

    def test_peak_density_near_shock(self):
        """Density inside the shock should significantly exceed initial density.

        The true post-shock density is rho2 = 6.0 for gamma=1.4.
        We sample close to the shock to capture the steep density gradient.
        """
        from sedov import solve_sedov
        # Include points very close to the shock to capture density peak
        r = np.sort(np.concatenate([
            np.linspace(0.1, 1.5, 200),
            np.array([0.998, 0.999, 0.9995])
        ]))
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        assert np.max(result['density']) > 5.5

    def test_velocity_increases_inside_shock(self):
        """Velocity should increase with radius inside the shock."""
        from sedov import solve_sedov
        r = np.linspace(0.3, 0.95, 50)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        vel = result['velocity']
        assert vel[-1] > vel[0], \
            "Velocity at larger r should exceed velocity at smaller r"

    def test_shock_position_in_result(self):
        """Solver should report shock position."""
        from sedov import solve_sedov
        r = np.linspace(0.1, 1.5, 100)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        assert 'r2' in result
        assert result['r2'] == pytest.approx(1.0, abs=2e-2)

    def test_energy_integrals_in_result(self):
        """Solver should report energy integrals."""
        from sedov import solve_sedov
        r = np.linspace(0.1, 1.5, 100)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        assert 'eval1' in result
        assert 'eval2' in result
        assert 'alpha' in result
        assert result['eval1'] == pytest.approx(2.96269e-02, abs=1e-5)

    def test_planar_profile_outside_shock(self):
        """Planar geometry: density outside shock equals rho0."""
        from sedov import solve_sedov
        r = np.linspace(0.01, 0.8, 100)
        result = solve_sedov(r, 1.0, geometry=1, gamma=1.4,
                             rho0=1.0, eblast=6.73185e-02)
        outside = r > result['r2'] + 0.03
        if np.any(outside):
            np.testing.assert_allclose(
                result['density'][outside], 1.0, atol=1e-2)

    def test_specific_internal_energy_positive(self):
        """Specific internal energy should be non-negative everywhere."""
        from sedov import solve_sedov
        r = np.linspace(0.2, 1.5, 100)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        assert np.all(result['specific_internal_energy'] >= -1e-10)

    def test_sound_speed_positive_inside(self):
        """Sound speed should be positive inside the shock."""
        from sedov import solve_sedov
        r = np.linspace(0.3, 0.95, 50)
        result = solve_sedov(r, 1.0, geometry=3, gamma=1.4,
                             rho0=1.0, eblast=0.851072)
        inside = r < result['r2']
        assert np.all(result['sound_speed'][inside] > 0)
