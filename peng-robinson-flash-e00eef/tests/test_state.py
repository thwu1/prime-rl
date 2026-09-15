
"""
Independent Peng-Robinson EoS verification.

Computes reference values using a Python PR implementation and compares
against the agent's Rust output in /app/results.json.
"""

import json
import math
import pytest
import numpy as np
from pathlib import Path

R = 8.31446261815324  # J/(mol K)
SQRT2 = math.sqrt(2)


# ============================================================
# Peng-Robinson EoS reference implementation
# ============================================================

class PRComponent:
    """Peng-Robinson component with precomputed constants."""

    def __init__(self, tc, pc, omega):
        self.tc = tc
        self.pc = pc
        self.omega = omega
        self.kappa = 0.37464 + 1.54226 * omega - 0.26992 * omega ** 2
        self.ac = 0.45724 * R ** 2 * tc ** 2 / pc
        self.b = 0.07780 * R * tc / pc

    def alpha(self, T):
        Tr = T / self.tc
        return (1.0 + self.kappa * (1.0 - math.sqrt(Tr))) ** 2

    def a(self, T):
        return self.ac * self.alpha(T)


def _solve_cubic_pr(A, B):
    """
    Solve the PR cubic for Z:
        Z^3 - (1-B)Z^2 + (A - 3B^2 - 2B)Z - (AB - B^2 - B^3) = 0
    Returns sorted real roots with Z > B.
    """
    coeffs = [1.0, -(1.0 - B), A - 3.0 * B * B - 2.0 * B,
              -(A * B - B * B - B ** 3)]
    raw = np.roots(coeffs)
    real = sorted(r.real for r in raw if abs(r.imag) < 1e-8 and r.real > B)
    return real


def _fugacity_coeff_pure(T, P, comp, vapor=True):
    a = comp.a(T)
    b = comp.b
    A = a * P / (R * R * T * T)
    B = b * P / (R * T)
    roots = _solve_cubic_pr(A, B)
    if not roots:
        return 1.0
    Z = roots[-1] if vapor else roots[0]
    ln_phi = (Z - 1.0
              - math.log(Z - B)
              - A / (2.0 * SQRT2 * B)
              * math.log((Z + (1.0 + SQRT2) * B)
                         / (Z + (1.0 - SQRT2) * B)))
    return math.exp(ln_phi)


def _vapor_pressure(T, comp, tol=1e-13, maxiter=300):
    # Wilson initial estimate
    P = comp.pc * math.exp(5.37 * (1.0 + comp.omega) * (1.0 - comp.tc / T))
    if P < 1.0:
        P = 1.0
    if P > comp.pc * 0.99:
        P = comp.pc * 0.5
    for _ in range(maxiter):
        phi_l = _fugacity_coeff_pure(T, P, comp, vapor=False)
        phi_v = _fugacity_coeff_pure(T, P, comp, vapor=True)
        P_new = P * phi_l / phi_v
        if abs(P_new - P) / P < tol:
            return P_new
        P = P_new
    return P


def _fugacity_coeff_mix(T, P, comps, x, kij, idx, vapor=True):
    n = len(comps)
    a_vals = [c.a(T) for c in comps]
    b_vals = [c.b for c in comps]

    a_mix = sum(x[i] * x[j] * math.sqrt(a_vals[i] * a_vals[j])
                * (1.0 - kij[i][j])
                for i in range(n) for j in range(n))
    b_mix = sum(x[i] * b_vals[i] for i in range(n))

    A = a_mix * P / (R * R * T * T)
    B = b_mix * P / (R * T)
    roots = _solve_cubic_pr(A, B)
    if not roots:
        return 1.0
    Z = roots[-1] if vapor else roots[0]

    sum_aij = sum(x[j] * math.sqrt(a_vals[idx] * a_vals[j])
                  * (1.0 - kij[idx][j]) for j in range(n))
    bi_bm = b_vals[idx] / b_mix

    ln_phi = (bi_bm * (Z - 1.0)
              - math.log(Z - B)
              - A / (2.0 * SQRT2 * B)
              * (2.0 * sum_aij / a_mix - bi_bm)
              * math.log((Z + (1.0 + SQRT2) * B)
                         / (Z + (1.0 - SQRT2) * B)))
    return math.exp(ln_phi)


