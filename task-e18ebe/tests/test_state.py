"""
Tests for the point-explosion solver.

Verification against published reference tables.

"""

import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest


class TestSedovFunctionsPlanar:
    """Verify Sedov functions against Kamm & Timmes Table 1.

    Planar geometry (j=1), gamma=1.4, omega=0.
    """

    lamvec = [0.9797, 0.9420, 0.9013, 0.8565, 0.8050, 0.7419, 0.7029,
              0.6553, 0.5925, 0.5396, 0.4912, 0.4589, 0.4161, 0.3480,
              0.2810, 0.2320, 0.1680, 0.1040]

    v_ref = [0.5500, 0.5400, 0.5300, 0.5200, 0.5100, 0.5000, 0.4950,
             0.4900, 0.4850, 0.4820, 0.4800, 0.4790, 0.4780, 0.4770,
             0.4765, 0.4763, 0.4762, 0.4762]

    f_ref = [0.9699, 0.9157, 0.8598, 0.8017, 0.7390, 0.6677, 0.6263,
             0.5780, 0.5173, 0.4682, 0.4244, 0.3957, 0.3580, 0.2988,
             0.2410, 0.1989, 0.1440, 0.0891]

    g_ref = [0.8620, 0.6662, 0.5159, 0.3981, 0.3020, 0.2201, 0.1823,
             0.1453, 0.1075, 0.0826, 0.0641, 0.0535, 0.0415, 0.0263,
             0.0153, 0.0095, 0.0042, 0.0013]

    h_ref = [0.9159, 0.7917, 0.6922, 0.6119, 0.5458, 0.4905, 0.4661,
             0.4437, 0.4230, 0.4112, 0.4037, 0.4001, 0.3964, 0.3929,
             0.3911, 0.3905, 0.3901, 0.3900]

    def test_v_values(self):
        import sedov
        n = len(self.lamvec)
        v_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v_out[i] = sedov.find_v_for_lambda(lam, 1.4, 1, 0.0)
        np.testing.assert_allclose(v_out, self.v_ref, atol=1.0e-4)

    def test_lambda_roundtrip(self):
        import sedov
        n = len(self.lamvec)
        lam_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 1, 0.0)
            lam_out[i], _, _, _ = sedov.sedov_funcs(v, 1.4, 1, 0.0)
        np.testing.assert_allclose(lam_out, self.lamvec, atol=1.0e-4)

    def test_f_function(self):
        import sedov
        n = len(self.lamvec)
        f_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 1, 0.0)
            _, f_out[i], _, _ = sedov.sedov_funcs(v, 1.4, 1, 0.0)
        np.testing.assert_allclose(f_out, self.f_ref, atol=1.0e-4)

    def test_g_function(self):
        import sedov
        n = len(self.lamvec)
        g_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 1, 0.0)
            _, _, g_out[i], _ = sedov.sedov_funcs(v, 1.4, 1, 0.0)
        np.testing.assert_allclose(g_out, self.g_ref, atol=1.0e-4)

    def test_h_function(self):
        import sedov
        n = len(self.lamvec)
        h_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 1, 0.0)
            _, _, _, h_out[i] = sedov.sedov_funcs(v, 1.4, 1, 0.0)
        np.testing.assert_allclose(h_out, self.h_ref, atol=1.0e-4)


