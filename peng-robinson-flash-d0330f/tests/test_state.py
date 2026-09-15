
"""
Comprehensive tests for cubic EOS toolkit: C library, PR bug fixes, SRK,
a_res, departure functions, load_params, flash, bubble/dew.
"""

import sys
import math
import os
import ctypes
import pytest
import numpy as np

sys.path.insert(0, "/app")

R_GAS = 8.314462618153241

# ---------------------------------------------------------------------------
# Component database (same data as /app/params.toml)
# ---------------------------------------------------------------------------
NAMES = ["methane", "ethane", "propane", "n-butane", "n-pentane"]
TC = [190.564, 305.32, 369.83, 425.12, 469.70]
PC = [4599200.0, 4872200.0, 4248000.0, 3796000.0, 3370000.0]
OMEGA = [0.01142, 0.09952, 0.15229, 0.20017, 0.25148]
KIJ_FULL = [
    [0.0, 0.0, 0.01, 0.02, 0.02],
    [0.0, 0.0, 0.0, 0.01, 0.01],
    [0.01, 0.0, 0.0, 0.0, 0.0],
    [0.02, 0.01, 0.0, 0.0, 0.0],
    [0.02, 0.01, 0.0, 0.0, 0.0],
]


# ===== Independent oracle implementations ===================================

def _oracle_pr_params(T, idx):
    nc = len(idx)
    Tc = [TC[i] for i in idx]
    Pc = [PC[i] for i in idx]
    om = [OMEGA[i] for i in idx]
    kij = [[KIJ_FULL[i][j] for j in idx] for i in idx]
    bi = [0.07780 * R_GAS * Tc[i] / Pc[i] for i in range(nc)]
    aci = [0.45724 * R_GAS ** 2 * Tc[i] ** 2 / Pc[i] for i in range(nc)]
    alpha = []
    for i in range(nc):
        Tr = T / Tc[i]
        kappa = 0.37464 + 1.54226 * om[i] - 0.26992 * om[i] ** 2
        alpha.append((1.0 + kappa * (1.0 - math.sqrt(Tr))) ** 2)
    ai = [aci[i] * alpha[i] for i in range(nc)]
    return bi, ai, kij


def _oracle_srk_params(T, idx):
    nc = len(idx)
    Tc = [TC[i] for i in idx]
    Pc = [PC[i] for i in idx]
    om = [OMEGA[i] for i in idx]
    kij = [[KIJ_FULL[i][j] for j in idx] for i in idx]
    bi = [0.08664 * R_GAS * Tc[i] / Pc[i] for i in range(nc)]
    aci = [0.42748 * R_GAS ** 2 * Tc[i] ** 2 / Pc[i] for i in range(nc)]
    alpha = []
    for i in range(nc):
        Tr = T / Tc[i]
        kappa = 0.480 + 1.574 * om[i] - 0.176 * om[i] ** 2
        alpha.append((1.0 + kappa * (1.0 - math.sqrt(Tr))) ** 2)
    ai = [aci[i] * alpha[i] for i in range(nc)]
    return bi, ai, kij


def _mix(x, bi, ai, kij):
    nc = len(x)
    b_mix = sum(x[i] * bi[i] for i in range(nc))
    a_mix = 0.0
    for i in range(nc):
        for j in range(nc):
            a_mix += x[i] * x[j] * math.sqrt(ai[i] * ai[j]) * (1.0 - kij[i][j])
    return a_mix, b_mix


def oracle_a_res_pr(V, T, z, idx):
    n = sum(z)
    x = [zi / n for zi in z]
    bi, ai, kij = _oracle_pr_params(T, idx)
    a_mix, b_mix = _mix(x, bi, ai, kij)
    nb = n * b_mix
    sqrt2 = math.sqrt(2.0)
    term1 = -math.log(1.0 - nb / V)
    term2 = (-a_mix / (2.0 * sqrt2 * b_mix * R_GAS * T)
             * math.log((V + nb * (1.0 + sqrt2)) / (V + nb * (1.0 - sqrt2))))
    return term1 + term2


