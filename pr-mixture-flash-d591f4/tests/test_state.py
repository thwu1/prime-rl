
"""
Tests for the Peng-Robinson / SRK flash calculator at /app/pr_flash.py.
Uses an embedded reference EOS implementation for validation.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Embedded reference EOS implementation
# ---------------------------------------------------------------------------

_R = 8.314462618

_EOS_CFGS = {
    "PR": {
        "c1": 0.4572355289213821893834601962251837888504,
        "c2": 0.0777960739038884559718447100373331839711,
        "kappa_coeffs": (0.37464, 1.54226, -0.26992),
        "delta1": 1.0 + math.sqrt(2.0),
        "delta2": 1.0 - math.sqrt(2.0),
    },
    "SRK": {
        "c1": 0.4274802335403414043909906940611707345513,
        "c2": 0.08664034996495772158907020242607611685675,
        "kappa_coeffs": (0.480, 1.574, -0.176),
        "delta1": 1.0,
        "delta2": 0.0,
    },
}


def _ref_compute_phase(Tcs, Pcs, omegas, zs, T, P, kijs, phase, eos="PR"):
    """Reference: compute fugacity coefficients + departure for one phase."""
    cfg = _EOS_CFGS[eos]
    N = len(Tcs)
    k0, k1, k2 = cfg["kappa_coeffs"]

    # Pure-component parameters
    bs = []
    a_alphas = []
    da_dTs = []
    for i in range(N):
        a = cfg["c1"] * _R * _R * Tcs[i] * Tcs[i] / Pcs[i]
        b = cfg["c2"] * _R * Tcs[i] / Pcs[i]
        kappa = k0 + k1 * omegas[i] + k2 * omegas[i] * omegas[i]
        sqrt_Tr = math.sqrt(T / Tcs[i])
        x = 1.0 + kappa * (1.0 - sqrt_Tr)
        aa = a * x * x
        da = -a * kappa * x / math.sqrt(T * Tcs[i])
        bs.append(b)
        a_alphas.append(aa)
        da_dTs.append(da)

    # Mixing rules (geometric combining)
    b_mix = sum(zs[i] * bs[i] for i in range(N))
    a_alpha_ij = [[0.0] * N for _ in range(N)]
    a_alpha_mix = 0.0
    da_dT_mix = 0.0
    for i in range(N):
        for j in range(N):
            omk = 1.0 - kijs[i][j]
            aij = omk * math.sqrt(a_alphas[i] * a_alphas[j])
            a_alpha_ij[i][j] = aij
            a_alpha_mix += zs[i] * zs[j] * aij
    for i in range(N):
        for j in range(N):
            omk = 1.0 - kijs[i][j]
            prod = a_alphas[i] * a_alphas[j]
            if prod > 0.0:
                sp = math.sqrt(prod)
                cross = (da_dTs[i] * a_alphas[j] +
                         a_alphas[i] * da_dTs[j]) / (2.0 * sp)
                da_dT_mix += zs[i] * zs[j] * omk * cross

    # Cubic coefficients
    A = a_alpha_mix * P / (_R * _R * T * T)
    B = b_mix * P / (_R * T)
    d1 = cfg["delta1"]
    d2 = cfg["delta2"]
    sigma = d1 + d2
    epsilon = d1 * d2
    c2 = (sigma - 1.0) * B - 1.0
    c1 = A + (epsilon - sigma) * B * B - sigma * B
    c0 = -A * B - epsilon * (B * B + B * B * B)

    # Solve depressed cubic
    c2_3 = c2 / 3.0
    p = c1 - c2 * c2_3
    q = c0 - c1 * c2_3 + 2.0 * c2_3 * c2_3 * c2_3
    disc = (q / 2.0) ** 2 + (p / 3.0) ** 3
    roots = []
    if disc < -1e-30:
        m = math.sqrt(-p / 3.0)
        ca = max(-1.0, min(1.0, -q / (2.0 * m * m * m)))
        theta = math.acos(ca) / 3.0
        for k in range(3):
            roots.append(2.0 * m * math.cos(theta - 2.0 * math.pi * k / 3.0) - c2_3)
    elif disc > 1e-30:
        sd = math.sqrt(disc)
        ua = -q / 2.0 + sd
        va = -q / 2.0 - sd
        u = math.copysign(abs(ua) ** (1.0 / 3.0), ua)
        v = math.copysign(abs(va) ** (1.0 / 3.0), va)
        roots.append(u + v - c2_3)
    else:
        if abs(q) < 1e-30:
            roots.append(-c2_3)
        else:
            u = math.copysign(abs(q / 2.0) ** (1.0 / 3.0), -q)
            roots.append(2.0 * u - c2_3)
            roots.append(-u - c2_3)
    roots.sort()

    # Root selection
    if phase == "liquid":
        cands = [z for z in roots if z > B + 1e-15]
        if not cands:
            cands = [z for z in roots if z > 0]
        Z = min(cands) if cands else roots[-1]
    else:
        cands = [z for z in roots if z > B + 1e-15]
        Z = max(cands) if cands else roots[-1]

    # Fugacity coefficients
    dd = d1 - d2
    zmb = max(Z - B, 1e-30)
    numer = Z + d1 * B
    denom = Z + d2 * B
    if abs(denom) < 1e-30:
        denom = 1e-30 if denom >= 0 else -1e-30
    log_ratio = math.log(abs(numer / denom))
    A_ddB = A / (dd * B) if abs(dd * B) > 1e-30 else 0.0

    phis = []
    for i in range(N):
        bi_b = bs[i] / b_mix
        sj = sum(zs[j] * a_alpha_ij[i][j] for j in range(N))
        bracket = bi_b - 2.0 * sj / a_alpha_mix
        lnphi = bi_b * (Z - 1.0) - math.log(zmb) + A_ddB * bracket * log_ratio
        phis.append(math.exp(lnphi))

    # Departure properties
    coeff = 1.0 / (dd * b_mix) if abs(dd * b_mix) > 1e-30 else 0.0
    H_dep = _R * T * (Z - 1.0) + (T * da_dT_mix - a_alpha_mix) * coeff * log_ratio
    S_dep = _R * math.log(zmb) + da_dT_mix * coeff * log_ratio

    return phis, Z, H_dep, S_dep


def _ref_flash(Tcs, Pcs, omegas, zs, T, P, kijs, eos="PR"):
    """Reference successive-substitution flash. Returns (VF, xs, ys, phis_l, phis_g) or None."""
    N = len(zs)
    # Wilson K-values
    Ks = [Pcs[i] / P * math.exp(5.37 * (1.0 + omegas[i]) * (1.0 - Tcs[i] / T))
          for i in range(N)]

    for _it in range(500):
        Kmin = min(Ks)
        Kmax = max(Ks)
        if Kmin >= 1.0 or Kmax <= 1.0:
            return None

        # Rachford-Rice bisection
        lo = max(0.0, 1.0 / (1.0 - Kmax)) + 1e-15
        hi = min(1.0, 1.0 / (1.0 - Kmin)) - 1e-15

        def rr(vf):
            return sum(zs[i] * (Ks[i] - 1.0) / (1.0 + vf * (Ks[i] - 1.0))
                       for i in range(N))

        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if rr(mid) > 0:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-15:
                break
        VF = 0.5 * (lo + hi)
        xs = [zs[i] / (1.0 + VF * (Ks[i] - 1.0)) for i in range(N)]
        ys = [Ks[i] * xs[i] for i in range(N)]
        sx = sum(xs)
        sy = sum(ys)
        xs = [x / sx for x in xs]
        ys = [y / sy for y in ys]

        if VF < -1e-8 or VF > 1.0 + 1e-8:
            return None

        phis_l, _, _, _ = _ref_compute_phase(Tcs, Pcs, omegas, xs, T, P, kijs, "liquid", eos)
        phis_g, _, _, _ = _ref_compute_phase(Tcs, Pcs, omegas, ys, T, P, kijs, "vapor", eos)

        Ks_new = [phis_l[i] / phis_g[i] for i in range(N)]
        converged = max(abs(math.log(Ks_new[i]) - math.log(Ks[i]))
                        for i in range(N)) < 1e-12
        Ks = Ks_new
        if converged:
            break

    return VF, xs, ys, phis_l, phis_g


def _ref_bubble_P(Tcs, Pcs, omegas, xs, T, kijs, eos="PR"):
    """Reference bubble pressure by successive substitution."""
    N = len(xs)
    P = sum(xs[i] * Pcs[i] * math.exp(5.37 * (1 + omegas[i]) * (1 - Tcs[i] / T))
            for i in range(N))
    Ks = [Pcs[i] / P * math.exp(5.37 * (1.0 + omegas[i]) * (1.0 - Tcs[i] / T))
          for i in range(N)]
    ys = [Ks[i] * xs[i] for i in range(N)]
    sy = sum(ys)
    ys = [y / sy for y in ys]

    for _ in range(500):
        phis_l, _, _, _ = _ref_compute_phase(Tcs, Pcs, omegas, xs, T, P, kijs, "liquid", eos)
        phis_g, _, _, _ = _ref_compute_phase(Tcs, Pcs, omegas, ys, T, P, kijs, "vapor", eos)
        Ks = [phis_l[i] / phis_g[i] for i in range(N)]
        ys_new = [Ks[i] * xs[i] for i in range(N)]
        sy = sum(ys_new)
        P_new = P * sy
        ys = [y / sy for y in ys_new]
        if abs(P_new - P) / max(abs(P), 1e-30) < 1e-10:
            P = P_new
            break
        P = P_new
    return P, ys, Ks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def import_solver():
    """Import the candidate solver module."""
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    if "pr_flash" in sys.modules:
        del sys.modules["pr_flash"]
    import pr_flash
    return pr_flash


def rel_err(a, b):
    if b == 0:
        return abs(a)
    return abs(a - b) / abs(b)


# ===========================================================================
# System definitions
# ===========================================================================

SYS_N2_CH4 = dict(
    Tcs=[126.1, 190.6],
    Pcs=[33.94e5, 46.04e5],
    omegas=[0.04, 0.011],
    zs=[0.5, 0.5],
    kijs=[[0.0, 0.0], [0.0, 0.0]],
    T=115.0,
    P=1e6,
)

SYS_TERNARY = dict(
    Tcs=[305.32, 369.83, 425.12],
    Pcs=[4872200.0, 4248000.0, 3796000.0],
    omegas=[0.099, 0.152, 0.200],
    zs=[0.5, 0.3, 0.2],
    kijs=[[0, 0, 0], [0, 0, 0], [0, 0, 0]],
    T=260.0,
    P=8e5,
)

SYS_CO2_CH4 = dict(
    Tcs=[304.2, 190.6],
    Pcs=[7376000.0, 4599000.0],
    omegas=[0.225, 0.011],
    zs=[0.4, 0.6],
    kijs=[[0.0, 0.12], [0.12, 0.0]],
    T=220.0,
    P=3e6,
)

SYS_PENTANE_HEXANE = dict(
    Tcs=[469.7, 507.6],
    Pcs=[3370000.0, 3025000.0],
    omegas=[0.251, 0.2975],
    zs=[0.6, 0.4],
    kijs=[[0.0, 0.0], [0.0, 0.0]],
    T=320.0,
    P=1e5,
)


# ===========================================================================
# PR EOS Tests -- Bug detection
# ===========================================================================

class TestPRFugacityCoefficients:
    """Verify the solver's PR EOS fugacity coefficients against reference."""

    def test_binary_fugacities_liquid(self):
        mod = import_solver()
        s = SYS_N2_CH4
        result = mod.pt_flash(**s)
        if result["xs"] is not None and result["phis_l"] is not None:
            ref_phis, _, _, _ = _ref_compute_phase(
                s["Tcs"], s["Pcs"], s["omegas"], result["xs"],
                s["T"], s["P"], s["kijs"], "liquid", "PR"
            )
            for i in range(len(s["zs"])):
                assert rel_err(result["phis_l"][i], ref_phis[i]) < 1e-4, \
                    f"phis_l[{i}]: got {result['phis_l'][i]}, ref {ref_phis[i]}"

    def test_ternary_fugacities_liquid(self):
        mod = import_solver()
        s = SYS_TERNARY
        result = mod.pt_flash(**s)
        if result["xs"] is not None and result["phis_l"] is not None:
            ref_phis, _, _, _ = _ref_compute_phase(
                s["Tcs"], s["Pcs"], s["omegas"], result["xs"],
                s["T"], s["P"], s["kijs"], "liquid", "PR"
            )
            for i in range(len(s["zs"])):
                assert rel_err(result["phis_l"][i], ref_phis[i]) < 1e-4, \
                    f"phis_l[{i}]: got {result['phis_l'][i]}, ref {ref_phis[i]}"

    def test_pentane_hexane_fugacities(self):
        """Heavier system -- higher omega exposes kappa correlation errors."""
        mod = import_solver()
        s = SYS_PENTANE_HEXANE
        result = mod.pt_flash(**s)
        if result["phis_g"] is not None and result["ys"] is not None:
            ref_phis, _, _, _ = _ref_compute_phase(
                s["Tcs"], s["Pcs"], s["omegas"], result["ys"],
                s["T"], s["P"], s["kijs"], "vapor", "PR"
            )
            for i in range(2):
                assert rel_err(result["phis_g"][i], ref_phis[i]) < 1e-4, \
                    f"phis_g[{i}]: got {result['phis_g'][i]}, ref {ref_phis[i]}"

    def test_co2_ch4_with_kijs(self):
        """Binary system with non-zero kijs."""
        mod = import_solver()
        s = SYS_CO2_CH4
        result = mod.pt_flash(**s)
        if result["xs"] is not None and result["phis_l"] is not None:
            ref_phis, _, _, _ = _ref_compute_phase(
                s["Tcs"], s["Pcs"], s["omegas"], result["xs"],
                s["T"], s["P"], s["kijs"], "liquid", "PR"
            )
            for i in range(2):
                assert rel_err(result["phis_l"][i], ref_phis[i]) < 1e-4, \
                    f"phis_l[{i}]: got {result['phis_l'][i]}, ref {ref_phis[i]}"