class TestSedovFunctionsCylindrical:
    """Verify Sedov functions against Kamm & Timmes Table 2.

    Cylindrical geometry (j=2), gamma=1.4, omega=0.
    """

    lamvec = [0.9998, 0.9802, 0.9644, 0.9476, 0.9295, 0.9096, 0.8725,
              0.8442, 0.8094, 0.7629, 0.7242, 0.6894, 0.6390, 0.5745,
              0.5180, 0.4748, 0.4222, 0.3654, 0.3000, 0.2500, 0.2000,
              0.1500, 0.1000]

    v_ref = [0.4166, 0.4100, 0.4050, 0.4000, 0.3950, 0.3900, 0.3820,
             0.3770, 0.3720, 0.3670, 0.3640, 0.3620, 0.3600, 0.3585,
             0.3578, 0.3575, 0.3573, 0.3572, 0.3572, 0.3571, 0.3571,
             0.3571, 0.3571]

    f_ref = [0.9996, 0.9645, 0.9374, 0.9097, 0.8812, 0.8514, 0.7999,
             0.7638, 0.7226, 0.6720, 0.6327, 0.5990, 0.5521, 0.4943,
             0.4448, 0.4074, 0.3620, 0.3133, 0.2572, 0.2143, 0.1714,
             0.1286, 0.0857]

    g_ref = [0.9972, 0.7651, 0.6281, 0.5161, 0.4233, 0.3450, 0.2427,
             0.1892, 0.1415, 0.0974, 0.0718, 0.0545, 0.0362, 0.0208,
             0.0123, 0.0079, 0.0044, 0.0021, 0.0008, 0.0003, 0.0001,
             0.0000, 0.0000]

    h_ref = [0.9984, 0.8658, 0.7829, 0.7122, 0.6513, 0.5982, 0.5266,
             0.4884, 0.4545, 0.4241, 0.4074, 0.3969, 0.3867, 0.3794,
             0.3760, 0.3746, 0.3737, 0.3732, 0.3730, 0.3729, 0.3729,
             0.3729, 0.3729]

    def test_v_values(self):
        import sedov
        n = len(self.lamvec)
        v_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v_out[i] = sedov.find_v_for_lambda(lam, 1.4, 2, 0.0)
        np.testing.assert_allclose(v_out, self.v_ref, atol=1.0e-4)

    def test_f_function(self):
        import sedov
        n = len(self.lamvec)
        f_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 2, 0.0)
            _, f_out[i], _, _ = sedov.sedov_funcs(v, 1.4, 2, 0.0)
        np.testing.assert_allclose(f_out, self.f_ref, atol=1.0e-4)

    def test_g_function(self):
        import sedov
        n = len(self.lamvec)
        g_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 2, 0.0)
            _, _, g_out[i], _ = sedov.sedov_funcs(v, 1.4, 2, 0.0)
        np.testing.assert_allclose(g_out, self.g_ref, atol=1.0e-4)

    def test_h_function(self):
        import sedov
        n = len(self.lamvec)
        h_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 2, 0.0)
            _, _, _, h_out[i] = sedov.sedov_funcs(v, 1.4, 2, 0.0)
        np.testing.assert_allclose(h_out, self.h_ref, atol=1.0e-4)


class TestSedovFunctionsSpherical:
    """Verify Sedov functions against Kamm & Timmes Table 3.

    Spherical geometry (j=3), gamma=1.4, omega=0.
    """

    lamvec = [0.9913, 0.9773, 0.9622, 0.9342, 0.9080, 0.8747, 0.8359,
              0.7950, 0.7493, 0.6788, 0.5794, 0.4560, 0.3600, 0.2960,
              0.2000, 0.1040]

    v_ref = [0.3300, 0.3250, 0.3200, 0.3120, 0.3060, 0.3000, 0.2950,
             0.2915, 0.2890, 0.2870, 0.2860, 0.2857, 0.2857, 0.2857,
             0.2857, 0.2857]

    f_ref = [0.9814, 0.9529, 0.9238, 0.8745, 0.8335, 0.7872, 0.7398,
             0.6952, 0.6497, 0.5844, 0.4971, 0.3909, 0.3086, 0.2537,
             0.1714, 0.0891]

    g_ref = [0.8388, 0.6454, 0.4984, 0.3248, 0.2275, 0.1508, 0.0968,
             0.0620, 0.0379, 0.0174, 0.0052, 0.0009, 0.0001, 0.0000,
             0.0000, 0.0000]

    h_ref = [0.9116, 0.7992, 0.7082, 0.5929, 0.5238, 0.4674, 0.4273,
             0.4021, 0.3857, 0.3732, 0.3672, 0.3656, 0.3655, 0.3655,
             0.3655, 0.3655]

    def test_v_values(self):
        import sedov
        n = len(self.lamvec)
        v_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v_out[i] = sedov.find_v_for_lambda(lam, 1.4, 3, 0.0)
        np.testing.assert_allclose(v_out, self.v_ref, atol=1.0e-4)

    def test_f_function(self):
        import sedov
        n = len(self.lamvec)
        f_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 3, 0.0)
            _, f_out[i], _, _ = sedov.sedov_funcs(v, 1.4, 3, 0.0)
        np.testing.assert_allclose(f_out, self.f_ref, atol=1.0e-4)

    def test_g_function(self):
        import sedov
        n = len(self.lamvec)
        g_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 3, 0.0)
            _, _, g_out[i], _ = sedov.sedov_funcs(v, 1.4, 3, 0.0)
        np.testing.assert_allclose(g_out, self.g_ref, atol=1.0e-4)

    def test_h_function(self):
        import sedov
        n = len(self.lamvec)
        h_out = np.zeros(n)
        for i, lam in enumerate(self.lamvec):
            v = sedov.find_v_for_lambda(lam, 1.4, 3, 0.0)
            _, _, _, h_out[i] = sedov.sedov_funcs(v, 1.4, 3, 0.0)
        np.testing.assert_allclose(h_out, self.h_ref, atol=1.0e-4)


