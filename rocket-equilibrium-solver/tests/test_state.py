
"""
Verification tests for H2/O2 chemical equilibrium rocket performance solver.
Tests Fortran library integration AND golden performance values from
NASA CEA RP-1311 Example 8: H2(L)/O2(L) at o/f=5.55157, Pc=53.3172 bar.
"""

import json
import os
import glob
import ctypes as ct
import pytest

# ===========================================================================
# CEA Example 8 golden reference values
# ===========================================================================
GOLDEN_CHAMBER_T = 3383.845       # K
GOLDEN_CHAMBER_MW = 12.716        # g/mol
GOLDEN_CHAMBER_MOLES = {
    "H":   0.033498,
    "H2":  0.29479,
    "H2O": 0.63456,
    "OH":  0.033341,
    "O":   0.0020678,
    "O2":  0.0017218,
}
GOLDEN_THROAT_T = 3185.673        # K
GOLDEN_THROAT_P = 30.655          # bar
GOLDEN_CSTAR = 2332.34            # m/s
GOLDEN_ISP_VAC = {
    25: 4348.510,                 # m/s
    50: 4487.303,                 # m/s
    75: 4554.913,                 # m/s
}


@pytest.fixture(scope="module")
def results():
    """Load solver output."""
    path = "/app/results.json"
    assert os.path.isfile(path), (
        "results.json not found — solver must write /app/results.json"
    )
    with open(path) as f:
        data = json.load(f)
    return data


def _rel(actual, expected):
    return abs(actual - expected) / abs(expected)


# ===========================================================================
# Fortran shared library integration tests
# ===========================================================================

class TestFortranIntegration:
    """Verify that the solver compiles and uses the Fortran thermo library."""

    def _find_so(self):
        patterns = ["/app/libthermo*.so", "/app/thermo*.so",
                    "/app/*.so"]
        for p in patterns:
            found = glob.glob(p)
            if found:
                return found[0]
        return None

    def test_shared_library_exists(self):
        so = self._find_so()
        assert so is not None, (
            "No compiled shared library (.so) found in /app/. "
            "thermo_eval.f90 must be compiled to a shared library."
        )

    def test_solver_uses_ctypes(self):
        assert os.path.isfile("/app/rocket_eq.py"), "rocket_eq.py not found"
        with open("/app/rocket_eq.py") as f:
            code = f.read()
        assert "ctypes" in code, (
            "rocket_eq.py must import ctypes to interface with the Fortran library"
        )
        assert "CDLL" in code or "cdll" in code, (
            "rocket_eq.py must load the shared library via ctypes.CDLL"
        )

    def test_library_exports_functions(self):
        so = self._find_so()
        assert so is not None, "No .so file"
        lib = ct.CDLL(so)
        required = ["thermo_cp_over_r", "thermo_h_over_rt",
                     "thermo_s_over_r", "thermo_g_over_rt"]
        for name in required:
            try:
                getattr(lib, name)
            except AttributeError:
                pytest.fail(f"Function '{name}' not exported by {so}")

    def test_library_computes_correctly(self):
        """Call the compiled library with known trivial coefficients."""
        so = self._find_so()
        assert so is not None, "No .so file"
        lib = ct.CDLL(so)
        _dp = ct.POINTER(ct.c_double)
        lib.thermo_cp_over_r.restype = ct.c_double
        lib.thermo_cp_over_r.argtypes = [_dp, ct.c_double, ct.c_double, ct.c_double]
        # a = [0, 0, 2.5, 0, 0, 0, 0] → Cp/R = a3 = 2.5 at any T
        a = (ct.c_double * 7)(0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 0.0)
        result = lib.thermo_cp_over_r(a, 0.0, 0.0, 1000.0)
        assert abs(result - 2.5) < 1e-10, (
            f"thermo_cp_over_r([0,0,2.5,0,0,0,0], 0, 0, 1000) = {result}, expected 2.5"
        )

    def test_h_over_rt_with_b1(self):
        """Verify H/(RT) correctly includes integration constant b1."""
        so = self._find_so()
        assert so is not None, "No .so file"
        lib = ct.CDLL(so)
        _dp = ct.POINTER(ct.c_double)
        lib.thermo_h_over_rt.restype = ct.c_double
        lib.thermo_h_over_rt.argtypes = [_dp, ct.c_double, ct.c_double, ct.c_double]
        # a = [0,0,3.0,0,0,0,0], b1=1000.0, T=500.0
        # H/(RT) = a3 + b1/T = 3.0 + 1000/500 = 5.0
        a = (ct.c_double * 7)(0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0)
        result = lib.thermo_h_over_rt(a, 1000.0, 0.0, 500.0)
        assert abs(result - 5.0) < 1e-10, (
            f"thermo_h_over_rt result = {result}, expected 5.0"
        )