class TestPRFlashBinary:
    """Full PR flash tests for binary N2-CH4 system."""

    def test_two_phase_exists(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        assert 0.0 <= result["V_over_F"] <= 1.0, \
            f"Expected two-phase, got V/F={result['V_over_F']}"

    def test_material_balance(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        VF = result["V_over_F"]
        xs, ys = result["xs"], result["ys"]
        zs = SYS_N2_CH4["zs"]
        for i in range(len(zs)):
            z_calc = (1 - VF) * xs[i] + VF * ys[i]
            assert abs(z_calc - zs[i]) < 1e-8, \
                f"Material balance: z[{i}]={zs[i]}, calc={z_calc}"

    def test_fugacity_equality(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        for i in range(len(SYS_N2_CH4["zs"])):
            f_l = result["phis_l"][i] * result["xs"][i]
            f_g = result["phis_g"][i] * result["ys"][i]
            assert rel_err(f_l, f_g) < 1e-5, \
                f"Fugacity mismatch comp {i}: f_l={f_l}, f_g={f_g}"

    def test_vf_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        ref = _ref_flash(**SYS_N2_CH4)
        assert ref is not None, "Reference flash returned single-phase unexpectedly"
        assert abs(result["V_over_F"] - ref[0]) < 1e-4, \
            f"V/F: got {result['V_over_F']}, ref {ref[0]}"

    def test_compositions_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        ref = _ref_flash(**SYS_N2_CH4)
        assert ref is not None
        for i in range(2):
            assert rel_err(result["xs"][i], ref[1][i]) < 1e-4
            assert rel_err(result["ys"][i], ref[2][i]) < 1e-4


class TestPRFlashTernary:
    """Flash tests for the ternary ethane-propane-butane system."""

    def test_two_phase(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_TERNARY)
        assert 0.0 <= result["V_over_F"] <= 1.0

    def test_material_balance(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_TERNARY)
        VF = result["V_over_F"]
        for i in range(3):
            z_calc = (1 - VF) * result["xs"][i] + VF * result["ys"][i]
            assert abs(z_calc - SYS_TERNARY["zs"][i]) < 1e-8

    def test_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_TERNARY)
        ref = _ref_flash(**SYS_TERNARY)
        assert ref is not None
        assert abs(result["V_over_F"] - ref[0]) < 1e-4


class TestPRFlashWithKijs:
    """PR flash with non-zero binary interaction parameters (CO2-CH4)."""

    def test_two_phase(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_CO2_CH4)
        assert 0.0 <= result["V_over_F"] <= 1.0

    def test_material_balance(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_CO2_CH4)
        VF = result["V_over_F"]
        for i in range(2):
            z_calc = (1 - VF) * result["xs"][i] + VF * result["ys"][i]
            assert abs(z_calc - SYS_CO2_CH4["zs"][i]) < 1e-8

    def test_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_CO2_CH4)
        ref = _ref_flash(**SYS_CO2_CH4)
        assert ref is not None
        assert abs(result["V_over_F"] - ref[0]) < 1e-4
        for i in range(2):
            assert rel_err(result["xs"][i], ref[1][i]) < 1e-4
            assert rel_err(result["ys"][i], ref[2][i]) < 1e-4


class TestPRFlashHeavy:
    """PR flash for pentane-hexane system (higher acentric factors)."""

    def test_two_phase(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_PENTANE_HEXANE)
        assert 0.0 <= result["V_over_F"] <= 1.0

    def test_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_PENTANE_HEXANE)
        ref = _ref_flash(**SYS_PENTANE_HEXANE)
        assert ref is not None
        assert abs(result["V_over_F"] - ref[0]) < 1e-4
        for i in range(2):
            assert rel_err(result["xs"][i], ref[1][i]) < 1e-4
            assert rel_err(result["ys"][i], ref[2][i]) < 1e-4

    def test_fugacity_equality(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_PENTANE_HEXANE)
        for i in range(2):
            f_l = result["phis_l"][i] * result["xs"][i]
            f_g = result["phis_g"][i] * result["ys"][i]
            assert rel_err(f_l, f_g) < 1e-5


