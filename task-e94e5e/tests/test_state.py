"""Tests for the Sedov blast wave solver, Noh implosion solver,
and cross-validation verification framework.

Sedov tests verify against Kamm & Timmes (2007) reference data.
Noh tests verify against closed-form analytical solutions.
Verification tests check the cross-validation framework output.
"""


import json
import os
import subprocess
import sys

sys.path.insert(0, '/app')

import pytest
import numpy as np


# ===========================================================================
# SEDOV SOLVER TESTS
# ===========================================================================

class TestSedovSolutionType:
    """Test solution type classification."""

    def test_standard_spherical(self):
        from sedov import Sedov
        solver = Sedov(geometry=3, gamma=1.4, omega=0.)
        assert solver.solution_type == 'standard'

    def test_standard_planar(self):
        from sedov import Sedov
        solver = Sedov(geometry=1, gamma=1.4, omega=0.)
        assert solver.solution_type == 'standard'

    def test_standard_cylindrical(self):
        from sedov import Sedov
        solver = Sedov(geometry=2, gamma=1.4, omega=0.)
        assert solver.solution_type == 'standard'

    def test_singular_cylindrical(self):
        from sedov import Sedov
        solver = Sedov(geometry=2, gamma=1.4, omega=1.66667)
        assert solver.solution_type == 'singular'

    def test_vacuum_cylindrical(self):
        from sedov import Sedov
        solver = Sedov(geometry=2, gamma=1.4, omega=1.7)
        assert solver.solution_type == 'vacuum'


class TestSedovAlpha:
    """Alpha constant (Kamm & Timmes Table 4 / Table 6)."""

    def test_alpha_planar(self):
        from sedov import Sedov
        solver = Sedov(geometry=1, gamma=1.4, omega=0.)
        assert solver.alpha == pytest.approx(0.538548, abs=1.0e-3)

    def test_alpha_cylindrical(self):
        from sedov import Sedov
        solver = Sedov(geometry=2, gamma=1.4, omega=0.)
        assert solver.alpha == pytest.approx(0.984041, abs=1.0e-3)

    def test_alpha_spherical(self):
        from sedov import Sedov
        solver = Sedov(geometry=3, gamma=1.4, omega=0.)
        assert solver.alpha == pytest.approx(0.851060, abs=1.0e-3)

    def test_alpha_singular_cylindrical(self):
        from sedov import Sedov
        solver = Sedov(geometry=2, gamma=1.4, omega=1.66667)
        assert solver.alpha == pytest.approx(4.80856, abs=1.0e-3)


class TestSedovEnergyIntegrals:
    """Energy integrals (Kamm & Timmes Table 4)."""

    def test_eval1_spherical(self):
        from sedov import Sedov
        solver = Sedov(geometry=3, gamma=1.4, omega=0.)
        assert solver.eval1 == pytest.approx(2.96269e-02, abs=1.0e-5)

    def test_eval2_spherical(self):
        from sedov import Sedov
        solver = Sedov(geometry=3, gamma=1.4, omega=0.)
        assert solver.eval2 == pytest.approx(2.11647e-02, abs=1.0e-5)

    def test_eval1_planar(self):
        from sedov import Sedov
        solver = Sedov(geometry=1, gamma=1.4, omega=0.)
        assert solver.eval1 == pytest.approx(0.197928, abs=1.0e-3)

    def test_eval2_planar(self):
        from sedov import Sedov
        solver = Sedov(geometry=1, gamma=1.4, omega=0.)
        assert solver.eval2 == pytest.approx(0.175834, abs=1.0e-3)