def _bubble_point(T, comps, x, kij, tol=1e-11, maxiter=500):
    n = len(comps)
    psats = [_vapor_pressure(T, c) for c in comps]
    P = sum(x[i] * psats[i] for i in range(n))

    k_vals = [(c.pc / P) * math.exp(5.37 * (1.0 + c.omega) * (1.0 - c.tc / T))
              for c in comps]
    y = [x[i] * k_vals[i] for i in range(n)]
    sy = sum(y)
    y = [yi / sy for yi in y]

    for _ in range(maxiter):
        sy_new = 0.0
        y_new = [0.0] * n
        for i in range(n):
            phi_l = _fugacity_coeff_mix(T, P, comps, x, kij, i, False)
            phi_v = _fugacity_coeff_mix(T, P, comps, y, kij, i, True)
            k_vals[i] = phi_l / phi_v
            y_new[i] = x[i] * k_vals[i]
            sy_new += y_new[i]
        P_new = P * sy_new
        y = [yi / sy_new for yi in y_new]
        if abs(P_new - P) / P < tol:
            return P_new
        P = P_new
    return P


def _dew_point(T, comps, y, kij, tol=1e-11, maxiter=500):
    n = len(comps)
    psats = [_vapor_pressure(T, c) for c in comps]
    P = 1.0 / sum(y[i] / psats[i] for i in range(n))

    k_vals = [(c.pc / P) * math.exp(5.37 * (1.0 + c.omega) * (1.0 - c.tc / T))
              for c in comps]
    x = [y[i] / k_vals[i] for i in range(n)]
    sx = sum(x)
    x = [xi / sx for xi in x]

    for _ in range(maxiter):
        sx_new = 0.0
        x_new = [0.0] * n
        for i in range(n):
            phi_l = _fugacity_coeff_mix(T, P, comps, x, kij, i, False)
            phi_v = _fugacity_coeff_mix(T, P, comps, y, kij, i, True)
            k_vals[i] = phi_l / phi_v
            x_new[i] = y[i] / k_vals[i]
            sx_new += x_new[i]
        P_new = P / sx_new
        x = [xi / sx_new for xi in x_new]
        if abs(P_new - P) / P < tol:
            return P_new
        P = P_new
    return P


def _rachford_rice(beta, z, k):
    return sum(z[i] * (k[i] - 1.0) / (1.0 + beta * (k[i] - 1.0))
               for i in range(len(z)))


def _rachford_rice_d(beta, z, k):
    return sum(-z[i] * (k[i] - 1.0) ** 2 / (1.0 + beta * (k[i] - 1.0)) ** 2
               for i in range(len(z)))


def _flash_tp(T, P, comps, z, kij, tol=1e-10, maxiter=200):
    n = len(comps)
    k_vals = [(c.pc / P) * math.exp(5.37 * (1.0 + c.omega) * (1.0 - c.tc / T))
              for c in comps]

    for _ in range(maxiter):
        # Check single-phase conditions
        g0 = _rachford_rice(0.0, z, k_vals)
        g1 = _rachford_rice(1.0, z, k_vals)
        if g0 <= 0:
            return 0.0, list(z), list(z)
        if g1 >= 0:
            return 1.0, list(z), list(z)

        # Newton-Raphson for Rachford-Rice
        beta = 0.5
        for _ in range(100):
            f = _rachford_rice(beta, z, k_vals)
            if abs(f) < 1e-14:
                break
            df = _rachford_rice_d(beta, z, k_vals)
            beta_new = beta - f / df
            beta = max(1e-12, min(1.0 - 1e-12, beta_new))

        # Compositions
        x = [z[i] / (1.0 + beta * (k_vals[i] - 1.0)) for i in range(n)]
        y_c = [k_vals[i] * x[i] for i in range(n)]
        sx = sum(x)
        sy = sum(y_c)
        x = [xi / sx for xi in x]
        y_c = [yi / sy for yi in y_c]

        # Update K-values from fugacities
        max_change = 0.0
        for i in range(n):
            phi_l = _fugacity_coeff_mix(T, P, comps, x, kij, i, False)
            phi_v = _fugacity_coeff_mix(T, P, comps, y_c, kij, i, True)
            k_new = phi_l / phi_v
            change = abs(k_new - k_vals[i]) / max(k_vals[i], 1e-30)
            if change > max_change:
                max_change = change
            k_vals[i] = k_new

        if max_change < tol:
            return beta, x, y_c

    return beta, x, y_c


