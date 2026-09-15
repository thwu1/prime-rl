
"""
Tests for the IAPWS-IF97 C library + Python wrapper.
Verifies against published IAPWS computer-program verification tables,
transport property correlations, and Rankine cycle analysis output.
"""

import sys
import os
import json
import math
import ctypes
import pytest

RTOL = 1e-6


def rel_err(computed, expected):
    if expected == 0:
        return abs(computed)
    return abs((computed - expected) / expected)


def assert_close(computed, expected, label=""):
    err = rel_err(computed, expected)
    assert err < RTOL, (
        f"{label}: computed={computed}, expected={expected}, rel_err={err:.2e}"
    )


# ============================================================
# Library build verification
# ============================================================
class TestLibraryBuild:
    def test_library_exists(self):
        assert os.path.exists('/app/libif97.so'), "libif97.so not found at /app/"

    def test_library_loadable(self):
        lib = ctypes.CDLL('/app/libif97.so')
        assert lib is not None

    def test_library_exports(self):
        lib = ctypes.CDLL('/app/libif97.so')
        for name in ['region1_props', 'region2_props', 'region3_props',
                      'region5_props', 'saturation_pressure',
                      'saturation_temperature', 'determine_region']:
            assert hasattr(lib, name), f"Missing export: {name}"


# ============================================================
# Engine fixture
# ============================================================
@pytest.fixture(scope="module")
def engine():
    sys.path.insert(0, '/app')
    from wrapper import IF97Engine
    return IF97Engine()


# ============================================================
# Region 1 verification (IF-97 Table 5)
# ============================================================
class TestRegion1:
    def test_T300_p3(self, engine):
        r = engine.region1_props(300.0, 3.0)
        assert_close(r['v'], 0.100215168e-2, 'v')
        assert_close(r['h'], 0.115331273e3, 'h')
        assert_close(r['u'], 0.112324818e3, 'u')
        assert_close(r['s'], 0.392294792e0, 's')
        assert_close(r['cp'], 0.417301218e1, 'cp')
        assert_close(r['w'], 0.150773921e4, 'w')

    def test_T300_p80(self, engine):
        r = engine.region1_props(300.0, 80.0)
        assert_close(r['v'], 0.971180894e-3, 'v')
        assert_close(r['h'], 0.184142828e3, 'h')
        assert_close(r['u'], 0.106448356e3, 'u')
        assert_close(r['s'], 0.368563852e0, 's')
        assert_close(r['cp'], 0.401008987e1, 'cp')
        assert_close(r['w'], 0.163469054e4, 'w')

    def test_T500_p3(self, engine):
        r = engine.region1_props(500.0, 3.0)
        assert_close(r['v'], 0.120241800e-2, 'v')
        assert_close(r['h'], 0.975542239e3, 'h')
        assert_close(r['u'], 0.971934985e3, 'u')
        assert_close(r['s'], 0.258041912e1, 's')
        assert_close(r['cp'], 0.465580682e1, 'cp')
        assert_close(r['w'], 0.124071337e4, 'w')


# ============================================================
# Region 2 verification (IF-97 Table 15)
# ============================================================
class TestRegion2:
    def test_T300_p0035(self, engine):
        r = engine.region2_props(300.0, 0.0035)
        assert_close(r['v'], 0.394913866e2, 'v')
        assert_close(r['h'], 0.254991145e4, 'h')
        assert_close(r['u'], 0.241169160e4, 'u')
        assert_close(r['s'], 0.852238967e1, 's')
        assert_close(r['cp'], 0.191300162e1, 'cp')
        assert_close(r['w'], 0.427920172e3, 'w')

    def test_T700_p0035(self, engine):
        r = engine.region2_props(700.0, 0.0035)
        assert_close(r['v'], 0.923015898e2, 'v')
        assert_close(r['h'], 0.333568375e4, 'h')
        assert_close(r['u'], 0.301262819e4, 'u')
        assert_close(r['s'], 0.101749996e2, 's')
        assert_close(r['cp'], 0.208141274e1, 'cp')
        assert_close(r['w'], 0.644289068e3, 'w')

    def test_T700_p30(self, engine):
        r = engine.region2_props(700.0, 30.0)
        assert_close(r['v'], 0.542946619e-2, 'v')
        assert_close(r['h'], 0.263149474e4, 'h')
        assert_close(r['u'], 0.246861076e4, 'u')
        assert_close(r['s'], 0.517540298e1, 's')
        assert_close(r['cp'], 0.103505092e2, 'cp')
        assert_close(r['w'], 0.480386523e3, 'w')