class TestSedovEnergyIntegralsPlanar:
    """Verify energy integrals for planar case (Table 4, row 1)."""

    def test_eval1(self):
        import sedov
        eval1, _, _ = sedov.sedov_alpha(1.4, 1, 0.0)
        assert eval1 == pytest.approx(0.197928, abs=1.0e-6)

    def test_eval2(self):
        import sedov
        _, eval2, _ = sedov.sedov_alpha(1.4, 1, 0.0)
        assert eval2 == pytest.approx(0.175834, abs=1.0e-3)

    def test_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 1, 0.0)
        assert alpha == pytest.approx(0.538548, abs=1.0e-3)


class TestSedovEnergyIntegralsCylindrical:
    """Verify energy integrals for cylindrical case (Table 4, row 2)."""

    def test_eval1(self):
        import sedov
        eval1, _, _ = sedov.sedov_alpha(1.4, 2, 0.0)
        assert eval1 == pytest.approx(6.54053e-02, abs=1.0e-6)

    def test_eval2(self):
        import sedov
        _, eval2, _ = sedov.sedov_alpha(1.4, 2, 0.0)
        assert eval2 == pytest.approx(4.95650e-02, abs=1.0e-4)

    def test_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 2, 0.0)
        assert alpha == pytest.approx(9.84041e-01, abs=1.0e-4)


class TestSedovEnergyIntegralsSpherical:
    """Verify energy integrals for spherical case (Table 4, row 3)."""

    def test_eval1(self):
        import sedov
        eval1, _, _ = sedov.sedov_alpha(1.4, 3, 0.0)
        assert eval1 == pytest.approx(2.96269e-02, abs=1.0e-6)

    def test_eval2(self):
        import sedov
        _, eval2, _ = sedov.sedov_alpha(1.4, 3, 0.0)
        assert eval2 == pytest.approx(2.11647e-02, abs=1.0e-6)

    def test_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 3, 0.0)
        assert alpha == pytest.approx(8.51060e-01, abs=1.0e-4)