def _enthalpy_departure(T, P, comp, vapor=True):
    a = comp.a(T)
    b = comp.b
    ac = comp.ac
    kap = comp.kappa
    al = comp.alpha(T)

    A = a * P / (R * R * T * T)
    B = b * P / (R * T)
    roots = _solve_cubic_pr(A, B)
    Z = roots[-1] if vapor else roots[0]

    # T*da/dT - a = -ac*(1+kappa)*sqrt(alpha) * ... simplified
    # da/dT = -ac * kappa * sqrt(alpha) / sqrt(T*Tc)
    # T*da/dT = -ac * kappa * sqrt(alpha) * sqrt(T/Tc)
    # T*da/dT - a = -ac * kappa * sqrt(alpha) * sqrt(T/Tc) - ac*alpha
    #             = -ac * sqrt(alpha) * (kappa*sqrt(T/Tc) + sqrt(alpha))
    # But simpler: T*da/dT - a = -ac*(1+kappa)*sqrt(alpha)... NO.
    # Correct: da/dT = -ac*kappa*sqrt(alpha/(T*Tc))
    # T*da/dT - a = T * (-ac*kappa*sqrt(alpha/(T*Tc))) - ac*alpha
    #             = -ac*kappa*sqrt(alpha*T/Tc) - ac*alpha
    # For the enthalpy departure we need: T*da/dT - a
    # Let f = 1 + kappa*(1-sqrt(Tr)), alpha = f^2
    # da/dT = 2*ac*f*f' = 2*ac*f*(-kappa/(2*sqrt(T*Tc))) = -ac*kappa*f/sqrt(T*Tc)
    # T*da/dT = -ac*kappa*f*T/sqrt(T*Tc) = -ac*kappa*f*sqrt(T/Tc)*sqrt(T)/sqrt(T)
    #         = -ac*kappa*f*sqrt(T/Tc)... wait
    # T/sqrt(T*Tc) = sqrt(T/Tc)
    # So T*da/dT = -ac*kappa*f*sqrt(T/Tc)
    # T*da/dT - a = -ac*kappa*f*sqrt(T/Tc) - ac*f^2
    #             = -ac*f*(kappa*sqrt(T/Tc) + f)
    #             = -ac*f*(kappa*sqrt(Tr) + 1 + kappa*(1-sqrt(Tr)))
    #             = -ac*f*(1 + kappa)
    # So T*da/dT - a = -ac*(1+kappa)*sqrt(alpha)
    coeff = -ac * (1.0 + kap) * math.sqrt(al)
    log_term = math.log((Z + (1.0 + SQRT2) * B) / (Z + (1.0 - SQRT2) * B))
    return R * T * (Z - 1.0) + coeff / (b * 2.0 * SQRT2) * log_term


def _hvap(T, comp):
    psat = _vapor_pressure(T, comp)
    return (_enthalpy_departure(T, psat, comp, True)
            - _enthalpy_departure(T, psat, comp, False))


def _z_liquid_sat(T, comp):
    """Liquid compressibility factor at saturation."""
    psat = _vapor_pressure(T, comp)
    a = comp.a(T)
    b = comp.b
    A = a * psat / (R ** 2 * T ** 2)
    B = b * psat / (R * T)
    roots = _solve_cubic_pr(A, B)
    return roots[0]  # smallest root = liquid Z