class TestSedovFunctionsSpherical:
    """Sedov functions against Kamm & Timmes Table 3 (spherical, gamma=1.4)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from sedov import Sedov
        self.solver = Sedov(geometry=3, gamma=1.4, omega=0.)

    def test_v0p3300(self):
        l, dl, f, g, h = self.solver.sedov_funcs_standard(0.3300)
        assert l == pytest.approx(0.9913, abs=1e-3)
        assert f == pytest.approx(0.9814, abs=1e-3)
        assert g == pytest.approx(0.8388, abs=1e-3)
        assert h == pytest.approx(0.9116, abs=1e-3)

    def test_v0p3000(self):
        l, dl, f, g, h = self.solver.sedov_funcs_standard(0.3000)
        assert l == pytest.approx(0.8747, abs=1e-3)
        assert f == pytest.approx(0.7872, abs=1e-3)
        assert g == pytest.approx(0.1508, abs=1e-3)
        assert h == pytest.approx(0.4674, abs=1e-3)

    def test_v0p2870(self):
        l, dl, f, g, h = self.solver.sedov_funcs_standard(0.2870)
        assert l == pytest.approx(0.6788, abs=1e-3)
        assert f == pytest.approx(0.5844, abs=1e-3)
        assert g == pytest.approx(0.0174, abs=1e-3)
        assert h == pytest.approx(0.3732, abs=1e-3)


class TestSedovPhysicalSpherical:
    """Spherical physical solution: gamma=1.4, omega=0, eblast=0.851072, t=1."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from sedov import Sedov
        self.solver = Sedov(geometry=3, gamma=1.4, omega=0., eblast=0.851072)
        self.r = np.linspace(0.0, 1.2, 121)
        self.solution = self.solver(self.r, 1.0)
        self.ishock = np.argmin(np.abs(self.r - 1.0))

    def test_postshock_density(self):
        assert self.solution.density[self.ishock] == pytest.approx(6.0, abs=0.05)

    def test_postshock_velocity(self):
        assert self.solution.velocity[self.ishock] == pytest.approx(
            0.333333, abs=0.005)

    def test_postshock_pressure(self):
        assert self.solution.pressure[self.ishock] == pytest.approx(
            0.133333, abs=0.005)

    def test_postshock_sie(self):
        assert self.solution.specific_internal_energy[self.ishock] == (
            pytest.approx(0.05556, abs=0.001))

    def test_preshock_density(self):
        for i in range(self.ishock + 2, len(self.r)):
            assert self.solution.density[i] == pytest.approx(1.0, abs=1e-5)

    def test_preshock_velocity(self):
        for i in range(self.ishock + 2, len(self.r)):
            assert self.solution.velocity[i] == pytest.approx(0.0, abs=1e-5)

    def test_density_positive_inside_shock(self):
        inside = slice(1, self.ishock)
        assert np.all(self.solution.density[inside] > 0)

    def test_sie_pressure_density_relation(self):
        """SIE = p / ((gamma-1) * rho) at the shock."""
        sie = self.solution.specific_internal_energy[self.ishock]
        p = self.solution.pressure[self.ishock]
        rho = self.solution.density[self.ishock]
        assert sie == pytest.approx(p / ((self.solver.gamma - 1) * rho), rel=1e-3)


class TestSedovEdgeCases:

    def test_t0_returns_nan(self):
        from sedov import Sedov
        solver = Sedov()
        solution = solver(np.array([0.5, 1.0]), 0.0)
        for field in ['density', 'pressure', 'specific_internal_energy',
                      'velocity', 'sound_speed']:
            assert np.all(np.isnan(solution[field]))

    def test_invalid_geometry(self):
        from sedov import Sedov
        with pytest.raises(ValueError):
            Sedov(geometry=-1)

    def test_invalid_gamma(self):
        from sedov import Sedov
        with pytest.raises(ValueError):
            Sedov(gamma=0.5)


# ===========================================================================
# NOH SOLVER TESTS
# ===========================================================================

class TestNohConstruction:

    def test_defaults(self):
        from noh import Noh
        solver = Noh()
        assert solver.geometry == 3
        assert solver.gamma == pytest.approx(5.0 / 3.0)
        assert solver.u0 == -1.0
        assert solver.rho0 == 1.0

    def test_custom_params(self):
        from noh import Noh
        solver = Noh(geometry=1, gamma=1.4, u0=-2.0, rho0=0.5)
        assert solver.geometry == 1
        assert solver.gamma == 1.4
        assert solver.u0 == -2.0
        assert solver.rho0 == 0.5

    def test_invalid_geometry(self):
        from noh import Noh
        with pytest.raises(ValueError):
            Noh(geometry=-1)

    def test_invalid_gamma(self):
        from noh import Noh
        with pytest.raises(ValueError):
            Noh(gamma=0.5)

    def test_positive_u0_raises(self):
        from noh import Noh
        with pytest.raises(ValueError):
            Noh(u0=1.0)

    def test_invalid_rho0(self):
        from noh import Noh
        with pytest.raises(ValueError):
            Noh(rho0=-1.0)


