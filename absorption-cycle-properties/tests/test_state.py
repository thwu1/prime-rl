
import pytest
import json
import sys
import os
from math import log, exp

sys.path.insert(0, '/app')

# ========================================================================
# Reference implementation of the correct Patek-Klomfar (1995) correlations
# Used only for computing expected cycle results.
# ========================================================================

def _ref_T_bubble(p, x):
    T0, p0 = 100.0, 2.0
    coeffs = [
        (0.322302e+1, 0, 0), (-0.384206e+0, 0, 1), (0.460965e-1, 0, 2),
        (-0.378945e-2, 0, 3), (0.135610e-3, 0, 4), (0.487755e+0, 1, 0),
        (-0.120108e+0, 1, 1), (0.106154e-1, 1, 2), (-0.533589e-3, 2, 3),
        (0.785041e+1, 4, 0), (-0.115941e+2, 5, 0), (-0.523150e-1, 5, 1),
        (0.489596e+1, 6, 0), (0.421059e-1, 13, 1),
    ]
    return T0 * sum(a * (1 - x)**m * log(p0 / p)**n for a, m, n in coeffs)


def _ref_T_dew(p, y):
    T0, p0 = 100.0, 2.0
    coeffs = [
        (0.324004e+1, 0, 0), (-0.395920e+0, 0, 1), (0.435624e-1, 0, 2),
        (-0.218943e-2, 0, 3), (-0.143526e+1, 1, 0), (0.105256e+1, 1, 1),
        (-0.719281e-1, 1, 2), (0.122362e+2, 2, 0), (-0.224368e+1, 2, 1),
        (-0.201780e+2, 3, 0), (0.110834e+1, 3, 1), (0.145399e+2, 4, 0),
        (0.644312e+0, 4, 2), (-0.221246e+1, 5, 0), (-0.756266e+0, 5, 2),
        (-0.135529e+1, 6, 0), (0.183541e+0, 7, 2),
    ]
    return T0 * sum(a * (1 - y)**(m / 4.0) * log(p0 / p)**n for a, m, n in coeffs)


def _ref_y_vapor(p, x):
    p0 = 2.0
    coeffs = [
        (1.98022017e+1, 0, 0), (-1.18092669e+1, 0, 1), (2.77479980e+1, 0, 6),
        (-2.88634277e+1, 0, 7), (-5.91616608e+1, 1, 0), (5.78091305e+2, 2, 1),
        (-6.21736743e+0, 2, 2), (-3.42198402e+3, 3, 2), (1.19403127e+4, 4, 3),
        (-2.45413777e+4, 5, 4), (2.91591865e+4, 6, 5), (-1.84782290e+4, 7, 6),
        (2.34819434e+1, 7, 7), (4.80310617e+3, 8, 7),
    ]
    s = sum(a * (p / p0)**m * x**(n / 3.0) for a, m, n in coeffs)
    return 1.0 - exp(log(1.0 - x) * s)


def _ref_h_liquid(T, x):
    h0, T0 = 100.0, 273.16
    coeffs = [
        (-0.761080e+1, 0, 1), (0.256905e+2, 0, 4), (-0.247092e+3, 0, 8),
        (0.325952e+3, 0, 9), (-0.158854e+3, 0, 12), (0.619084e+2, 0, 14),
        (0.114314e+2, 1, 0), (0.118157e+1, 1, 1), (0.284179e+1, 2, 1),
        (0.741609e+1, 3, 3), (0.891844e+3, 5, 3), (-0.161309e+4, 5, 4),
        (0.622106e+3, 5, 5), (-0.207588e+3, 6, 2), (-0.687393e+1, 6, 4),
        (0.350716e+1, 8, 0),
    ]
    return h0 * sum(a * (T / T0 - 1.0)**m * x**n for a, m, n in coeffs)


def _ref_h_vapor(T, y):
    h0, T0 = 1000.0, 324.0
    coeffs = [
        (0.128827e+1, 0, 0), (0.125247e+0, 1, 0), (-0.208748e+1, 2, 0),
        (0.217696e+1, 3, 0), (0.235687e+1, 0, 2), (-0.886987e+1, 1, 2),
        (0.102635e+2, 2, 2), (-0.237440e+1, 3, 2), (-0.670515e+1, 0, 3),
        (0.164508e+2, 1, 3), (-0.936849e+1, 2, 3), (0.842254e+1, 0, 4),
        (-0.858807e+1, 1, 4), (-0.277049e+1, 0, 5), (-0.961248e+0, 4, 6),
        (0.988009e+0, 2, 7), (0.308482e+0, 1, 10),
    ]
    return h0 * sum(a * (1.0 - T / T0)**m * (1.0 - y)**(n / 4.0) for a, m, n in coeffs)