class TestSinglePhase:
    """Detect single-phase conditions correctly."""

    def test_all_liquid_high_pressure(self):
        mod = import_solver()
        result = mod.pt_flash(
            Tcs=[126.1, 190.6],
            Pcs=[33.94e5, 46.04e5],
            omegas=[0.04, 0.011],
            zs=[0.5, 0.5],
            T=115.0,
            P=1e8,
        )
        assert result["V_over_F"] == -1.0
        assert result["xs"] is not None
        assert result["ys"] is None

    def test_all_vapor_high_temperature(self):
        mod = import_solver()
        result = mod.pt_flash(
            Tcs=[305.32, 369.83],
            Pcs=[4872200.0, 4248000.0],
            omegas=[0.099, 0.152],
            zs=[0.5, 0.5],
            T=600.0,
            P=1e4,
        )
        assert result["V_over_F"] == 2.0
        assert result["ys"] is not None
        assert result["xs"] is None


class TestPRDepartureProperties:
    """Verify PR departure enthalpy and entropy against reference."""

    def test_binary_departure(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        if result["xs"] is None or result["ys"] is None:
            pytest.skip("Single phase")

        _, _, H_dep_l_ref, S_dep_l_ref = _ref_compute_phase(
            SYS_N2_CH4["Tcs"], SYS_N2_CH4["Pcs"], SYS_N2_CH4["omegas"],
            result["xs"], SYS_N2_CH4["T"], SYS_N2_CH4["P"],
            SYS_N2_CH4["kijs"], "liquid", "PR"
        )
        _, _, H_dep_g_ref, S_dep_g_ref = _ref_compute_phase(
            SYS_N2_CH4["Tcs"], SYS_N2_CH4["Pcs"], SYS_N2_CH4["omegas"],
            result["ys"], SYS_N2_CH4["T"], SYS_N2_CH4["P"],
            SYS_N2_CH4["kijs"], "vapor", "PR"
        )

        if result["H_dep_l"] is not None:
            assert rel_err(result["H_dep_l"], H_dep_l_ref) < 5e-3, \
                f"H_dep_l: got {result['H_dep_l']}, ref {H_dep_l_ref}"
        if result["H_dep_g"] is not None:
            assert rel_err(result["H_dep_g"], H_dep_g_ref) < 5e-3, \
                f"H_dep_g: got {result['H_dep_g']}, ref {H_dep_g_ref}"
        if result["S_dep_l"] is not None:
            assert rel_err(result["S_dep_l"], S_dep_l_ref) < 5e-3, \
                f"S_dep_l: got {result['S_dep_l']}, ref {S_dep_l_ref}"
        if result["S_dep_g"] is not None:
            assert rel_err(result["S_dep_g"], S_dep_g_ref) < 5e-3, \
                f"S_dep_g: got {result['S_dep_g']}, ref {S_dep_g_ref}"

    def test_heavy_system_departure(self):
        """Departure properties for pentane-hexane (exposes sign errors)."""
        mod = import_solver()
        result = mod.pt_flash(**SYS_PENTANE_HEXANE)
        if result["xs"] is None or result["ys"] is None:
            pytest.skip("Single phase")

        _, _, H_dep_l_ref, S_dep_l_ref = _ref_compute_phase(
            SYS_PENTANE_HEXANE["Tcs"], SYS_PENTANE_HEXANE["Pcs"],
            SYS_PENTANE_HEXANE["omegas"], result["xs"],
            SYS_PENTANE_HEXANE["T"], SYS_PENTANE_HEXANE["P"],
            SYS_PENTANE_HEXANE["kijs"], "liquid", "PR"
        )

        if result["H_dep_l"] is not None:
            assert rel_err(result["H_dep_l"], H_dep_l_ref) < 5e-3, \
                f"H_dep_l: got {result['H_dep_l']}, ref {H_dep_l_ref}"
        if result["S_dep_l"] is not None:
            assert rel_err(result["S_dep_l"], S_dep_l_ref) < 5e-3, \
                f"S_dep_l: got {result['S_dep_l']}, ref {S_dep_l_ref}"


class TestKValues:
    """Verify K-values are consistent with fugacity coefficients."""

    def test_k_equals_phi_ratio(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        if result["K_values"] is None:
            pytest.skip("Single phase")
        for i in range(len(SYS_N2_CH4["zs"])):
            k_from_phi = result["phis_l"][i] / result["phis_g"][i]
            assert rel_err(result["K_values"][i], k_from_phi) < 1e-8


# ===========================================================================
# SRK EOS Tests
# ===========================================================================

class TestSRKFlashBinary:
    """SRK EOS flash for N2-CH4."""

    def test_srk_two_phase(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        assert 0.0 <= result["V_over_F"] <= 1.0

    def test_srk_material_balance(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        VF = result["V_over_F"]
        zs = SYS_N2_CH4["zs"]
        for i in range(len(zs)):
            z_calc = (1 - VF) * result["xs"][i] + VF * result["ys"][i]
            assert abs(z_calc - zs[i]) < 1e-8

    def test_srk_fugacity_equality(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        for i in range(2):
            f_l = result["phis_l"][i] * result["xs"][i]
            f_g = result["phis_g"][i] * result["ys"][i]
            assert rel_err(f_l, f_g) < 1e-5

    def test_srk_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        ref = _ref_flash(**SYS_N2_CH4, eos="SRK")
        assert ref is not None
        assert abs(result["V_over_F"] - ref[0]) < 1e-4
        for i in range(2):
            assert rel_err(result["xs"][i], ref[1][i]) < 1e-4
            assert rel_err(result["ys"][i], ref[2][i]) < 1e-4

    def test_srk_fugacities_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        if result["xs"] is not None and result["phis_l"] is not None:
            ref_phis, _, _, _ = _ref_compute_phase(
                SYS_N2_CH4["Tcs"], SYS_N2_CH4["Pcs"], SYS_N2_CH4["omegas"],
                result["xs"], SYS_N2_CH4["T"], SYS_N2_CH4["P"],
                SYS_N2_CH4["kijs"], "liquid", "SRK"
            )
            for i in range(2):
                assert rel_err(result["phis_l"][i], ref_phis[i]) < 1e-4


class TestSRKFlashTernary:
    """SRK EOS flash for ternary system."""

    def test_srk_ternary_two_phase(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_TERNARY, eos="SRK")
        assert 0.0 <= result["V_over_F"] <= 1.0

    def test_srk_ternary_against_reference(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_TERNARY, eos="SRK")
        ref = _ref_flash(**SYS_TERNARY, eos="SRK")
        assert ref is not None
        assert abs(result["V_over_F"] - ref[0]) < 1e-4

    def test_srk_ternary_fugacity_equality(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_TERNARY, eos="SRK")
        for i in range(3):
            f_l = result["phis_l"][i] * result["xs"][i]
            f_g = result["phis_g"][i] * result["ys"][i]
            assert rel_err(f_l, f_g) < 1e-5


class TestSRKDepartureProperties:
    """SRK departure properties against reference."""

    def test_srk_departure(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        if result["xs"] is None or result["ys"] is None:
            pytest.skip("Single phase")

        _, _, H_dep_l_ref, S_dep_l_ref = _ref_compute_phase(
            SYS_N2_CH4["Tcs"], SYS_N2_CH4["Pcs"], SYS_N2_CH4["omegas"],
            result["xs"], SYS_N2_CH4["T"], SYS_N2_CH4["P"],
            SYS_N2_CH4["kijs"], "liquid", "SRK"
        )

        if result["H_dep_l"] is not None:
            assert rel_err(result["H_dep_l"], H_dep_l_ref) < 5e-3
        if result["S_dep_l"] is not None:
            assert rel_err(result["S_dep_l"], S_dep_l_ref) < 5e-3


class TestSRKWithKijs:
    """SRK flash with non-zero kijs."""

    def test_srk_co2_ch4(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_CO2_CH4, eos="SRK")
        assert 0.0 <= result["V_over_F"] <= 1.0
        ref = _ref_flash(**SYS_CO2_CH4, eos="SRK")
        assert ref is not None
        assert abs(result["V_over_F"] - ref[0]) < 1e-4
        for i in range(2):
            assert rel_err(result["xs"][i], ref[1][i]) < 1e-4


# ===========================================================================
# Bubble Point Tests
# ===========================================================================

class TestBubblePressure:
    """Test bubble-point pressure calculation."""

    def test_bubble_pr_binary(self):
        mod = import_solver()
        Tcs = [305.32, 369.83]
        Pcs = [4872200.0, 4248000.0]
        omegas = [0.099, 0.152]
        xs = [0.4, 0.6]
        T = 280.0
        kijs = [[0, 0], [0, 0]]

        result = mod.bubble_pressure(Tcs, Pcs, omegas, xs, T, kijs=kijs, eos="PR")
        P_ref, ys_ref, Ks_ref = _ref_bubble_P(Tcs, Pcs, omegas, xs, T, kijs, eos="PR")

        assert rel_err(result["P_bubble"], P_ref) < 1e-3, \
            f"P_bubble: got {result['P_bubble']}, ref {P_ref}"
        for i in range(2):
            assert rel_err(result["ys"][i], ys_ref[i]) < 1e-3

    def test_bubble_pr_ternary(self):
        mod = import_solver()
        Tcs = [305.32, 369.83, 425.12]
        Pcs = [4872200.0, 4248000.0, 3796000.0]
        omegas = [0.099, 0.152, 0.200]
        xs = [0.3, 0.4, 0.3]
        T = 300.0
        kijs = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]

        result = mod.bubble_pressure(Tcs, Pcs, omegas, xs, T, kijs=kijs, eos="PR")
        P_ref, ys_ref, Ks_ref = _ref_bubble_P(Tcs, Pcs, omegas, xs, T, kijs, eos="PR")

        assert rel_err(result["P_bubble"], P_ref) < 1e-3

    def test_bubble_srk_binary(self):
        mod = import_solver()
        Tcs = [305.32, 369.83]
        Pcs = [4872200.0, 4248000.0]
        omegas = [0.099, 0.152]
        xs = [0.4, 0.6]
        T = 280.0
        kijs = [[0, 0], [0, 0]]

        result = mod.bubble_pressure(Tcs, Pcs, omegas, xs, T, kijs=kijs, eos="SRK")
        P_ref, ys_ref, Ks_ref = _ref_bubble_P(Tcs, Pcs, omegas, xs, T, kijs, eos="SRK")

        assert rel_err(result["P_bubble"], P_ref) < 1e-3

    def test_bubble_returns_dict(self):
        mod = import_solver()
        result = mod.bubble_pressure(
            Tcs=[305.32, 369.83],
            Pcs=[4872200.0, 4248000.0],
            omegas=[0.099, 0.152],
            xs=[0.5, 0.5],
            T=290.0
        )
        assert "P_bubble" in result
        assert "ys" in result
        assert "K_values" in result
        assert isinstance(result["P_bubble"], float)
        assert result["P_bubble"] > 0
        assert abs(sum(result["ys"]) - 1.0) < 0.01


# ===========================================================================
# CLI Tests
# ===========================================================================

class TestCLI:
    """Verify the command-line interface."""

    def test_cli_pr_flash(self):
        s = SYS_N2_CH4.copy()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f_in:
            json.dump(s, f_in)
            in_path = f_in.name
        out_path = in_path + ".out.json"
        try:
            proc = subprocess.run(
                ["python3", "/app/pr_flash.py", in_path, out_path],
                capture_output=True, text=True, timeout=60
            )
            assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
            with open(out_path) as f:
                result = json.load(f)
            assert "V_over_F" in result
            assert 0.0 <= result["V_over_F"] <= 1.0
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_cli_srk_flash(self):
        s = dict(SYS_N2_CH4)
        s["eos"] = "SRK"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f_in:
            json.dump(s, f_in)
            in_path = f_in.name
        out_path = in_path + ".out.json"
        try:
            proc = subprocess.run(
                ["python3", "/app/pr_flash.py", in_path, out_path],
                capture_output=True, text=True, timeout=60
            )
            assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
            with open(out_path) as f:
                result = json.load(f)
            assert "V_over_F" in result
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_cli_bubble_mode(self):
        s = {
            "mode": "bubble",
            "Tcs": [305.32, 369.83],
            "Pcs": [4872200.0, 4248000.0],
            "omegas": [0.099, 0.152],
            "xs": [0.5, 0.5],
            "T": 290.0,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f_in:
            json.dump(s, f_in)
            in_path = f_in.name
        out_path = in_path + ".out.json"
        try:
            proc = subprocess.run(
                ["python3", "/app/pr_flash.py", in_path, out_path],
                capture_output=True, text=True, timeout=60
            )
            assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
            with open(out_path) as f:
                result = json.load(f)
            assert "P_bubble" in result
            assert result["P_bubble"] > 0
        finally:
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


# ===========================================================================
# EOS parameter validation
# ===========================================================================

class TestEOSParameter:
    """Verify EOS accepts the eos parameter."""

    def test_pr_default(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4)
        assert "V_over_F" in result

    def test_pr_explicit(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="PR")
        assert "V_over_F" in result

    def test_srk_explicit(self):
        mod = import_solver()
        result = mod.pt_flash(**SYS_N2_CH4, eos="SRK")
        assert "V_over_F" in result

    def test_pr_and_srk_differ(self):
        """PR and SRK should give different results for same inputs."""
        mod = import_solver()
        result_pr = mod.pt_flash(**SYS_TERNARY, eos="PR")
        result_srk = mod.pt_flash(**SYS_TERNARY, eos="SRK")
        assert 0.0 <= result_pr["V_over_F"] <= 1.0
        assert 0.0 <= result_srk["V_over_F"] <= 1.0
        assert abs(result_pr["V_over_F"] - result_srk["V_over_F"]) > 1e-6, \
            "PR and SRK gave identical V/F -- likely not implemented separately"