class TestSedovShockSpherical:
    """Verify post-shock values for spherical case (Table 5, row 3)."""

    def test_shock_position(self):
        import sedov
        result = sedov.sedov_solution(
            np.array([1.0]), 1.0,
            gamma=1.4, geometry=3, rho0=1.0, omega=0.0, eblast=0.851072)
        assert result['shock_position'] == pytest.approx(1.0, abs=1.0e-2)

    def test_postshock_density(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['density'][ishock] == pytest.approx(6.0, abs=1.0e-2)

    def test_postshock_velocity(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['velocity'][ishock] == pytest.approx(3.33333e-1, abs=1.0e-4)

    def test_postshock_pressure(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['pressure'][ishock] == pytest.approx(1.33333e-1, abs=1.0e-4)

    def test_postshock_sie(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['specific_internal_energy'][ishock] == pytest.approx(
            5.5555e-02, abs=1.0e-4)

    def test_postshock_sound_speed(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['sound_speed'][ishock] == pytest.approx(
            1.76383e-1, abs=1.0e-4)

    def test_preshock_density(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['density'][ishock + 1] == pytest.approx(1.0, abs=1.0e-5)

    def test_preshock_velocity(self):
        import sedov
        r = np.linspace(0.0, 1.2, 121)
        result = sedov.sedov_solution(r, 1.0, gamma=1.4, geometry=3,
                                      rho0=1.0, omega=0.0, eblast=0.851072)
        ishock = np.argmin(np.abs(r - 1.0))
        assert result['velocity'][ishock + 1] == pytest.approx(0.0, abs=1.0e-5)


class TestSedovShockPlanarCylindrical:
    """Verify shock positions for planar and cylindrical cases (Table 5)."""

    def test_planar_shock_position(self):
        import sedov
        result = sedov.sedov_solution(
            np.array([1.0]), 1.0,
            gamma=1.4, geometry=1, rho0=1.0, omega=0.0,
            eblast=6.73185e-02)
        assert result['shock_position'] == pytest.approx(0.5, abs=1.0e-2)

    def test_cylindrical_shock_position(self):
        import sedov
        result = sedov.sedov_solution(
            np.array([1.0]), 1.0,
            gamma=1.4, geometry=2, rho0=1.0, omega=0.0,
            eblast=0.311357)
        assert result['shock_position'] == pytest.approx(0.75, abs=1.0e-3)


class TestSedovSingularCase:
    """Verify singular solution type (Table 6)."""

    def test_singular_cylindrical_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 2, 1.66667)
        assert alpha == pytest.approx(4.80856, abs=1.0e-4)

    def test_singular_spherical_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 3, 2.33333)
        assert alpha == pytest.approx(4.90875, abs=1.0e-4)


class TestSedovVacuumCase:
    """Verify vacuum solution type (Table 8)."""

    def test_vacuum_cylindrical_eval1(self):
        import sedov
        eval1, _, _ = sedov.sedov_alpha(1.4, 2, 1.7)
        assert eval1 == pytest.approx(0.856238, abs=1.0e-5)

    def test_vacuum_cylindrical_eval2(self):
        import sedov
        _, eval2, _ = sedov.sedov_alpha(1.4, 2, 1.7)
        assert eval2 == pytest.approx(0.158561, abs=1.0e-5)

    def test_vacuum_cylindrical_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 2, 1.7)
        assert alpha == pytest.approx(5.18062, abs=1.0e-3)

    def test_vacuum_spherical_eval1(self):
        import sedov
        eval1, _, _ = sedov.sedov_alpha(1.4, 3, 2.4)
        assert eval1 == pytest.approx(0.454265, abs=1.0e-5)

    def test_vacuum_spherical_eval2(self):
        import sedov
        _, eval2, _ = sedov.sedov_alpha(1.4, 3, 2.4)
        assert eval2 == pytest.approx(8.28391e-02, abs=1.0e-5)

    def test_vacuum_spherical_alpha(self):
        import sedov
        _, _, alpha = sedov.sedov_alpha(1.4, 3, 2.4)
        assert alpha == pytest.approx(5.45670, abs=1.0e-3)


class TestSedovSpecialSingularities:
    """Verify that special singularity cases are detected correctly."""

    def test_omega2_detection(self):
        """denom2 ~ 0 when omega ~ (2*gamm1 + j) / gamma."""
        import sedov
        # For gamma=1.4, j=3: omega2 = (2*0.4 + 3)/1.4 = 2.714
        _, _, alpha = sedov.sedov_alpha(1.4, 3, 2.71428)
        assert alpha > 0  # Must not crash

    def test_omega3_detection(self):
        """denom3 ~ 0 when omega ~ j*(2 - gamma)."""
        import sedov
        # For gamma=1.4, j=3: omega3 = 3*0.6 = 1.8
        _, _, alpha = sedov.sedov_alpha(1.4, 3, 1.8)
        assert alpha > 0  # Must not crash


class TestSedovReturnStructure:
    """Verify that sedov_solution returns correctly structured output."""

    def test_returns_dict(self):
        import sedov
        result = sedov.sedov_solution(np.array([0.5, 1.0]), 1.0)
        assert isinstance(result, dict)

    def test_required_keys(self):
        import sedov
        result = sedov.sedov_solution(np.array([0.5, 1.0]), 1.0)
        for key in ['density', 'velocity', 'pressure',
                     'specific_internal_energy', 'sound_speed',
                     'shock_position']:
            assert key in result, f"Missing key: {key}"

    def test_array_shapes(self):
        import sedov
        r = np.linspace(0.0, 1.5, 50)
        result = sedov.sedov_solution(r, 1.0)
        for key in ['density', 'velocity', 'pressure',
                     'specific_internal_energy', 'sound_speed']:
            assert len(result[key]) == len(r), f"Wrong shape for {key}"

    def test_shock_position_is_float(self):
        import sedov
        result = sedov.sedov_solution(np.array([0.5, 1.0]), 1.0)
        assert isinstance(result['shock_position'], float)