def _ref_molar_to_mass(q):
    MA, MW = 17.031, 18.015
    return q * MA / (q * MA + (1.0 - q) * MW)


# ========================================================================
# Verify reference implementation against known benchmark data
# ========================================================================

class TestReferenceIntegrity:
    """Sanity check that the test's own reference implementation is correct."""

    def test_ref_bubble(self):
        assert abs(_ref_T_bubble(0.5, 0.4) - 331.258850) < 0.001

    def test_ref_dew(self):
        assert abs(_ref_T_dew(1.0, 0.3) - 438.994863) < 0.001

    def test_ref_y(self):
        assert abs(_ref_y_vapor(1.0, 0.3) - 0.9082798) < 1e-5

    def test_ref_hl(self):
        assert abs(_ref_h_liquid(300, 0.5) - (-136.7231)) < 0.01

    def test_ref_hv(self):
        assert abs(_ref_h_vapor(280, 0.5) - 1931.4134) < 0.01


# ========================================================================
# Test solver's forward correlations against benchmark data
# ========================================================================

class TestBubblePointTemperature:
    def test_points(self):
        import nh3h2o
        cases = [
            (0.05, 0.1,  324.832110),
            (0.05, 0.5,  255.459181),
            (0.1,  0.1,  342.993097),
            (0.1,  0.3,  303.114145),
            (0.1,  0.5,  270.274470),
            (0.1,  0.9,  241.762361),
            (0.2,  0.5,  287.349433),
            (0.5,  0.3,  350.849447),
            (0.5,  0.4,  331.258850),
            (1.0,  0.5,  338.608689),
            (1.0,  0.6,  324.336750),
            (1.0,  0.7,  313.938573),
            (1.5,  0.3,  394.392248),
            (2.0,  0.9,  327.246950),
        ]
        for p, x, expected in cases:
            T = nh3h2o.T_from_px(p, x)
            assert abs(T - expected) < 0.01, \
                f"T_from_px({p}, {x}): got {T:.6f}, expected {expected:.6f}"


class TestDewPointTemperature:
    def test_points(self):
        import nh3h2o
        cases = [
            (0.05, 0.3, 345.927687),
            (0.05, 0.7, 329.329687),
            (0.1,  0.3, 363.194624),
            (0.1,  0.7, 344.299883),
            (0.2,  0.5, 373.385613),
            (0.2,  0.9, 339.544551),
            (0.5,  0.3, 412.631965),
            (0.5,  0.5, 401.499309),
            (1.0,  0.1, 448.539409),
            (1.0,  0.5, 426.362736),
            (1.0,  0.7, 409.122728),
            (1.5,  0.5, 442.539393),
            (2.0,  0.3, 469.041298),
            (2.0,  0.7, 434.856854),
        ]
        for p, y, expected in cases:
            T = nh3h2o.T_from_py(p, y)
            assert abs(T - expected) < 0.01, \
                f"T_from_py({p}, {y}): got {T:.6f}, expected {expected:.6f}"


class TestVaporComposition:
    def test_points(self):
        import nh3h2o
        cases = [
            (0.05, 0.2, 0.93195779),
            (0.1,  0.1, 0.72019696),
            (0.1,  0.5, 0.99869623),
            (0.2,  0.3, 0.96450997),
            (0.5,  0.3, 0.94143301),
            (0.5,  0.5, 0.99400818),
            (1.0,  0.3, 0.90827980),
            (1.0,  0.5, 0.98716205),
            (1.5,  0.3, 0.88790889),
            (1.5,  0.5, 0.97929994),
            (2.0,  0.1, 0.45741814),
            (2.0,  0.7, 0.99319733),
        ]
        for p, x, expected in cases:
            y = nh3h2o.y_from_px(p, x)
            assert abs(y - expected) < 1e-4, \
                f"y_from_px({p}, {x}): got {y:.8f}, expected {expected:.8f}"


class TestLiquidEnthalpy:
    def test_points(self):
        import nh3h2o
        cases = [
            (275, 0.2, -140.2902),
            (275, 0.5, -248.2280),
            (275, 0.8, -138.2563),
            (290, 0.4, -172.7311),
            (300, 0.3, -91.8456),
            (300, 0.7, -80.2935),
            (310, 0.6, -72.6386),
            (320, 0.5, -45.2238),
            (340, 0.8, 172.4887),
            (360, 0.4, 148.6733),
            (380, 0.2, 318.8182),
            (400, 0.9, 350.8643),
        ]
        for T, x, expected in cases:
            h = nh3h2o.Hl_from_Tx(T, x)
            assert abs(h - expected) < 0.05, \
                f"Hl_from_Tx({T}, {x}): got {h:.4f}, expected {expected:.4f}"