class TestNohSphericalGamma53:
    """Spherical Noh, gamma=5/3, rho0=1, u0=-1, t=1."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from noh import Noh
        self.solver = Noh(geometry=3, gamma=5.0 / 3.0, u0=-1.0, rho0=1.0)
        # Shock at r_shock = 1 * (2/3)/2 = 1/3
        # Test points: 0.1 (inside), 0.5 (outside)
        self.r = np.array([0.1, 0.5])
        self.solution = self.solver(self.r, 1.0)

    def test_shock_location(self):
        r_shock = abs(self.solver.u0) * 1.0 * (self.solver.gamma - 1) / 2
        assert r_shock == pytest.approx(1.0 / 3.0, abs=1e-10)

    def test_postshock_density(self):
        # rho0 * ((gamma+1)/(gamma-1))^3 = 1 * 4^3 = 64
        assert self.solution.density[0] == pytest.approx(64.0, abs=1e-10)

    def test_postshock_velocity(self):
        assert self.solution.velocity[0] == pytest.approx(0.0, abs=1e-10)

    def test_postshock_pressure(self):
        # rho0 * u0^2 * G^(j-1) * (gamma+1)/2 = 1 * 1 * 4^2 * (8/3)/2 = 64/3
        assert self.solution.pressure[0] == pytest.approx(64.0 / 3.0, abs=1e-8)

    def test_postshock_sie(self):
        # u0^2 / 2 = 0.5
        assert self.solution.specific_internal_energy[0] == pytest.approx(
            0.5, abs=1e-10)

    def test_preshock_density(self):
        # rho0 * (1 + |u0|*t/r)^(j-1) = (1 + 1/0.5)^2 = 9.0
        assert self.solution.density[1] == pytest.approx(9.0, abs=1e-10)

    def test_preshock_velocity(self):
        assert self.solution.velocity[1] == pytest.approx(-1.0, abs=1e-10)

    def test_preshock_pressure(self):
        assert self.solution.pressure[1] == pytest.approx(0.0, abs=1e-10)

    def test_preshock_sie(self):
        assert self.solution.specific_internal_energy[1] == pytest.approx(
            0.0, abs=1e-10)


class TestNohSphericalGamma14:
    """Spherical Noh, gamma=1.4, rho0=1, u0=-1, t=1."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from noh import Noh
        self.solver = Noh(geometry=3, gamma=1.4, u0=-1.0, rho0=1.0)
        # Shock at r_shock = 1 * 0.4/2 = 0.2
        self.r = np.array([0.1, 0.5])
        self.solution = self.solver(self.r, 1.0)

    def test_shock_location(self):
        r_shock = abs(self.solver.u0) * 1.0 * (self.solver.gamma - 1) / 2
        assert r_shock == pytest.approx(0.2, abs=1e-10)

    def test_postshock_density(self):
        # rho0 * (2.4/0.4)^3 = 6^3 = 216
        assert self.solution.density[0] == pytest.approx(216.0, abs=1e-8)

    def test_postshock_pressure(self):
        # rho0 * u0^2 * 6^2 * 2.4/2 = 36 * 1.2 = 43.2
        assert self.solution.pressure[0] == pytest.approx(43.2, abs=1e-8)

    def test_postshock_sie(self):
        assert self.solution.specific_internal_energy[0] == pytest.approx(
            0.5, abs=1e-10)

    def test_preshock_density(self):
        # At r=0.5, t=1: (1 + 1/0.5)^2 = 9.0
        assert self.solution.density[1] == pytest.approx(9.0, abs=1e-10)


class TestNohAllGeometries:
    """Test all geometries with gamma=5/3."""

    def test_planar_postshock_density(self):
        from noh import Noh
        solver = Noh(geometry=1, gamma=5.0 / 3.0)
        sol = solver(np.array([0.1]), 1.0)
        # 4^1 = 4
        assert sol.density[0] == pytest.approx(4.0, abs=1e-10)

    def test_cylindrical_postshock_density(self):
        from noh import Noh
        solver = Noh(geometry=2, gamma=5.0 / 3.0)
        sol = solver(np.array([0.1]), 1.0)
        # 4^2 = 16
        assert sol.density[0] == pytest.approx(16.0, abs=1e-10)

    def test_spherical_postshock_density(self):
        from noh import Noh
        solver = Noh(geometry=3, gamma=5.0 / 3.0)
        sol = solver(np.array([0.1]), 1.0)
        # 4^3 = 64
        assert sol.density[0] == pytest.approx(64.0, abs=1e-10)

    def test_planar_postshock_pressure(self):
        from noh import Noh
        solver = Noh(geometry=1, gamma=5.0 / 3.0)
        sol = solver(np.array([0.1]), 1.0)
        # G^0 * (gamma+1)/2 = 1 * 4/3 = 4/3
        assert sol.pressure[0] == pytest.approx(4.0 / 3.0, abs=1e-8)

    def test_cylindrical_postshock_pressure(self):
        from noh import Noh
        solver = Noh(geometry=2, gamma=5.0 / 3.0)
        sol = solver(np.array([0.1]), 1.0)
        # G^1 * (gamma+1)/2 = 4 * 4/3 = 16/3
        assert sol.pressure[0] == pytest.approx(16.0 / 3.0, abs=1e-8)

    def test_planar_preshock_density(self):
        from noh import Noh
        solver = Noh(geometry=1, gamma=5.0 / 3.0)
        sol = solver(np.array([0.5]), 1.0)
        # (1 + 1/0.5)^(1-1) = 1.0 (planar: no convergence effect)
        assert sol.density[0] == pytest.approx(1.0, abs=1e-10)

    def test_cylindrical_preshock_density(self):
        from noh import Noh
        solver = Noh(geometry=2, gamma=5.0 / 3.0)
        sol = solver(np.array([0.5]), 1.0)
        # (1 + 1/0.5)^(2-1) = 3.0
        assert sol.density[0] == pytest.approx(3.0, abs=1e-10)