def oracle_a_res_srk(V, T, z, idx):
    n = sum(z)
    x = [zi / n for zi in z]
    bi, ai, kij = _oracle_srk_params(T, idx)
    a_mix, b_mix = _mix(x, bi, ai, kij)
    nb = n * b_mix
    term1 = -math.log(1.0 - nb / V)
    term2 = -a_mix / (b_mix * R_GAS * T) * math.log(1.0 + nb / V)
    return term1 + term2


def oracle_pressure_pr(V, T, z, idx):
    n = sum(z)
    x = [zi / n for zi in z]
    bi, ai, kij = _oracle_pr_params(T, idx)
    a_mix, b_mix = _mix(x, bi, ai, kij)
    nb = n * b_mix
    denom = V * (V + nb) + nb * (V - nb)
    return n * R_GAS * T / (V - nb) - n ** 2 * a_mix / denom


def oracle_pressure_srk(V, T, z, idx):
    n = sum(z)
    x = [zi / n for zi in z]
    bi, ai, kij = _oracle_srk_params(T, idx)
    a_mix, b_mix = _mix(x, bi, ai, kij)
    nb = n * b_mix
    return n * R_GAS * T / (V - nb) - n ** 2 * a_mix / (V * (V + nb))


# ===== EOS constructors =====================================================

def _make_pr(indices):
    from eos_engine import PengRobinson
    tc = [TC[i] for i in indices]
    pc = [PC[i] for i in indices]
    om = [OMEGA[i] for i in indices]
    kij = [[KIJ_FULL[i][j] for j in indices] for i in indices]
    return PengRobinson(tc, pc, om, kij)


def _make_srk(indices):
    from eos_engine import SRK
    tc = [TC[i] for i in indices]
    pc = [PC[i] for i in indices]
    om = [OMEGA[i] for i in indices]
    kij = [[KIJ_FULL[i][j] for j in indices] for i in indices]
    return SRK(tc, pc, om, kij)


# ===== C Library tests (direct ctypes verification) ========================

class TestCLibrary:
    """Verify the C shared library exists, loads, and works correctly."""

    def test_libcubic_exists(self):
        assert os.path.exists("/app/libcubic.so"), \
            "libcubic.so must exist at /app/libcubic.so"

    def test_libcubic_loads_and_exports(self):
        lib = ctypes.CDLL("/app/libcubic.so")
        lib.eos_pressure.restype = ctypes.c_double
        lib.eos_solve_Z.restype = ctypes.c_int

    def test_c_pressure_ideal(self):
        """With a=0, b=0: P = nRT/V (ideal gas check)."""
        lib = ctypes.CDLL("/app/libcubic.so")
        lib.eos_pressure.restype = ctypes.c_double
        lib.eos_pressure.argtypes = [ctypes.c_double] * 8
        P = lib.eos_pressure(0.01, 300.0, 1.0, 0.0, 0.0, 1.0, 0.0, R_GAS)
        P_exp = R_GAS * 300.0 / 0.01
        assert abs(P - P_exp) / P_exp < 1e-10

    def test_c_pressure_multimole(self):
        """Pressure must use n-squared scaling of attractive term."""
        lib = ctypes.CDLL("/app/libcubic.so")
        lib.eos_pressure.restype = ctypes.c_double
        lib.eos_pressure.argtypes = [ctypes.c_double] * 8
        d1 = 1.0 + math.sqrt(2.0)
        d2 = 1.0 - math.sqrt(2.0)
        V, T, n = 0.01, 300.0, 2.5
        a_mix, b_mix = 0.3, 4e-5
        P = lib.eos_pressure(V, T, n, a_mix, b_mix, d1, d2, R_GAS)
        nb = n * b_mix
        P_exp = (n * R_GAS * T / (V - nb)
                 - n * n * a_mix / ((V + nb * d1) * (V + nb * d2)))
        assert abs(P - P_exp) / abs(P_exp) < 1e-10, \
            f"C pressure n^2 check: {P} vs {P_exp}"

    def test_c_solve_z_single_root(self):
        """At low A,B the cubic should give one root near 1."""
        lib = ctypes.CDLL("/app/libcubic.so")
        lib.eos_solve_Z.restype = ctypes.c_int
        lib.eos_solve_Z.argtypes = [
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
        ]
        d1 = 1.0 + math.sqrt(2.0)
        d2 = 1.0 - math.sqrt(2.0)
        roots = (ctypes.c_double * 3)()
        nroots = lib.eos_solve_Z(0.01, 0.001, d1, d2, roots)
        assert nroots >= 1
        Z = max(roots[i] for i in range(nroots))
        assert abs(Z - 1.0) < 0.05, f"Z at low density: {Z}"

    def test_c_solve_z_srk(self):
        """SRK cubic solver test with delta1=1, delta2=0."""
        lib = ctypes.CDLL("/app/libcubic.so")
        lib.eos_solve_Z.restype = ctypes.c_int
        lib.eos_solve_Z.argtypes = [
            ctypes.c_double, ctypes.c_double,
            ctypes.c_double, ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
        ]
        roots = (ctypes.c_double * 3)()
        nroots = lib.eos_solve_Z(0.5, 0.05, 1.0, 0.0, roots)
        assert nroots >= 1
        for i in range(nroots):
            assert roots[i] > 0.05, "All roots must exceed B"