class TestVaporEnthalpy:
    def test_points(self):
        import nh3h2o
        cases = [
            (240, 0.2, 2201.1390),
            (240, 0.6, 1738.1260),
            (260, 0.4, 2012.5900),
            (270, 0.8, 1543.7635),
            (280, 0.5, 1931.4134),
            (290, 0.3, 2187.2297),
            (300, 0.7, 1726.0420),
            (310, 0.9, 1500.4246),
            (320, 0.1, 2472.9598),
            (320, 0.4, 2125.9110),
        ]
        for T, y, expected in cases:
            h = nh3h2o.Hg_from_Ty(T, y)
            assert abs(h - expected) < 0.05, \
                f"Hg_from_Ty({T}, {y}): got {h:.4f}, expected {expected:.4f}"


# ========================================================================
# Test inverse functions
# ========================================================================

class TestInverseFunctions:
    def test_p_from_Tx(self):
        import nh3h2o
        cases = [
            (331.258850, 0.4, 0.5),
            (324.336750, 0.6, 1.0),
            (287.349433, 0.5, 0.2),
            (394.392248, 0.3, 1.5),
            (270.274470, 0.5, 0.1),
        ]
        for T, x, expected_p in cases:
            p = nh3h2o.p_from_Tx(T, x)
            assert abs(p - expected_p) < 0.002, \
                f"p_from_Tx({T}, {x}): got {p:.6f}, expected {expected_p:.4f}"

    def test_x_from_pT(self):
        import nh3h2o
        cases = [
            (0.5, 331.258850, 0.4),
            (1.0, 324.336750, 0.6),
            (0.2, 287.349433, 0.5),
            (1.5, 394.392248, 0.3),
        ]
        for p, T, expected_x in cases:
            x = nh3h2o.x_from_pT(p, T)
            assert abs(x - expected_x) < 0.002, \
                f"x_from_pT({p}, {T}): got {x:.6f}, expected {expected_x:.4f}"

    def test_T_from_hx_recovery(self):
        """T_from_hx should recover temperature from reference enthalpy."""
        import nh3h2o
        cases = [
            (300, 0.3), (320, 0.5), (350, 0.6),
            (280, 0.2), (400, 0.4), (340, 0.6),
        ]
        for T_orig, x in cases:
            h = _ref_h_liquid(T_orig, x)
            T_rec = nh3h2o.T_from_hx(h, x)
            assert abs(T_rec - T_orig) < 0.1, \
                f"T_from_hx(h={h:.2f}, x={x}): got {T_rec:.4f}, expected {T_orig:.4f}"

    def test_T_from_hx_consistency(self):
        """T_from_hx should be consistent with solver's own Hl_from_Tx."""
        import nh3h2o
        cases = [
            (-91.8456, 0.3),
            (-45.2238, 0.5),
            (-72.6386, 0.6),
            (148.6733, 0.4),
        ]
        for h, x in cases:
            T = nh3h2o.T_from_hx(h, x)
            h_check = nh3h2o.Hl_from_Tx(T, x)
            assert abs(h_check - h) < 0.1, \
                f"Roundtrip: h={h}, x={x}, T={T:.4f}, h_check={h_check:.4f}"

    def test_inverse_roundtrip(self):
        """Forward then inverse should recover original inputs."""
        import nh3h2o
        test_cases = [(0.3, 0.4), (1.0, 0.7), (1.5, 0.2)]
        for p_orig, x_orig in test_cases:
            T = nh3h2o.T_from_px(p_orig, x_orig)
            p_rec = nh3h2o.p_from_Tx(T, x_orig)
            assert abs(p_rec - p_orig) < 0.005, \
                f"Roundtrip p: orig={p_orig}, recovered={p_rec}"
            x_rec = nh3h2o.x_from_pT(p_orig, T)
            assert abs(x_rec - x_orig) < 0.005, \
                f"Roundtrip x: orig={x_orig}, recovered={x_rec}"


# ========================================================================
# Test cycle results with SHX
# ========================================================================

