"""
Tests for IAPWS-IF97 steam property calculator.
Verifies shared library build, ctypes integration, and numerical accuracy
against published IAPWS verification values from IF97-Rev tables.

"""

import subprocess
import os
import pytest

RTOL = 5e-7


def run_if97(*args):
    """Run the /app/if97 CLI and return stdout."""
    cmd = ["/app/if97"] + [str(a) for a in args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "if97 failed: {}".format(result.stderr)
    return result.stdout.strip()


def parse_props(output):
    """Parse 7 space-separated property values."""
    vals = output.split()
    assert len(vals) == 7, "Expected 7 values, got {}: {}".format(len(vals), output)
    return [float(v) for v in vals]


def approx(expected, rel=RTOL):
    return pytest.approx(expected, rel=rel)


class TestSharedLibrary:
    """Verify the C shared library was built and is loadable."""

    def test_so_file_exists(self):
        assert os.path.isfile("/app/src/libif97.so"), \
            "libif97.so not found at /app/src/"

    def test_so_is_loadable(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        assert lib is not None

    def test_exports_gamma1(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        fn = getattr(lib, "if97_gamma1", None)
        assert fn is not None, "if97_gamma1 not exported"

    def test_exports_gamma2_ideal(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        fn = getattr(lib, "if97_gamma2_ideal", None)
        assert fn is not None, "if97_gamma2_ideal not exported"

    def test_exports_gamma2_res(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        fn = getattr(lib, "if97_gamma2_res", None)
        assert fn is not None, "if97_gamma2_res not exported"

    def test_exports_psat(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        fn = getattr(lib, "if97_psat_t", None)
        assert fn is not None, "if97_psat_t not exported"

    def test_exports_tsat(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        fn = getattr(lib, "if97_tsat_p", None)
        assert fn is not None, "if97_tsat_p not exported"

    def test_exports_p23(self):
        import ctypes
        lib = ctypes.CDLL("/app/src/libif97.so")
        fn = getattr(lib, "if97_p23_t", None)
        assert fn is not None, "if97_p23_t not exported"


class TestRegionDetermination:
    def test_region1_low_T_low_P(self):
        assert run_if97("region", 300, 3) == "1"

    def test_region1_high_P(self):
        assert run_if97("region", 300, 80) == "1"

    def test_region1_high_T(self):
        assert run_if97("region", 500, 3) == "1"

    def test_region2_low_P_low_T(self):
        assert run_if97("region", 300, 0.0035) == "2"

    def test_region2_high_T(self):
        assert run_if97("region", 700, 0.0035) == "2"

    def test_region2_high_T_high_P(self):
        assert run_if97("region", 700, 30) == "2"

    def test_region3(self):
        assert run_if97("region", 650, 25.5837018) == "3"

    def test_region5_low_P(self):
        assert run_if97("region", 1500, 0.5) == "5"

    def test_region5_high_P(self):
        assert run_if97("region", 1500, 30) == "5"

    def test_region5_very_high_T(self):
        assert run_if97("region", 2000, 30) == "5"


class TestSaturation:
    def test_psat_500K(self):
        val = float(run_if97("satT", 500))
        assert val == approx(2.63889776)

    def test_psat_300K(self):
        val = float(run_if97("satT", 300))
        assert val == approx(0.00353658941301)

    def test_psat_600K(self):
        val = float(run_if97("satT", 600))
        assert val == approx(12.3443145784)

    def test_tsat_10MPa(self):
        val = float(run_if97("satP", 10))
        assert val == approx(584.149488)

    def test_tsat_1MPa(self):
        val = float(run_if97("satP", 1))
        assert val == approx(453.035632)

    def test_tsat_0_1MPa(self):
        val = float(run_if97("satP", 0.1))
        assert val == approx(372.755919)


class TestRegion1Forward:
    """IAPWS-IF97 Table 5 verification."""

    def test_v_300_3(self):
        vals = parse_props(run_if97("props", 300, 3))
        assert vals[0] == approx(0.00100215168)

    def test_h_300_3(self):
        vals = parse_props(run_if97("props", 300, 3))
        assert vals[1] == approx(115.331273)

    def test_u_300_3(self):
        vals = parse_props(run_if97("props", 300, 3))
        assert vals[2] == approx(112.324818)

    def test_s_300_80(self):
        vals = parse_props(run_if97("props", 300, 80))
        assert vals[3] == approx(0.368563852)

    def test_cp_300_80(self):
        vals = parse_props(run_if97("props", 300, 80))
        assert vals[4] == approx(4.01008987)

    def test_cv_300_80(self):
        vals = parse_props(run_if97("props", 300, 80))
        assert vals[5] == approx(3.91736606)

    def test_w_500_3(self):
        vals = parse_props(run_if97("props", 500, 3))
        assert vals[6] == approx(1240.71337)

    def test_h_500_3(self):
        vals = parse_props(run_if97("props", 500, 3))
        assert vals[1] == approx(975.542239)

    def test_s_500_3(self):
        vals = parse_props(run_if97("props", 500, 3))
        assert vals[3] == approx(2.58041912)


class TestRegion2Forward:
    """IAPWS-IF97 Table 15 verification."""

    def test_v_700_30(self):
        vals = parse_props(run_if97("props", 700, 30))
        assert vals[0] == approx(0.00542946619)

    def test_h_700_30(self):
        vals = parse_props(run_if97("props", 700, 30))
        assert vals[1] == approx(2631.49474)

    def test_u_700_30(self):
        vals = parse_props(run_if97("props", 700, 30))
        assert vals[2] == approx(2468.61076)

    def test_s_700_0035(self):
        vals = parse_props(run_if97("props", 700, 0.0035))
        assert vals[3] == approx(10.1749996)

    def test_cp_700_0035(self):
        vals = parse_props(run_if97("props", 700, 0.0035))
        assert vals[4] == approx(2.08141274)

    def test_cv_700_0035(self):
        vals = parse_props(run_if97("props", 700, 0.0035))
        assert vals[5] == approx(1.61978333)

    def test_w_300_0035(self):
        vals = parse_props(run_if97("props", 300, 0.0035))
        assert vals[6] == approx(427.920172)

    def test_v_300_0035(self):
        vals = parse_props(run_if97("props", 300, 0.0035))
        assert vals[0] == approx(39.4913866)

    def test_h_300_0035(self):
        vals = parse_props(run_if97("props", 300, 0.0035))
        assert vals[1] == approx(2549.91145)


class TestRegion3Forward:
    """IAPWS-IF97 Table 33 verification via (T, P) interface.
    T=650K, P=25.5837018 corresponds to rho=500 kg/m3.
    Region 3 tested with relaxed tolerance due to density inversion."""

    def test_v_650_25p58(self):
        vals = parse_props(run_if97("props", 650, 25.5837018))
        assert vals[0] == approx(0.002, rel=5e-4)

    def test_h_650_25p58(self):
        vals = parse_props(run_if97("props", 650, 25.5837018))
        assert vals[1] == approx(1863.43019, rel=5e-4)

    def test_u_650_25p58(self):
        vals = parse_props(run_if97("props", 650, 25.5837018))
        assert vals[2] == approx(1812.26279, rel=5e-4)

    def test_s_650_25p58(self):
        vals = parse_props(run_if97("props", 650, 25.5837018))
        assert vals[3] == approx(4.05427273, rel=5e-4)

    def test_region3_another_point(self):
        vals = parse_props(run_if97("props", 630, 50))
        assert vals[0] == approx(0.001470853100, rel=5e-3)

    def test_region3_v_high_P(self):
        vals = parse_props(run_if97("props", 710, 50))
        assert vals[0] == approx(0.002204728587, rel=5e-3)


class TestRegion5Forward:
    """IAPWS-IF97 Table 42 verification."""

    def test_v_1500_05(self):
        vals = parse_props(run_if97("props", 1500, 0.5))
        assert vals[0] == approx(1.38455090)

    def test_h_1500_05(self):
        vals = parse_props(run_if97("props", 1500, 0.5))
        assert vals[1] == approx(5219.76855)

    def test_u_1500_05(self):
        vals = parse_props(run_if97("props", 1500, 0.5))
        assert vals[2] == approx(4527.49310)

    def test_s_1500_30(self):
        vals = parse_props(run_if97("props", 1500, 30))
        assert vals[3] == approx(7.72970133)

    def test_cp_1500_30(self):
        vals = parse_props(run_if97("props", 1500, 30))
        assert vals[4] == approx(2.72724317)

    def test_cv_1500_30(self):
        vals = parse_props(run_if97("props", 1500, 30))
        assert vals[5] == approx(2.19274829)

    def test_w_2000_30(self):
        vals = parse_props(run_if97("props", 2000, 30))
        assert vals[6] == approx(1067.36948)

    def test_v_2000_30(self):
        vals = parse_props(run_if97("props", 2000, 30))
        assert vals[0] == approx(0.0311385219)

    def test_h_2000_30(self):
        vals = parse_props(run_if97("props", 2000, 30))
        assert vals[1] == approx(6571.22604)


class TestBackward1TPh:
    """IAPWS-IF97 Table 7 verification."""

    def test_3_500(self):
        val = float(run_if97("backward_ph", 3, 500))
        assert val == approx(391.798509)

    def test_80_1500(self):
        val = float(run_if97("backward_ph", 80, 1500))
        assert val == approx(611.041229)

    def test_80_500(self):
        val = float(run_if97("backward_ph", 80, 500))
        assert val == approx(378.108626)


class TestBackward1TPs:
    """IAPWS-IF97 Table 9 verification."""

    def test_3_05(self):
        val = float(run_if97("backward_ps", 3, 0.5))
        assert val == approx(307.842258)

    def test_80_3(self):
        val = float(run_if97("backward_ps", 80, 3))
        assert val == approx(565.899909)

    def test_80_05(self):
        val = float(run_if97("backward_ps", 80, 0.5))
        assert val == approx(309.979785)


class TestBackward2TPh:
    """IAPWS-IF97 Tables 24, 25, 29 verification."""

    def test_2a_0001_3000(self):
        val = float(run_if97("backward_ph", 0.001, 3000))
        assert val == approx(534.433241)

    def test_2a_3_4000(self):
        val = float(run_if97("backward_ph", 3, 4000))
        assert val == approx(1010.77577)

    def test_2b_5_4000(self):
        val = float(run_if97("backward_ph", 5, 4000))
        assert val == approx(1015.31583)

    def test_2b_25_3500(self):
        val = float(run_if97("backward_ph", 25, 3500))
        assert val == approx(875.279054)

    def test_2c_40_2700(self):
        val = float(run_if97("backward_ph", 40, 2700))
        assert val == approx(743.056411)

    def test_2c_60_3200(self):
        val = float(run_if97("backward_ph", 60, 3200))
        assert val == approx(882.756860)


class TestBackward2TPs:
    """IAPWS-IF97 Tables 25, 26, 27 verification."""

    def test_2a_01_75(self):
        val = float(run_if97("backward_ps", 0.1, 7.5))
        assert val == approx(399.517097)

    def test_2a_25_8(self):
        val = float(run_if97("backward_ps", 2.5, 8))
        assert val == approx(1039.84917)

    def test_2b_8_6(self):
        val = float(run_if97("backward_ps", 8, 6))
        assert val == approx(600.484040)

    def test_2b_90_6(self):
        val = float(run_if97("backward_ps", 90, 6))
        assert val == approx(1038.01126)

    def test_2c_20_575(self):
        val = float(run_if97("backward_ps", 20, 5.75))
        assert val == approx(697.992849)

    def test_2c_80_575(self):
        val = float(run_if97("backward_ps", 80, 5.75))
        assert val == approx(949.017998)