# ===========================================================================
# Chamber conditions
# ===========================================================================

def test_chamber_temperature(results):
    T = results["chamber"]["temperature_k"]
    err = _rel(T, GOLDEN_CHAMBER_T)
    assert err < 0.005, (
        f"Chamber T = {T:.1f} K, expected {GOLDEN_CHAMBER_T} K "
        f"(rel err {err:.4f}, limit 0.5%)"
    )


def test_chamber_molecular_weight(results):
    MW = results["chamber"]["molecular_weight"]
    err = _rel(MW, GOLDEN_CHAMBER_MW)
    assert err < 0.01, (
        f"Chamber MW = {MW:.3f}, expected {GOLDEN_CHAMBER_MW} "
        f"(rel err {err:.4f}, limit 1%)"
    )


@pytest.mark.parametrize("species,expected", list(GOLDEN_CHAMBER_MOLES.items()))
def test_chamber_mole_fraction(results, species, expected):
    moles = results["chamber"]["mole_fractions"]
    actual = moles.get(species, 0.0)
    err = _rel(actual, expected)
    assert err < 0.05, (
        f"x({species}) = {actual:.6g}, expected {expected:.6g} "
        f"(rel err {err:.4f}, limit 5%)"
    )


# ===========================================================================
# Throat conditions
# ===========================================================================

def test_throat_temperature(results):
    T = results["throat"]["temperature_k"]
    err = _rel(T, GOLDEN_THROAT_T)
    assert err < 0.01, (
        f"Throat T = {T:.1f} K, expected {GOLDEN_THROAT_T} K "
        f"(rel err {err:.4f}, limit 1%)"
    )


def test_throat_pressure(results):
    P = results["throat"]["pressure_bar"]
    err = _rel(P, GOLDEN_THROAT_P)
    assert err < 0.015, (
        f"Throat P = {P:.2f} bar, expected {GOLDEN_THROAT_P} bar "
        f"(rel err {err:.4f}, limit 1.5%)"
    )


# ===========================================================================
# Performance parameters
# ===========================================================================

def test_characteristic_velocity(results):
    cs = results["performance"]["c_star_m_per_s"]
    err = _rel(cs, GOLDEN_CSTAR)
    assert err < 0.003, (
        f"c* = {cs:.2f} m/s, expected {GOLDEN_CSTAR} m/s "
        f"(rel err {err:.4f}, limit 0.3%)"
    )


@pytest.mark.parametrize("area_ratio,expected_isp", list(GOLDEN_ISP_VAC.items()))
def test_vacuum_isp(results, area_ratio, expected_isp):
    exits = results["performance"]["exit_conditions"]
    match = [e for e in exits if e["area_ratio"] == area_ratio]
    assert len(match) == 1, (
        f"No exit condition found for area ratio {area_ratio}"
    )
    isp = match[0]["isp_vacuum_m_per_s"]
    err = _rel(isp, expected_isp)
    assert err < 0.005, (
        f"Isp_vac at Ae/At={area_ratio}: {isp:.1f} m/s, "
        f"expected {expected_isp} m/s (rel err {err:.4f}, limit 0.5%)"
    )


# ===========================================================================
# Structural checks
# ===========================================================================

def test_results_schema(results):
    assert "chamber" in results
    assert "throat" in results
    assert "performance" in results
    assert "temperature_k" in results["chamber"]
    assert "mole_fractions" in results["chamber"]
    assert "c_star_m_per_s" in results["performance"]
    assert "exit_conditions" in results["performance"]
    assert len(results["performance"]["exit_conditions"]) == 3


def test_mole_fractions_sum_to_one(results):
    moles = results["chamber"]["mole_fractions"]
    total = sum(moles.values())
    assert abs(total - 1.0) < 0.01, (
        f"Mole fractions sum to {total:.6f}, expected ~1.0"
    )


def test_all_species_present(results):
    """All product species from problem.json must appear in output."""
    expected = {"H", "H2", "O", "O2", "OH", "H2O", "HO2", "H2O2", "O3"}
    actual = set(results["chamber"]["mole_fractions"].keys())
    missing = expected - actual
    assert not missing, f"Missing species in mole_fractions: {missing}"


def test_exit_conditions_sorted(results):
    """Exit conditions must be sorted by ascending area ratio."""
    exits = results["performance"]["exit_conditions"]
    ratios = [e["area_ratio"] for e in exits]
    assert ratios == sorted(ratios), (
        f"Exit conditions not sorted by area ratio: {ratios}"
    )