class TestCycleResults:
    def test_results_file_exists(self):
        assert os.path.exists('/app/cycle_results.json'), \
            "cycle_results.json not found at /app/"

    def test_all_keys_present(self):
        with open('/app/cycle_results.json') as f:
            res = json.load(f)
        required = [
            "T_generator_K", "T_absorber_K", "y_refrigerant_molar",
            "h_weak_gen_kJperkg", "h_strong_abs_kJperkg",
            "h_refrigerant_vapor_kJperkg", "T_condenser_K",
            "h_condensed_liquid_kJperkg", "T_evaporator_K",
            "h_evaporator_vapor_kJperkg", "circulation_ratio",
            "T_weak_SHX_out_K", "h_strong_SHX_out_kJperkg",
            "T_strong_SHX_out_K", "Q_SHX_kW",
            "Q_generator_kW", "Q_evaporator_kW",
            "COP_cooling", "COP_no_SHX",
        ]
        for k in required:
            assert k in res, f"Missing key: {k}"

    def test_cycle_values(self):
        from scipy.optimize import brentq

        with open('/app/cycle_results.json') as f:
            res = json.load(f)
        with open('/app/cycle_spec.json') as f:
            cfg = json.load(f)

        P_hi = cfg['P_high_MPa']
        P_lo = cfg['P_low_MPa']
        x_s = cfg['x_strong_molar']
        x_w = cfg['x_weak_molar']
        m_r = cfg['m_ref_kgps']
        eps = cfg['SHX_effectiveness']

        # Basic state points
        T_gen = _ref_T_bubble(P_hi, x_w)
        T_abs = _ref_T_bubble(P_lo, x_s)
        y_ref = _ref_y_vapor(P_hi, x_w)

        h_wk = _ref_h_liquid(T_gen, x_w)
        h_st = _ref_h_liquid(T_abs, x_s)
        h_vap = _ref_h_vapor(T_gen, y_ref)

        T_cond = _ref_T_bubble(P_hi, y_ref)
        h_cond = _ref_h_liquid(T_cond, y_ref)
        T_evap = _ref_T_dew(P_lo, y_ref)
        h_evap = _ref_h_vapor(T_evap, y_ref)

        # Mass fractions and circulation ratio
        w_s = _ref_molar_to_mass(x_s)
        w_w = _ref_molar_to_mass(x_w)
        w_r = _ref_molar_to_mass(y_ref)
        f = (w_r - w_w) / (w_s - w_w)

        m_wk = (f - 1) * m_r
        m_st = f * m_r

        # SHX calculations
        T_wk_out = T_gen - eps * (T_gen - T_abs)
        h_wk_out = _ref_h_liquid(T_wk_out, x_w)
        Q_SHX = m_wk * (h_wk - h_wk_out)
        h_st_out = h_st + Q_SHX / m_st
        T_st_out = brentq(
            lambda T: _ref_h_liquid(T, x_s) - h_st_out, 250, 450
        )

        # Energy balances with SHX
        Q_gen = (h_vap + (f - 1) * h_wk - f * h_st_out) * m_r
        Q_evap = (h_evap - h_cond) * m_r
        COP = Q_evap / Q_gen

        # Without SHX
        Q_gen_no = (h_vap + (f - 1) * h_wk - f * h_st) * m_r
        COP_no = Q_evap / Q_gen_no

        tol_T = 0.5
        tol_h = 2.0
        tol_y = 0.002
        tol_f = 0.05
        tol_Q = 10.0
        tol_COP = 0.02

        checks = [
            ("T_generator_K", T_gen, tol_T),
            ("T_absorber_K", T_abs, tol_T),
            ("y_refrigerant_molar", y_ref, tol_y),
            ("h_weak_gen_kJperkg", h_wk, tol_h),
            ("h_strong_abs_kJperkg", h_st, tol_h),
            ("h_refrigerant_vapor_kJperkg", h_vap, tol_h),
            ("T_condenser_K", T_cond, tol_T),
            ("h_condensed_liquid_kJperkg", h_cond, tol_h),
            ("T_evaporator_K", T_evap, tol_T),
            ("h_evaporator_vapor_kJperkg", h_evap, tol_h),
            ("circulation_ratio", f, tol_f),
            ("T_weak_SHX_out_K", T_wk_out, tol_T),
            ("h_strong_SHX_out_kJperkg", h_st_out, tol_h),
            ("T_strong_SHX_out_K", T_st_out, tol_T),
            ("Q_SHX_kW", Q_SHX, tol_Q),
            ("Q_generator_kW", Q_gen, tol_Q),
            ("Q_evaporator_kW", Q_evap, tol_Q),
            ("COP_cooling", COP, tol_COP),
            ("COP_no_SHX", COP_no, tol_COP),
        ]
        for key, expected, tol in checks:
            actual = res[key]
            assert abs(actual - expected) < tol, \
                f"{key}: got {actual}, expected {expected:.6f}, tol {tol}"