# ============================================================
# Region 3 verification (IF-97 Table 33)
# ============================================================
class TestRegion3:
    def test_T650_rho500(self, engine):
        r = engine.region3_props(650.0, 500.0)
        assert_close(r['p'], 0.255837018e2, 'p')
        assert_close(r['h'], 0.186343019e4, 'h')
        assert_close(r['u'], 0.181226279e4, 'u')
        assert_close(r['s'], 0.405427273e1, 's')
        assert_close(r['cp'], 0.138935717e2, 'cp')
        assert_close(r['w'], 0.502005554e3, 'w')

    def test_T650_rho200(self, engine):
        r = engine.region3_props(650.0, 200.0)
        assert_close(r['p'], 0.222930643e2, 'p')
        assert_close(r['h'], 0.237512401e4, 'h')
        assert_close(r['u'], 0.226365868e4, 'u')
        assert_close(r['s'], 0.485438792e1, 's')
        assert_close(r['cp'], 0.446579342e2, 'cp')
        assert_close(r['w'], 0.383444594e3, 'w')

    def test_T750_rho500(self, engine):
        r = engine.region3_props(750.0, 500.0)
        assert_close(r['p'], 0.783095639e2, 'p')
        assert_close(r['h'], 0.225868845e4, 'h')
        assert_close(r['u'], 0.210206932e4, 'u')
        assert_close(r['s'], 0.446971906e1, 's')
        assert_close(r['cp'], 0.634165359e1, 'cp')
        assert_close(r['w'], 0.760696041e3, 'w')


# ============================================================
# Region 4 saturation verification (IF-97 Tables 35 & 36)
# ============================================================
class TestSaturation:
    def test_psat_T300(self, engine):
        assert_close(engine.saturation_pressure(300.0), 0.353658941e-2, 'psat(300)')

    def test_psat_T500(self, engine):
        assert_close(engine.saturation_pressure(500.0), 0.263889776e1, 'psat(500)')

    def test_psat_T600(self, engine):
        assert_close(engine.saturation_pressure(600.0), 0.123443146e2, 'psat(600)')

    def test_Tsat_p01(self, engine):
        assert_close(engine.saturation_temperature(0.1), 0.372755919e3, 'Tsat(0.1)')

    def test_Tsat_p1(self, engine):
        assert_close(engine.saturation_temperature(1.0), 0.453035632e3, 'Tsat(1)')

    def test_Tsat_p10(self, engine):
        assert_close(engine.saturation_temperature(10.0), 0.584149488e3, 'Tsat(10)')


# ============================================================
# Region 5 verification (IF-97 Table 42)
# ============================================================
class TestRegion5:
    def test_T1500_p05(self, engine):
        r = engine.region5_props(1500.0, 0.5)
        assert_close(r['v'], 0.138455090e1, 'v')
        assert_close(r['h'], 0.521976855e4, 'h')
        assert_close(r['u'], 0.452749310e4, 'u')
        assert_close(r['s'], 0.965408875e1, 's')
        assert_close(r['cp'], 0.261609445e1, 'cp')
        assert_close(r['w'], 0.917068690e3, 'w')

    def test_T1500_p30(self, engine):
        r = engine.region5_props(1500.0, 30.0)
        assert_close(r['v'], 0.230761299e-1, 'v')
        assert_close(r['h'], 0.516723514e4, 'h')
        assert_close(r['u'], 0.447495124e4, 'u')
        assert_close(r['s'], 0.772970133e1, 's')
        assert_close(r['cp'], 0.272724317e1, 'cp')
        assert_close(r['w'], 0.928548002e3, 'w')

    def test_T2000_p30(self, engine):
        r = engine.region5_props(2000.0, 30.0)
        assert_close(r['v'], 0.311385219e-1, 'v')
        assert_close(r['h'], 0.657122604e4, 'h')
        assert_close(r['u'], 0.563707038e4, 'u')
        assert_close(r['s'], 0.853640523e1, 's')
        assert_close(r['cp'], 0.288569882e1, 'cp')
        assert_close(r['w'], 0.106736948e4, 'w')