class TestNohEdgeCases:

    def test_t0_returns_nan(self):
        from noh import Noh
        solver = Noh()
        sol = solver(np.array([0.1, 0.5]), 0.0)
        for field in ['density', 'pressure', 'specific_internal_energy',
                      'velocity', 'sound_speed']:
            assert np.all(np.isnan(sol[field]))

    def test_negative_t_returns_nan(self):
        from noh import Noh
        solver = Noh()
        sol = solver(np.array([0.1, 0.5]), -1.0)
        assert np.all(np.isnan(sol.density))

    def test_returns_all_fields(self):
        from noh import Noh
        solver = Noh()
        sol = solver(np.linspace(0.01, 1.0, 50), 1.0)
        for field in ['position', 'density', 'pressure',
                      'specific_internal_energy', 'velocity', 'sound_speed']:
            assert hasattr(sol, field)
            assert len(sol[field]) == 50

    def test_sound_speed_postshock(self):
        from noh import Noh
        # cs = sqrt(gamma * p / rho) = sqrt(gamma * u0^2 * (gamma-1) / 2)
        # For gamma=5/3: sqrt(5/3 * 1 * 2/3 / 2) = sqrt(5/9)
        solver = Noh(geometry=3, gamma=5.0 / 3.0)
        sol = solver(np.array([0.1]), 1.0)
        expected_cs = np.sqrt(5.0 / 9.0)
        assert sol.sound_speed[0] == pytest.approx(expected_cs, rel=1e-6)

    def test_sound_speed_preshock_is_zero(self):
        from noh import Noh
        solver = Noh(geometry=3, gamma=5.0 / 3.0)
        sol = solver(np.array([0.5]), 1.0)
        assert sol.sound_speed[0] == pytest.approx(0.0, abs=1e-10)


class TestNohGeneralGamma:
    """Test with gamma=1.4 across all geometries to ensure general formula."""

    def test_planar_gamma14_density(self):
        from noh import Noh
        solver = Noh(geometry=1, gamma=1.4)
        sol = solver(np.array([0.01]), 1.0)
        # G = 6, density = 6^1 = 6
        assert sol.density[0] == pytest.approx(6.0, abs=1e-10)

    def test_cylindrical_gamma14_density(self):
        from noh import Noh
        solver = Noh(geometry=2, gamma=1.4)
        sol = solver(np.array([0.01]), 1.0)
        # G = 6, density = 6^2 = 36
        assert sol.density[0] == pytest.approx(36.0, abs=1e-10)

    def test_spherical_gamma14_density(self):
        from noh import Noh
        solver = Noh(geometry=3, gamma=1.4)
        sol = solver(np.array([0.01]), 1.0)
        # G = 6, density = 6^3 = 216
        assert sol.density[0] == pytest.approx(216.0, abs=1e-8)

    def test_planar_gamma14_pressure(self):
        from noh import Noh
        solver = Noh(geometry=1, gamma=1.4)
        sol = solver(np.array([0.01]), 1.0)
        # G^0 * (1.4+1)/2 = 1.2
        assert sol.pressure[0] == pytest.approx(1.2, abs=1e-8)

    def test_cylindrical_gamma14_pressure(self):
        from noh import Noh
        solver = Noh(geometry=2, gamma=1.4)
        sol = solver(np.array([0.01]), 1.0)
        # G^1 * (gamma+1)/2 = 6 * 1.2 = 7.2
        assert sol.pressure[0] == pytest.approx(7.2, abs=1e-8)

    def test_spherical_gamma14_pressure(self):
        from noh import Noh
        solver = Noh(geometry=3, gamma=1.4)
        sol = solver(np.array([0.01]), 1.0)
        # G^2 * (gamma+1)/2 = 36 * 1.2 = 43.2
        assert sol.pressure[0] == pytest.approx(43.2, abs=1e-8)