def _cv_residual(T, P, comp, vapor=True):
    """Residual isochoric heat capacity from PR EoS."""
    a_val = comp.a(T)
    b = comp.b
    ac = comp.ac
    kap = comp.kappa
    al = comp.alpha(T)

    A = a_val * P / (R ** 2 * T ** 2)
    B = b * P / (R * T)
    roots = _solve_cubic_pr(A, B)
    Z = roots[-1] if vapor else roots[0]

    # d^2 a / dT^2
    # f = 1 + kappa*(1 - sqrt(T/Tc))
    # f' = -kappa / (2*sqrt(T*Tc))
    # f'' = kappa / (4*T*sqrt(T*Tc))
    # a = ac * f^2
    # a'' = 2*ac*(f'^2 + f*f'')
    #      = 2*ac*(kappa^2/(4*T*Tc) + f*kappa/(4*T*sqrt(T*Tc)))
    #      = ac*kappa/(2*T) * (kappa/Tc + f/sqrt(T*Tc))
    #      = ac*kappa/(2*T) * (kappa/Tc + sqrt(alpha)/sqrt(T*Tc))
    d2a_dT2 = ac * kap / (2.0 * T) * (
        kap / comp.tc + math.sqrt(al) / math.sqrt(T * comp.tc)
    )

    log_term = math.log(
        (Z + (1.0 + SQRT2) * B) / (Z + (1.0 - SQRT2) * B)
    )

    return T * d2a_dT2 / (2.0 * SQRT2 * b) * log_term


# ============================================================
# Component definitions (must match components.json)
# ============================================================

propane = PRComponent(369.96, 4250000.0, 0.153)
butane = PRComponent(425.2, 3800000.0, 0.199)
pentane = PRComponent(469.7, 3370000.0, 0.2515)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="module")
def reference():
    """Compute all reference values from the Python PR implementation."""
    ref = {}
    ref["propane_psat"] = _vapor_pressure(300.0, propane)
    ref["butane_psat"] = _vapor_pressure(350.0, butane)
    ref["bubble_p"] = _bubble_point(
        300.0, [propane, butane], [0.4, 0.6], [[0, 0], [0, 0]])
    ref["dew_p"] = _dew_point(
        300.0, [propane, butane], [0.4, 0.6], [[0, 0], [0, 0]])
    beta, x, y = _flash_tp(
        300.0, 250000.0,
        [propane, butane, pentane],
        [0.2, 0.3, 0.5],
        [[0, 0, 0], [0, 0, 0], [0, 0, 0]])
    ref["flash_beta"] = beta
    ref["flash_x"] = x
    ref["flash_y"] = y
    ref["hvap"] = _hvap(300.0, propane)
    ref["z_liq"] = _z_liquid_sat(300.0, propane)
    psat_propane = ref["propane_psat"]
    ref["cv_res"] = _cv_residual(300.0, psat_propane, propane, vapor=False)
    return ref


@pytest.fixture(scope="module")
def agent():
    """Load agent results from /app/results.json."""
    p = Path("/app/results.json")
    if not p.exists():
        pytest.fail("/app/results.json not found")
    with open(p) as f:
        return json.load(f)


# ============================================================
# Tests
# ============================================================

class TestResultsFormat:
    """Verify the output file structure."""

    def test_all_keys_present(self, agent):
        required = [
            "propane_psat_300K_Pa",
            "butane_psat_350K_Pa",
            "propane_butane_bubble_300K_Pa",
            "propane_butane_dew_300K_Pa",
            "flash_vapor_fraction",
            "flash_liquid_composition",
            "flash_vapor_composition",
            "propane_hvap_300K_J_per_mol",
            "propane_z_liq_300K",
            "propane_cv_res_liq_300K_J_per_molK",
        ]
        for key in required:
            assert key in agent, f"Missing key: {key}"

    def test_flash_composition_lengths(self, agent):
        assert len(agent["flash_liquid_composition"]) == 3
        assert len(agent["flash_vapor_composition"]) == 3