# ============================================================
# Backward T(p,h) Region 1 verification (IF-97 Table 7)
# ============================================================
class TestBackwardRegion1:
    def test_p3_h500(self, engine):
        assert_close(engine.backward_T_ph_region1(3.0, 500.0), 0.391798509e3, 'T')

    def test_p80_h500(self, engine):
        assert_close(engine.backward_T_ph_region1(80.0, 500.0), 0.378108626e3, 'T')

    def test_p80_h1500(self, engine):
        assert_close(engine.backward_T_ph_region1(80.0, 1500.0), 0.611041229e3, 'T')


# ============================================================
# Backward T(p,h) Region 2 verification (IF-97 Table 24)
# ============================================================
class TestBackwardRegion2:
    def test_2a_p0001_h3000(self, engine):
        assert_close(engine.backward_T_ph_region2(0.001, 3000.0), 0.534433241e3, 'T')

    def test_2a_p3_h3000(self, engine):
        assert_close(engine.backward_T_ph_region2(3.0, 3000.0), 0.575373370e3, 'T')

    def test_2a_p3_h4000(self, engine):
        assert_close(engine.backward_T_ph_region2(3.0, 4000.0), 0.101077577e4, 'T')

    def test_2b_p5_h3500(self, engine):
        assert_close(engine.backward_T_ph_region2(5.0, 3500.0), 0.801299102e3, 'T')

    def test_2b_p5_h4000(self, engine):
        assert_close(engine.backward_T_ph_region2(5.0, 4000.0), 0.101531583e4, 'T')

    def test_2b_p25_h3500(self, engine):
        assert_close(engine.backward_T_ph_region2(25.0, 3500.0), 0.875279054e3, 'T')

    def test_2c_p40_h2700(self, engine):
        assert_close(engine.backward_T_ph_region2(40.0, 2700.0), 0.743056411e3, 'T')

    def test_2c_p60_h2700(self, engine):
        assert_close(engine.backward_T_ph_region2(60.0, 2700.0), 0.791137067e3, 'T')

    def test_2c_p60_h3200(self, engine):
        assert_close(engine.backward_T_ph_region2(60.0, 3200.0), 0.882756860e3, 'T')


# ============================================================
# Viscosity verification (IAPWS 2008)
# ============================================================
class TestViscosity:
    def test_liquid_T298_rho998(self, engine):
        mu = engine.viscosity(998.0, 298.15)
        assert_close(mu, 0.889735100e-3, 'mu(998,298.15)')

    def test_dense_T873_rho600(self, engine):
        mu = engine.viscosity(600.0, 873.15)
        assert_close(mu, 7.74301952e-5, 'mu(600,873.15)')

    def test_dilute_gas_positive(self, engine):
        mu = engine.viscosity(0.0, 500.0)
        assert mu > 0, "Dilute gas viscosity must be positive"
        assert mu < 1e-4, "Dilute gas viscosity should be small"


# ============================================================
# Thermal conductivity verification (IAPWS 2011, lambda2=0)
# ============================================================
class TestThermalConductivity:
    def test_dilute_T298(self, engine):
        k = engine.thermal_conductivity(0.0, 298.15)
        assert_close(k, 0.0184341883, 'k(0,298.15)')

    def test_liquid_T298_rho998(self, engine):
        k = engine.thermal_conductivity(998.0, 298.15)
        assert_close(k, 0.607712868, 'k(998,298.15)')

    def test_compressed_T298_rho1200(self, engine):
        k = engine.thermal_conductivity(1200.0, 298.15)
        assert_close(k, 0.799038144, 'k(1200,298.15)')

    def test_dilute_T873(self, engine):
        k = engine.thermal_conductivity(0.0, 873.15)
        assert_close(k, 0.0791034659, 'k(0,873.15)')