# ===========================================================================
# VERIFICATION FRAMEWORK TESTS
# ===========================================================================

@pytest.fixture(scope='module')
def verification_results():
    """Run verify.py and load results."""
    result = subprocess.run(
        [sys.executable, '/app/verify.py'],
        capture_output=True, text=True, cwd='/app', timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"verify.py failed with:\n{result.stderr}\n{result.stdout}")
    with open('/app/results.json') as f:
        return json.load(f)


class TestVerificationStructure:
    """Test that results.json has the required structure."""

    def test_results_file_exists(self, verification_results):
        assert os.path.exists('/app/results.json')

    def test_top_level_keys(self, verification_results):
        assert 'quadrature_comparison' in verification_results
        assert 'cross_validation' in verification_results
        assert 'rankine_hugoniot' in verification_results

    def test_quadrature_keys(self, verification_results):
        q = verification_results['quadrature_comparison']
        assert 'quad_alpha' in q
        assert 'fixed_quad_n15_alpha' in q
        assert 'fixed_quad_n40_alpha' in q
        assert 'best_method' in q

    def test_cross_validation_has_six_entries(self, verification_results):
        cv = verification_results['cross_validation']
        assert len(cv) >= 6

    def test_rankine_hugoniot_keys(self, verification_results):
        rh = verification_results['rankine_hugoniot']
        assert 'density_rel_error' in rh
        assert 'velocity_rel_error' in rh
        assert 'pressure_rel_error' in rh


class TestVerificationQuadrature:
    """Test quadrature comparison results."""

    def test_quad_alpha_accurate(self, verification_results):
        q = verification_results['quadrature_comparison']
        assert abs(q['quad_alpha'] - 0.851060) < 1e-3

    def test_fixed_quad_n15_reasonable(self, verification_results):
        q = verification_results['quadrature_comparison']
        assert 0.5 < q['fixed_quad_n15_alpha'] < 1.5

    def test_fixed_quad_n40_reasonable(self, verification_results):
        q = verification_results['quadrature_comparison']
        assert 0.5 < q['fixed_quad_n40_alpha'] < 1.5

    def test_best_method_is_string(self, verification_results):
        q = verification_results['quadrature_comparison']
        assert isinstance(q['best_method'], str)
        assert q['best_method'] in ['quad', 'fixed_quad_n15', 'fixed_quad_n40']


class TestVerificationCrossValidation:
    """Test cross-validation results."""

    def test_spherical_gamma14_ratio(self, verification_results):
        cv = verification_results['cross_validation']
        entry = cv['spherical_gamma_1_4']
        assert entry['analytical_ratio'] == pytest.approx(6.0, abs=1e-10)

    def test_spherical_gamma53_ratio(self, verification_results):
        cv = verification_results['cross_validation']
        entry = cv['spherical_gamma_5_3']
        assert entry['analytical_ratio'] == pytest.approx(4.0, abs=1e-10)

    def test_noh_density_matches_expected(self, verification_results):
        cv = verification_results['cross_validation']
        for key, entry in cv.items():
            assert entry['noh_density_error'] < 1e-6, (
                f"Noh density error too large for {key}: {entry['noh_density_error']}"
            )

    def test_sedov_compression_matches_analytical(self, verification_results):
        cv = verification_results['cross_validation']
        for key, entry in cv.items():
            assert abs(entry['sedov_compression'] - entry['analytical_ratio']) < 1e-10, (
                f"Sedov compression mismatch for {key}"
            )

    def test_all_geometries_present(self, verification_results):
        cv = verification_results['cross_validation']
        for geo in ['planar', 'cylindrical', 'spherical']:
            for gam in ['gamma_1_4', 'gamma_5_3']:
                key = f'{geo}_{gam}'
                assert key in cv, f"Missing cross-validation entry: {key}"


class TestVerificationRankineHugoniot:
    """Test Rankine-Hugoniot verification results."""

    def test_density_error_small(self, verification_results):
        rh = verification_results['rankine_hugoniot']
        assert rh['density_rel_error'] < 0.05

    def test_velocity_error_small(self, verification_results):
        rh = verification_results['rankine_hugoniot']
        assert rh['velocity_rel_error'] < 0.05

    def test_pressure_error_small(self, verification_results):
        rh = verification_results['rankine_hugoniot']
        assert rh['pressure_rel_error'] < 0.05

    def test_shock_position_positive(self, verification_results):
        rh = verification_results['rankine_hugoniot']
        assert rh['shock_position'] > 0