class TestPureVaporPressure:
    """Verify pure-component saturation pressures."""

    def test_propane_psat_300K(self, agent, reference):
        ref = reference["propane_psat"]
        val = agent["propane_psat_300K_Pa"]
        rel = abs(val - ref) / ref
        assert rel < 1e-3, (
            f"Propane Psat 300K: got {val:.2f}, ref {ref:.2f}, rel_err {rel:.2e}")

    def test_butane_psat_350K(self, agent, reference):
        ref = reference["butane_psat"]
        val = agent["butane_psat_350K_Pa"]
        rel = abs(val - ref) / ref
        assert rel < 1e-3, (
            f"Butane Psat 350K: got {val:.2f}, ref {ref:.2f}, rel_err {rel:.2e}")

    def test_propane_psat_sign(self, agent):
        assert agent["propane_psat_300K_Pa"] > 0

    def test_butane_psat_sign(self, agent):
        assert agent["butane_psat_350K_Pa"] > 0


class TestBubblePoint:
    """Verify binary bubble-point pressure."""

    def test_bubble_point_value(self, agent, reference):
        ref = reference["bubble_p"]
        val = agent["propane_butane_bubble_300K_Pa"]
        rel = abs(val - ref) / ref
        assert rel < 1e-3, (
            f"Bubble P: got {val:.2f}, ref {ref:.2f}, rel_err {rel:.2e}")

    def test_bubble_between_pure_psats(self, agent, reference):
        p_propane = reference["propane_psat"]
        p_butane = _vapor_pressure(300.0, butane)
        val = agent["propane_butane_bubble_300K_Pa"]
        lo = min(p_propane, p_butane) * 0.5
        hi = max(p_propane, p_butane) * 1.5
        assert lo < val < hi, (
            f"Bubble P {val:.0f} outside plausible range [{lo:.0f}, {hi:.0f}]")


class TestDewPoint:
    """Verify binary dew-point pressure."""

    def test_dew_point_value(self, agent, reference):
        ref = reference["dew_p"]
        val = agent["propane_butane_dew_300K_Pa"]
        rel = abs(val - ref) / ref
        assert rel < 1e-3, (
            f"Dew P: got {val:.2f}, ref {ref:.2f}, rel_err {rel:.2e}")

    def test_dew_point_positive(self, agent):
        assert agent["propane_butane_dew_300K_Pa"] > 0

    def test_dew_below_bubble(self, agent):
        """For the same y as x in a non-azeotropic system,
        dew P should differ from bubble P."""
        bubble = agent["propane_butane_bubble_300K_Pa"]
        dew = agent["propane_butane_dew_300K_Pa"]
        # dew point for y=[0.4,0.6] should differ from bubble for x=[0.4,0.6]
        assert abs(dew - bubble) / bubble > 0.01, (
            f"Dew and bubble pressures are suspiciously close: "
            f"dew={dew:.0f}, bubble={bubble:.0f}")

    def test_dew_plausible_range(self, agent, reference):
        p_propane = reference["propane_psat"]
        p_butane = _vapor_pressure(300.0, butane)
        val = agent["propane_butane_dew_300K_Pa"]
        lo = min(p_propane, p_butane) * 0.3
        hi = max(p_propane, p_butane) * 1.5
        assert lo < val < hi, (
            f"Dew P {val:.0f} outside plausible range [{lo:.0f}, {hi:.0f}]")