# ===== PR bug-fix verification: a_res ========================================

class TestPR_a_res:
    def test_pure_methane(self):
        idx = [0]
        eos = _make_pr(idx)
        V, T, z = 1e-3, 200.0, [1.0]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_pr(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"PR a_res CH4: {got} vs {ref}"

    def test_pure_propane(self):
        idx = [2]
        eos = _make_pr(idx)
        V, T, z = 2e-4, 300.0, [1.0]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_pr(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"PR a_res C3: {got} vs {ref}"

    def test_pure_pentane(self):
        idx = [4]
        eos = _make_pr(idx)
        V, T, z = 3e-4, 350.0, [1.0]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_pr(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"PR a_res nC5: {got} vs {ref}"

    def test_binary_with_kij(self):
        idx = [0, 2]
        eos = _make_pr(idx)
        V, T, z = 1e-3, 280.0, [0.4, 0.6]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_pr(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"PR a_res C1+C3: {got} vs {ref}"

    def test_binary_larger_kij(self):
        idx = [0, 4]
        eos = _make_pr(idx)
        V, T, z = 8e-4, 260.0, [0.3, 0.7]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_pr(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"PR a_res C1+nC5: {got} vs {ref}"

    def test_five_component(self):
        idx = list(range(5))
        eos = _make_pr(idx)
        V, T, z = 2e-3, 280.0, [0.15, 0.25, 0.25, 0.20, 0.15]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_pr(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"PR a_res 5-comp: {got} vs {ref}"


# ===== PR pressure against oracle ==========================================

class TestPR_Pressure:
    def test_pure_methane(self):
        idx = [0]
        eos = _make_pr(idx)
        V, T, z = 1e-3, 200.0, [1.0]
        P = eos.pressure(V, T, z)
        P_ref = oracle_pressure_pr(V, T, z, idx)
        assert abs(P - P_ref) / abs(P_ref) < 1e-10, f"{P} vs {P_ref}"

    def test_binary_mixture(self):
        idx = [1, 2]
        eos = _make_pr(idx)
        V, T, z = 1e-3, 300.0, [0.5, 0.5]
        P = eos.pressure(V, T, z)
        P_ref = oracle_pressure_pr(V, T, z, idx)
        assert abs(P - P_ref) / abs(P_ref) < 1e-10, f"{P} vs {P_ref}"

    def test_five_component(self):
        idx = list(range(5))
        eos = _make_pr(idx)
        V, T, z = 2e-3, 280.0, [0.15, 0.25, 0.25, 0.20, 0.15]
        P = eos.pressure(V, T, z)
        P_ref = oracle_pressure_pr(V, T, z, idx)
        assert abs(P - P_ref) / abs(P_ref) < 1e-10, f"{P} vs {P_ref}"

    def test_multimole(self):
        """Verify correct n-squared scaling through Python interface."""
        idx = [0, 1]
        eos = _make_pr(idx)
        V, T, z = 5e-3, 300.0, [2.0, 3.0]
        P = eos.pressure(V, T, z)
        P_ref = oracle_pressure_pr(V, T, z, idx)
        assert abs(P - P_ref) / abs(P_ref) < 1e-10, \
            f"Multimole pressure: {P} vs {P_ref}"


# ===== SRK implementation ===================================================

class TestSRK_a_res:
    def test_pure_ethane(self):
        idx = [1]
        eos = _make_srk(idx)
        V, T, z = 1e-3, 300.0, [1.0]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_srk(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"SRK a_res C2: {got} vs {ref}"

    def test_pure_pentane(self):
        idx = [4]
        eos_pr = _make_pr(idx)
        eos_srk = _make_srk(idx)
        V, T, z = 3e-4, 350.0, [1.0]
        got_srk = eos_srk.a_res(V, T, z)
        ref_srk = oracle_a_res_srk(V, T, z, idx)
        assert abs(got_srk - ref_srk) / abs(ref_srk) < 1e-6
        got_pr = eos_pr.a_res(V, T, z)
        assert abs(got_pr - got_srk) / abs(got_pr) > 1e-4, \
            "PR and SRK should give different a_res"

    def test_binary_with_kij(self):
        idx = [0, 4]
        eos = _make_srk(idx)
        V, T, z = 8e-4, 260.0, [0.3, 0.7]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_srk(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"SRK a_res C1+nC5: {got} vs {ref}"

    def test_five_component(self):
        idx = list(range(5))
        eos = _make_srk(idx)
        V, T, z = 2e-3, 280.0, [0.15, 0.25, 0.25, 0.20, 0.15]
        got = eos.a_res(V, T, z)
        ref = oracle_a_res_srk(V, T, z, idx)
        assert abs(got - ref) / abs(ref) < 1e-6, f"SRK a_res 5-comp: {got} vs {ref}"


class TestSRK_Pressure:
    def test_pure_propane(self):
        idx = [2]
        eos = _make_srk(idx)
        V, T, z = 2e-4, 300.0, [1.0]
        P = eos.pressure(V, T, z)
        P_ref = oracle_pressure_srk(V, T, z, idx)
        assert abs(P - P_ref) / abs(P_ref) < 1e-10, f"{P} vs {P_ref}"

    def test_binary(self):
        idx = [1, 2]
        eos = _make_srk(idx)
        V, T, z = 1e-3, 300.0, [0.5, 0.5]
        P = eos.pressure(V, T, z)
        P_ref = oracle_pressure_srk(V, T, z, idx)
        assert abs(P - P_ref) / abs(P_ref) < 1e-10, f"{P} vs {P_ref}"


# ===== Volume roundtrip =====================================================

class TestVolume:
    def test_pr_roundtrip_liquid(self):
        eos = _make_pr([2])
        P, T, z = 2.0e6, 300.0, [1.0]
        V = eos.volume(P, T, z, phase='liquid')
        assert V > 0
        P_back = eos.pressure(V, T, z)
        assert abs(P_back - P) / abs(P) < 1e-10

    def test_pr_roundtrip_vapor(self):
        eos = _make_pr([0])
        V_true = 0.01
        T = 300.0
        z = [1.0]
        P = eos.pressure(V_true, T, z)
        V_calc = eos.volume(P, T, z, phase='vapor')
        P_back = eos.pressure(V_calc, T, z)
        assert abs(P_back - P) / abs(P) < 1e-10

    def test_pr_roundtrip_mixture(self):
        eos = _make_pr([0, 1, 2])
        V_true = 0.005
        T = 350.0
        z = [0.3, 0.3, 0.4]
        P = eos.pressure(V_true, T, z)
        V_calc = eos.volume(P, T, z, phase='vapor')
        P_back = eos.pressure(V_calc, T, z)
        assert abs(P_back - P) / abs(P) < 1e-10

    def test_srk_roundtrip_liquid(self):
        eos = _make_srk([2])
        P, T, z = 2.0e6, 300.0, [1.0]
        V = eos.volume(P, T, z, phase='liquid')
        assert V > 0
        P_back = eos.pressure(V, T, z)
        assert abs(P_back - P) / abs(P) < 1e-10

    def test_srk_roundtrip_vapor(self):
        eos = _make_srk([0])
        V_true = 0.01
        T = 300.0
        z = [1.0]
        P = eos.pressure(V_true, T, z)
        V_calc = eos.volume(P, T, z, phase='vapor')
        P_back = eos.pressure(V_calc, T, z)
        assert abs(P_back - P) / abs(P) < 1e-10


# ===== Fugacity coefficients ================================================

class TestFugacity:
    def test_pr_ideal_gas_pure(self):
        eos = _make_pr([0])
        phi = eos.fugacity_coefficients(100.0, 500.0, [1.0], phase='vapor')
        assert abs(phi[0] - 1.0) < 0.005

    def test_pr_ideal_gas_mixture(self):
        eos = _make_pr([0, 1, 2])
        phi = eos.fugacity_coefficients(50.0, 500.0, [0.3, 0.3, 0.4], phase='vapor')
        for i, p in enumerate(phi):
            assert abs(p - 1.0) < 0.005, f"phi[{i}] = {p}"

    def test_srk_ideal_gas_mixture(self):
        eos = _make_srk([0, 1, 2])
        phi = eos.fugacity_coefficients(50.0, 500.0, [0.3, 0.3, 0.4], phase='vapor')
        for i, p in enumerate(phi):
            assert abs(p - 1.0) < 0.005, f"SRK phi[{i}] = {p}"

    def test_pr_fugacity_gibbs_consistency(self):
        """sum(x_i * ln(phi_i)) must equal a_res + Z - 1 - ln(Z)."""
        idx = [1, 2]
        eos = _make_pr(idx)
        P, T, z = 2e6, 300.0, [0.5, 0.5]
        phi = eos.fugacity_coefficients(P, T, z, phase='vapor')
        V = eos.volume(P, T, z, phase='vapor')
        n = sum(z)
        Z = P * V / (n * R_GAS * T)
        a_r = eos.a_res(V, T, z)
        sum_xlnphi = sum(z[i] / n * math.log(phi[i]) for i in range(len(z)))
        g_res_over_rt = a_r + Z - 1.0 - math.log(Z)
        assert abs(sum_xlnphi - g_res_over_rt) < 1e-6, \
            f"Gibbs consistency: {sum_xlnphi} vs {g_res_over_rt}"


# ===== Flash verification helper ============================================

def _verify_flash(eos, p, T, z, result, label=""):
    assert result is not None, f"{label}: flash returned None"
    beta = result['beta']
    x = np.array(result['x'])
    y = np.array(result['y'])
    zf = np.array(z) / np.sum(z)
    nc = len(z)
    assert 0.0 <= beta <= 1.0, f"{label}: beta={beta}"
    assert all(xi >= -1e-12 for xi in x)
    assert all(yi >= -1e-12 for yi in y)
    assert abs(np.sum(x) - 1.0) < 1e-8
    assert abs(np.sum(y) - 1.0) < 1e-8
    for i in range(nc):
        mb = (1.0 - beta) * x[i] + beta * y[i]
        assert abs(mb - zf[i]) < 1e-8, f"{label}: MB comp {i}"
    phi_l = np.array(eos.fugacity_coefficients(p, T, x.tolist(), 'liquid'))
    phi_v = np.array(eos.fugacity_coefficients(p, T, y.tolist(), 'vapor'))
    for i in range(nc):
        fi_l = phi_l[i] * x[i]
        fi_v = phi_v[i] * y[i]
        denom = max(abs(fi_v), 1e-15)
        assert abs(fi_l - fi_v) / denom < 1e-6, \
            f"{label}: fug eq comp {i}: {fi_l} vs {fi_v}"
    K = y / np.maximum(x, 1e-30)
    assert not np.allclose(K, 1.0, atol=0.01), f"{label}: trivial K"


class TestFlash:
    def test_pr_binary(self):
        eos = _make_pr([1, 2])
        result = eos.tp_flash(2.0e6, 300.0, [0.4, 0.6])
        _verify_flash(eos, 2.0e6, 300.0, [0.4, 0.6], result, "PR binary")

    def test_pr_ternary(self):
        eos = _make_pr([0, 1, 2])
        result = eos.tp_flash(2.0e6, 250.0, [0.2, 0.4, 0.4])
        _verify_flash(eos, 2.0e6, 250.0, [0.2, 0.4, 0.4], result, "PR ternary")

    def test_pr_five_component(self):
        eos = _make_pr(list(range(5)))
        result = eos.tp_flash(2.0e6, 250.0, [0.15, 0.25, 0.25, 0.20, 0.15])
        _verify_flash(eos, 2.0e6, 250.0,
                       [0.15, 0.25, 0.25, 0.20, 0.15], result, "PR 5-comp")

    def test_pr_different_conditions(self):
        eos = _make_pr([0, 1])
        result = eos.tp_flash(3.0e6, 220.0, [0.6, 0.4])
        _verify_flash(eos, 3.0e6, 220.0, [0.6, 0.4], result, "PR C1+C2")

    def test_srk_binary(self):
        eos = _make_srk([1, 2])
        result = eos.tp_flash(2.0e6, 300.0, [0.4, 0.6])
        _verify_flash(eos, 2.0e6, 300.0, [0.4, 0.6], result, "SRK binary")


class TestSinglePhase:
    def test_pr_high_pressure(self):
        eos = _make_pr([1, 2])
        assert eos.tp_flash(20.0e6, 200.0, [0.5, 0.5]) is None

    def test_pr_low_pressure(self):
        eos = _make_pr([1, 2])
        assert eos.tp_flash(0.05e6, 400.0, [0.5, 0.5]) is None

    def test_pr_heavy_components(self):
        eos = _make_pr([3, 4])
        assert eos.tp_flash(10.0e6, 300.0, [0.5, 0.5]) is None

    def test_srk_high_pressure(self):
        eos = _make_srk([1, 2])
        assert eos.tp_flash(20.0e6, 200.0, [0.5, 0.5]) is None


class TestBubbleDew:
    def test_pr_bubble(self):
        eos = _make_pr([1, 2])
        T, z = 280.0, [0.3, 0.7]
        P_bub = eos.bubble_pressure(T, z)
        assert 1e4 < P_bub < 1e7
        result = eos.tp_flash(P_bub, T, z)
        if result is not None:
            assert result['beta'] < 0.02, f"beta at bubble = {result['beta']}"

    def test_pr_dew(self):
        eos = _make_pr([1, 2])
        T, z = 280.0, [0.3, 0.7]
        P_dew = eos.dew_pressure(T, z)
        assert 1e4 < P_dew < 1e7
        result = eos.tp_flash(P_dew, T, z)
        if result is not None:
            assert result['beta'] > 0.98, f"beta at dew = {result['beta']}"

    def test_pr_bubble_above_dew(self):
        eos = _make_pr([1, 2])
        T, z = 280.0, [0.3, 0.7]
        assert eos.bubble_pressure(T, z) > eos.dew_pressure(T, z)

    def test_pr_bubble_ternary(self):
        eos = _make_pr([0, 1, 2])
        T, z = 230.0, [0.1, 0.4, 0.5]
        P_bub = eos.bubble_pressure(T, z)
        assert 1e4 < P_bub < 2e7
        result = eos.tp_flash(P_bub, T, z)
        if result is not None:
            assert result['beta'] < 0.02

    def test_srk_bubble(self):
        eos = _make_srk([1, 2])
        T, z = 280.0, [0.3, 0.7]
        P_bub = eos.bubble_pressure(T, z)
        assert 1e4 < P_bub < 1e7

    def test_srk_bubble_above_dew(self):
        eos = _make_srk([1, 2])
        T, z = 280.0, [0.3, 0.7]
        assert eos.bubble_pressure(T, z) > eos.dew_pressure(T, z)


# ===== Departure function tests =============================================

class TestDeparture:
    def _check_gibbs_consistency(self, eos, P, T, z, phase):
        V = eos.volume(P, T, z, phase=phase)
        n = sum(z)
        Z = P * V / (n * R_GAS * T)
        a_r = eos.a_res(V, T, z)
        H_dep = eos.enthalpy_departure(P, T, z, phase=phase)
        S_dep = eos.entropy_departure(P, T, z, phase=phase)
        lhs = H_dep - T * S_dep
        rhs = R_GAS * T * (a_r + Z - 1.0 - math.log(Z))
        assert abs(lhs - rhs) / max(abs(rhs), 1e-10) < 1e-5, \
            f"Gibbs consistency: H-TS={lhs}, RT*(ar+Z-1-lnZ)={rhs}"

    def _check_entropy_numerical(self, eos, P, T, z, phase):
        dT = 0.01
        V = eos.volume(P, T, z, phase=phase)
        n = sum(z)
        a1 = eos.a_res(V, T + dT, z)
        a2 = eos.a_res(V, T - dT, z)
        da_dT_num = (a1 - a2) / (2.0 * dT)
        Z = P * V / (n * R_GAS * T)
        a_r = eos.a_res(V, T, z)
        S_dep_num = -R_GAS * (a_r + T * da_dT_num) + R_GAS * math.log(Z)
        S_dep_calc = eos.entropy_departure(P, T, z, phase=phase)
        assert abs(S_dep_calc - S_dep_num) / max(abs(S_dep_num), 1e-10) < 1e-3, \
            f"Entropy numerical check: {S_dep_calc} vs {S_dep_num}"

    def test_pr_vapor_gibbs(self):
        eos = _make_pr([1, 2])
        self._check_gibbs_consistency(eos, 1e6, 320.0, [0.5, 0.5], 'vapor')

    def test_pr_liquid_gibbs(self):
        eos = _make_pr([2])
        self._check_gibbs_consistency(eos, 2e6, 300.0, [1.0], 'liquid')

    def test_pr_mixture_gibbs(self):
        eos = _make_pr([0, 1, 2])
        self._check_gibbs_consistency(eos, 1e6, 350.0, [0.3, 0.3, 0.4], 'vapor')

    def test_pr_entropy_numerical(self):
        eos = _make_pr([1, 2])
        self._check_entropy_numerical(eos, 1e6, 320.0, [0.5, 0.5], 'vapor')

    def test_pr_liquid_entropy_numerical(self):
        eos = _make_pr([2])
        self._check_entropy_numerical(eos, 2e6, 300.0, [1.0], 'liquid')

    def test_srk_vapor_gibbs(self):
        eos = _make_srk([1, 2])
        self._check_gibbs_consistency(eos, 1e6, 320.0, [0.5, 0.5], 'vapor')

    def test_srk_entropy_numerical(self):
        eos = _make_srk([1, 2])
        self._check_entropy_numerical(eos, 1e6, 320.0, [0.5, 0.5], 'vapor')

    def test_departure_sign(self):
        eos = _make_pr([2])
        H = eos.enthalpy_departure(1e6, 400.0, [1.0], 'vapor')
        assert H < 0, f"H_dep vapor should be negative, got {H}"


# ===== load_params ==========================================================

class TestLoadParams:
    def test_load_params_basic(self):
        from eos_engine import load_params
        names, Tc, Pc, omega, kij = load_params("/app/params.toml")
        assert len(names) == 5
        assert "methane" in names
        assert "n-pentane" in names
        mi = names.index("methane")
        assert abs(Tc[mi] - 190.564) < 1e-3
        assert abs(Pc[mi] - 4599200.0) < 1.0

    def test_load_params_kij(self):
        from eos_engine import load_params
        names, Tc, Pc, omega, kij = load_params("/app/params.toml")
        mi = names.index("methane")
        pi = names.index("propane")
        assert abs(kij[mi][pi] - 0.01) < 1e-6
        assert abs(kij[pi][mi] - 0.01) < 1e-6
        ei = names.index("ethane")
        assert abs(kij[mi][ei]) < 1e-10

    def test_load_params_roundtrip(self):
        from eos_engine import PengRobinson, load_params
        names, Tc, Pc, omega, kij = load_params("/app/params.toml")
        eos = PengRobinson(Tc, Pc, omega, kij)
        V, T, z = 1e-3, 300.0, [0.2] * 5
        P = eos.pressure(V, T, z)
        assert P > 0