# ============================================================
# Consistency checks
# ============================================================
class TestConsistency:
    def test_u_equals_h_minus_pv_region1(self, engine):
        r = engine.region1_props(300.0, 3.0)
        u_calc = r['h'] - 3.0 * r['v'] * 1000.0
        assert_close(u_calc, r['u'], 'u=h-pv R1')

    def test_u_equals_h_minus_pv_region2(self, engine):
        r = engine.region2_props(700.0, 30.0)
        u_calc = r['h'] - 30.0 * r['v'] * 1000.0
        assert_close(u_calc, r['u'], 'u=h-pv R2')

    def test_forward_backward_region1(self, engine):
        T_orig = 400.0
        p = 10.0
        r = engine.region1_props(T_orig, p)
        T_back = engine.backward_T_ph_region1(p, r['h'])
        assert abs(T_back - T_orig) < 0.1

    def test_forward_backward_region2(self, engine):
        T_orig = 500.0
        p = 1.0
        r = engine.region2_props(T_orig, p)
        T_back = engine.backward_T_ph_region2(p, r['h'])
        assert abs(T_back - T_orig) < 0.1


# ============================================================
# Rankine cycle results verification
# ============================================================
@pytest.fixture(scope="module")
def results():
    path = '/app/results.json'
    assert os.path.exists(path), "results.json not found"
    with open(path) as f:
        return json.load(f)


class TestRankineCycle:

    def test_required_keys(self, results):
        for key in ['cycle_efficiency', 'net_specific_work_kj_per_kg',
                     'heat_input_kj_per_kg', 'back_work_ratio',
                     'turbine_inlet_viscosity_pa_s',
                     'turbine_inlet_conductivity_w_per_m_k']:
            assert key in results, f"Missing key: {key}"

    def test_turbine_inlet_keys(self, results):
        ti = results['turbine_inlet']
        for key in ['T', 'p', 'h', 's']:
            assert key in ti, f"Missing turbine_inlet.{key}"

    def test_condenser_outlet_keys(self, results):
        co = results['condenser_outlet']
        for key in ['T', 'p', 'h', 's', 'v']:
            assert key in co, f"Missing condenser_outlet.{key}"

    def test_efficiency_physical_bounds(self, results):
        eta = results['cycle_efficiency']
        assert 0.25 < eta < 0.55, f"Cycle efficiency {eta} out of physical range"

    def test_net_work_positive(self, results):
        assert results['net_specific_work_kj_per_kg'] > 0

    def test_back_work_ratio(self, results):
        bwr = results['back_work_ratio']
        assert 0 < bwr < 0.05, f"Back work ratio {bwr} should be small for steam"

    def test_turbine_inlet_matches_config(self, results):
        ti = results['turbine_inlet']
        assert_close(ti['T'], 800.0, 'turbine_inlet.T')
        assert_close(ti['p'], 10.0, 'turbine_inlet.p')

    def test_condenser_at_correct_pressure(self, results):
        co = results['condenser_outlet']
        assert_close(co['p'], 0.008, 'condenser_outlet.p')

    def test_cycle_energy_balance(self, results):
        """net_work = heat_input * efficiency"""
        w_net = results['net_specific_work_kj_per_kg']
        q_in = results['heat_input_kj_per_kg']
        eta = results['cycle_efficiency']
        assert abs(w_net - q_in * eta) / w_net < 1e-6, "Energy balance: w_net != q_in * eta"

    def test_cycle_cross_validation(self, engine, results):
        """Cross-validate cycle results using the corrected engine."""
        # Turbine inlet (Region 2: T=800K, p=10MPa)
        r2 = engine.region2_props(800.0, 10.0)
        assert_close(results['turbine_inlet']['h'], r2['h'], 'turbine_inlet.h')
        assert_close(results['turbine_inlet']['s'], r2['s'], 'turbine_inlet.s')

        # Condenser outlet: saturated liquid at p=0.008 MPa
        Tsat = engine.saturation_temperature(0.008)
        r1_sat = engine.region1_props(Tsat, 0.008)
        assert_close(results['condenser_outlet']['T'], Tsat, 'condenser_outlet.T')
        assert_close(results['condenser_outlet']['h'], r1_sat['h'], 'condenser_outlet.h')

    def test_transport_at_turbine_inlet(self, engine, results):
        """Verify transport properties at turbine inlet."""
        r2 = engine.region2_props(800.0, 10.0)
        rho = 1.0 / r2['v']
        mu = engine.viscosity(rho, 800.0)
        k = engine.thermal_conductivity(rho, 800.0)
        assert_close(results['turbine_inlet_viscosity_pa_s'], mu, 'viscosity')
        assert_close(results['turbine_inlet_conductivity_w_per_m_k'], k, 'conductivity')