class TestFlash:
    """Verify ternary isothermal flash results."""

    def test_vapor_fraction(self, agent, reference):
        ref = reference["flash_beta"]
        val = agent["flash_vapor_fraction"]
        assert abs(val - ref) < 0.005, (
            f"Flash beta: got {val:.6f}, ref {ref:.6f}")

    def test_vapor_fraction_in_range(self, agent):
        beta = agent["flash_vapor_fraction"]
        assert 0.0 <= beta <= 1.0, f"beta={beta} out of [0,1]"

    def test_liquid_composition_sum(self, agent):
        x = agent["flash_liquid_composition"]
        assert abs(sum(x) - 1.0) < 1e-3, f"sum(x_liq)={sum(x)}"

    def test_vapor_composition_sum(self, agent):
        y = agent["flash_vapor_composition"]
        assert abs(sum(y) - 1.0) < 1e-3, f"sum(y_vap)={sum(y)}"

    def test_liquid_composition_values(self, agent, reference):
        ref_x = reference["flash_x"]
        val_x = agent["flash_liquid_composition"]
        for i in range(3):
            assert abs(val_x[i] - ref_x[i]) < 0.005, (
                f"x_liq[{i}]: got {val_x[i]:.6f}, ref {ref_x[i]:.6f}")

    def test_vapor_composition_values(self, agent, reference):
        ref_y = reference["flash_y"]
        val_y = agent["flash_vapor_composition"]
        for i in range(3):
            assert abs(val_y[i] - ref_y[i]) < 0.005, (
                f"y_vap[{i}]: got {val_y[i]:.6f}, ref {ref_y[i]:.6f}")

    def test_material_balance(self, agent):
        """Check z_i = beta*y_i + (1-beta)*x_i."""
        z = [0.2, 0.3, 0.5]
        beta = agent["flash_vapor_fraction"]
        x = agent["flash_liquid_composition"]
        y = agent["flash_vapor_composition"]
        for i in range(3):
            z_calc = beta * y[i] + (1.0 - beta) * x[i]
            assert abs(z_calc - z[i]) < 0.005, (
                f"Material balance component {i}: z_calc={z_calc:.6f}, z={z[i]}")


class TestEnthalpyOfVaporization:
    """Verify enthalpy of vaporization."""

    def test_hvap_value(self, agent, reference):
        ref = reference["hvap"]
        val = agent["propane_hvap_300K_J_per_mol"]
        rel = abs(val - ref) / abs(ref)
        assert rel < 0.005, (
            f"Hvap: got {val:.2f}, ref {ref:.2f}, rel_err {rel:.2e}")

    def test_hvap_positive(self, agent):
        assert agent["propane_hvap_300K_J_per_mol"] > 0, (
            "Enthalpy of vaporization must be positive")

    def test_hvap_plausible_range(self, agent):
        val = agent["propane_hvap_300K_J_per_mol"]
        assert 8000 < val < 25000, (
            f"Hvap {val:.0f} J/mol outside plausible range for propane at 300 K")


class TestLiquidCompressibility:
    """Verify liquid-phase compressibility factor at saturation."""

    def test_z_liq_value(self, agent, reference):
        ref = reference["z_liq"]
        val = agent["propane_z_liq_300K"]
        rel = abs(val - ref) / ref
        assert rel < 1e-3, (
            f"Z_liq: got {val:.6f}, ref {ref:.6f}, rel_err {rel:.2e}")

    def test_z_liq_less_than_one(self, agent):
        """Liquid Z should be much less than 1."""
        val = agent["propane_z_liq_300K"]
        assert 0.0 < val < 0.2, (
            f"Z_liq={val:.6f} outside plausible liquid range (0, 0.2)")

    def test_z_liq_greater_than_B(self, agent):
        """Z must be greater than B for physical solutions."""
        psat = agent["propane_psat_300K_Pa"]
        B = propane.b * psat / (R * 300.0)
        val = agent["propane_z_liq_300K"]
        assert val > B, f"Z_liq={val:.6f} < B={B:.6f}"


class TestResidualCv:
    """Verify residual isochoric heat capacity of liquid at saturation."""

    def test_cv_res_value(self, agent, reference):
        ref = reference["cv_res"]
        val = agent["propane_cv_res_liq_300K_J_per_molK"]
        rel = abs(val - ref) / abs(ref)
        assert rel < 0.01, (
            f"Cv_res: got {val:.4f}, ref {ref:.4f}, rel_err {rel:.2e}")

    def test_cv_res_positive(self, agent):
        val = agent["propane_cv_res_liq_300K_J_per_molK"]
        assert val > 0, "Residual Cv must be positive"

    def test_cv_res_plausible_range(self, agent):
        """Residual Cv for liquid propane at 300 K should be in a reasonable range."""
        val = agent["propane_cv_res_liq_300K_J_per_molK"]
        assert 10 < val < 100, (
            f"Cv_res={val:.2f} J/(mol K) outside plausible range [10, 100]")
