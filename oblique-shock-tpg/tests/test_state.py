"""
Tests for the Thermally Perfect Gas Oblique Shock Solver.

Verifies:
1. Output file exists and has correct structure
2. CPG-regime values match exact calorically perfect gas formulas
3. Ideal gas law consistency across all shocks
4. Physical constraints (entropy increase, shock ordering)
5. TPG-regime behavior (reduced gamma at high temperatures)
6. Detachment angles are physically reasonable

"""

import json
import math
import os

import numpy as np
import pytest
from scipy.optimize import brentq, minimize_scalar

RESULTS_PATH = "/app/results/flow_tables.json"
GAMMA_CPG = 1.4


# ------------------------------------------------------------------ #
#  CPG reference functions                                            #
# ------------------------------------------------------------------ #

def cpg_static_T(Tt, M, gamma=GAMMA_CPG):
    return Tt / (1.0 + (gamma - 1.0) / 2.0 * M ** 2)


def cpg_normal_shock(M1, gamma=GAMMA_CPG):
    g = gamma
    M2_sq = (M1 ** 2 + 2.0 / (g - 1)) / (2.0 * g / (g - 1) * M1 ** 2 - 1.0)
    P_ratio = (2.0 * g * M1 ** 2 - (g - 1)) / (g + 1)
    rho_ratio = (g + 1) * M1 ** 2 / (2.0 + (g - 1) * M1 ** 2)
    T_ratio = P_ratio / rho_ratio
    Pt_ratio = (
        ((g + 1) * M1 ** 2 / (2.0 + (g - 1) * M1 ** 2)) ** (g / (g - 1))
        * ((g + 1) / (2.0 * g * M1 ** 2 - (g - 1))) ** (1.0 / (g - 1))
    )
    return {
        "M2": math.sqrt(max(M2_sq, 0)),
        "P2_P1": P_ratio,
        "T2_T1": T_ratio,
        "rho2_rho1": rho_ratio,
        "Pt2_Pt1": Pt_ratio,
    }


def cpg_theta_from_beta(M, beta_rad, gamma=GAMMA_CPG):
    g = gamma
    sb2 = math.sin(beta_rad) ** 2
    num = 2.0 * math.cos(beta_rad) / math.sin(beta_rad) * (M ** 2 * sb2 - 1.0)
    den = M ** 2 * (g + math.cos(2.0 * beta_rad)) + 2.0
    if den == 0:
        return 0.0
    return math.atan2(num, den)


def cpg_find_beta(M, theta_deg, gamma=GAMMA_CPG, shock_type="weak"):
    theta_target = math.radians(theta_deg)
    mu = math.asin(1.0 / M)

    def neg_theta(b):
        return -cpg_theta_from_beta(M, b, gamma)

    res = minimize_scalar(neg_theta, bounds=(mu + 0.001, math.pi / 2 - 0.001), method="bounded")
    beta_det = res.x
    theta_max = -res.fun

    if theta_target > theta_max:
        return None

    def f(b):
        return cpg_theta_from_beta(M, b, gamma) - theta_target

    if shock_type == "weak":
        b_lo, b_hi = mu + 0.001, beta_det - 0.0001
    else:
        b_lo, b_hi = beta_det + 0.0001, math.pi / 2 - 0.001

    if f(b_lo) * f(b_hi) > 0:
        return None
    return math.degrees(brentq(f, b_lo, b_hi, xtol=1e-10))


def cpg_detachment_angle(M, gamma=GAMMA_CPG):
    mu = math.asin(1.0 / M)

    def neg_theta(b):
        return -cpg_theta_from_beta(M, b, gamma)

    res = minimize_scalar(neg_theta, bounds=(mu + 0.001, math.pi / 2 - 0.001), method="bounded")
    return math.degrees(-res.fun)


# ------------------------------------------------------------------ #
#  Fixtures                                                           #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Output file not found: {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ------------------------------------------------------------------ #
#  Test: output structure                                             #
# ------------------------------------------------------------------ #

class TestOutputStructure:

    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_all_conditions_present(self, results):
        expected = {"case_1", "case_2", "case_3", "case_4", "case_5", "case_6"}
        assert expected.issubset(set(results.keys())), (
            f"Missing conditions: {expected - set(results.keys())}"
        )

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_freestream_keys(self, results, case_id):
        fs = results[case_id]["freestream"]
        assert "T_static_K" in fs
        assert "gamma_effective" in fs

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_normal_shock_keys(self, results, case_id):
        ns = results[case_id]["normal_shock"]
        for k in ("M2", "P2_P1", "T2_T1", "rho2_rho1", "Pt2_Pt1"):
            assert k in ns, f"Missing key {k} in normal_shock for {case_id}"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_oblique_shock_keys(self, results, case_id):
        for stype in ("weak_shock", "strong_shock"):
            assert stype in results[case_id], f"Missing {stype} for {case_id}"
            shock = results[case_id][stype]
            for k in ("beta_deg", "M2", "P2_P1", "T2_T1", "rho2_rho1", "Pt2_Pt1"):
                assert k in shock, f"Missing key {k} in {stype} for {case_id}"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_detachment_present(self, results, case_id):
        assert "detachment_angle_deg" in results[case_id]


# ------------------------------------------------------------------ #
#  Test: CPG-regime validation (cases 1 & 2 at Tt=400K, M=2)         #
# ------------------------------------------------------------------ #

class TestCPGValidation:
    """
    At Tt=400K, freestream T ~ 222K and post-shock T < 400K.
    At these temperatures gamma ~ 1.400, so results should match CPG formulas.
    """

    CPG_TOL = 0.005  # 0.5% relative tolerance

    def test_case1_gamma(self, results):
        gamma = results["case_1"]["freestream"]["gamma_effective"]
        assert abs(gamma - 1.4) / 1.4 < 0.003, f"gamma = {gamma}, expected ~1.4"

    def test_case1_static_T(self, results):
        T1 = results["case_1"]["freestream"]["T_static_K"]
        T1_cpg = cpg_static_T(400.0, 2.0)
        assert abs(T1 - T1_cpg) / T1_cpg < self.CPG_TOL, (
            f"T1={T1:.2f}, expected ~{T1_cpg:.2f}"
        )

    def test_case1_normal_shock_M2(self, results):
        ref = cpg_normal_shock(2.0)
        val = results["case_1"]["normal_shock"]["M2"]
        assert abs(val - ref["M2"]) / ref["M2"] < self.CPG_TOL, (
            f"M2={val:.4f}, expected ~{ref['M2']:.4f}"
        )

    def test_case1_normal_shock_P_ratio(self, results):
        ref = cpg_normal_shock(2.0)
        val = results["case_1"]["normal_shock"]["P2_P1"]
        assert abs(val - ref["P2_P1"]) / ref["P2_P1"] < self.CPG_TOL

    def test_case1_normal_shock_T_ratio(self, results):
        ref = cpg_normal_shock(2.0)
        val = results["case_1"]["normal_shock"]["T2_T1"]
        assert abs(val - ref["T2_T1"]) / ref["T2_T1"] < self.CPG_TOL

    def test_case1_normal_shock_rho_ratio(self, results):
        ref = cpg_normal_shock(2.0)
        val = results["case_1"]["normal_shock"]["rho2_rho1"]
        assert abs(val - ref["rho2_rho1"]) / ref["rho2_rho1"] < self.CPG_TOL

    def test_case1_normal_shock_Pt_ratio(self, results):
        ref = cpg_normal_shock(2.0)
        val = results["case_1"]["normal_shock"]["Pt2_Pt1"]
        assert abs(val - ref["Pt2_Pt1"]) / ref["Pt2_Pt1"] < self.CPG_TOL

    def test_case1_weak_beta(self, results):
        ref_beta = cpg_find_beta(2.0, 15.0, shock_type="weak")
        val = results["case_1"]["weak_shock"]["beta_deg"]
        assert abs(val - ref_beta) < 0.3, f"beta_weak={val:.2f}, expected ~{ref_beta:.2f}"

    def test_case1_strong_beta(self, results):
        ref_beta = cpg_find_beta(2.0, 15.0, shock_type="strong")
        val = results["case_1"]["strong_shock"]["beta_deg"]
        assert abs(val - ref_beta) < 0.3, f"beta_strong={val:.2f}, expected ~{ref_beta:.2f}"

    def test_case1_detachment(self, results):
        ref = cpg_detachment_angle(2.0)
        val = results["case_1"]["detachment_angle_deg"]
        assert abs(val - ref) < 0.5, f"detach={val:.2f}, expected ~{ref:.2f}"

    def test_case2_weak_beta(self, results):
        ref_beta = cpg_find_beta(2.0, 20.0, shock_type="weak")
        val = results["case_2"]["weak_shock"]["beta_deg"]
        assert abs(val - ref_beta) < 0.3, f"beta_weak={val:.2f}, expected ~{ref_beta:.2f}"


# ------------------------------------------------------------------ #
#  Test: ideal gas law consistency rho = P / (R*T)                    #
# ------------------------------------------------------------------ #

class TestIdealGasConsistency:
    """For any shock, rho2/rho1 must equal (P2/P1) / (T2/T1)."""

    TOL = 0.002  # 0.2%

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_normal_shock_consistency(self, results, case_id):
        ns = results[case_id]["normal_shock"]
        rho_from_PT = ns["P2_P1"] / ns["T2_T1"]
        rho_direct = ns["rho2_rho1"]
        assert abs(rho_from_PT - rho_direct) / rho_direct < self.TOL, (
            f"{case_id}: rho ratio mismatch: {rho_from_PT:.4f} vs {rho_direct:.4f}"
        )

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_weak_shock_consistency(self, results, case_id):
        ws = results[case_id]["weak_shock"]
        rho_from_PT = ws["P2_P1"] / ws["T2_T1"]
        rho_direct = ws["rho2_rho1"]
        assert abs(rho_from_PT - rho_direct) / rho_direct < self.TOL

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_strong_shock_consistency(self, results, case_id):
        ss = results[case_id]["strong_shock"]
        rho_from_PT = ss["P2_P1"] / ss["T2_T1"]
        rho_direct = ss["rho2_rho1"]
        assert abs(rho_from_PT - rho_direct) / rho_direct < self.TOL


# ------------------------------------------------------------------ #
#  Test: physical constraints                                         #
# ------------------------------------------------------------------ #

class TestPhysicalConstraints:

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_normal_shock_entropy_increase(self, results, case_id):
        """Total pressure must decrease across a shock (entropy increases)."""
        Pt_ratio = results[case_id]["normal_shock"]["Pt2_Pt1"]
        assert 0 < Pt_ratio < 1.0, f"{case_id}: Pt2/Pt1 = {Pt_ratio}"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_oblique_entropy_increase(self, results, case_id):
        for stype in ("weak_shock", "strong_shock"):
            Pt_ratio = results[case_id][stype]["Pt2_Pt1"]
            assert 0 < Pt_ratio < 1.0, f"{case_id} {stype}: Pt2/Pt1 = {Pt_ratio}"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_weak_less_than_strong_beta(self, results, case_id):
        beta_w = results[case_id]["weak_shock"]["beta_deg"]
        beta_s = results[case_id]["strong_shock"]["beta_deg"]
        assert beta_w < beta_s, (
            f"{case_id}: weak beta {beta_w:.2f} >= strong beta {beta_s:.2f}"
        )

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_weak_M2_greater_than_strong(self, results, case_id):
        M2_w = results[case_id]["weak_shock"]["M2"]
        M2_s = results[case_id]["strong_shock"]["M2"]
        assert M2_w > M2_s, (
            f"{case_id}: weak M2 {M2_w:.4f} <= strong M2 {M2_s:.4f}"
        )

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_normal_M2_less_than_one(self, results, case_id):
        M2 = results[case_id]["normal_shock"]["M2"]
        assert M2 < 1.0, f"{case_id}: normal shock M2 = {M2:.4f} >= 1.0"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_strong_shock_M2_less_than_one(self, results, case_id):
        M2 = results[case_id]["strong_shock"]["M2"]
        assert M2 < 1.0, f"{case_id}: strong shock M2 = {M2:.4f} >= 1.0"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_shock_wave_angle_bounds(self, results, case_id):
        cond_mach = {"case_1": 2.0, "case_2": 2.0, "case_3": 3.0,
                     "case_4": 5.0, "case_5": 5.0, "case_6": 8.0}
        M = cond_mach[case_id]
        mu = math.degrees(math.asin(1.0 / M))
        beta_w = results[case_id]["weak_shock"]["beta_deg"]
        beta_s = results[case_id]["strong_shock"]["beta_deg"]
        assert beta_w > mu, f"{case_id}: weak beta {beta_w:.2f} <= Mach angle {mu:.2f}"
        assert beta_s <= 90.0, f"{case_id}: strong beta {beta_s:.2f} > 90"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_detachment_angle_reasonable(self, results, case_id):
        theta_max = results[case_id]["detachment_angle_deg"]
        assert 5.0 < theta_max < 55.0, (
            f"{case_id}: detach angle {theta_max:.2f} outside expected range"
        )

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_pressure_ratio_increases(self, results, case_id):
        for stype in ("normal_shock", "weak_shock", "strong_shock"):
            P_ratio = results[case_id][stype]["P2_P1"]
            assert P_ratio > 1.0, f"{case_id} {stype}: P2/P1 = {P_ratio:.4f} <= 1"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_temperature_ratio_increases(self, results, case_id):
        for stype in ("normal_shock", "weak_shock", "strong_shock"):
            T_ratio = results[case_id][stype]["T2_T1"]
            assert T_ratio > 1.0, f"{case_id} {stype}: T2/T1 = {T_ratio:.4f} <= 1"

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_normal_stronger_than_oblique(self, results, case_id):
        """Normal shock should produce the largest pressure ratio."""
        ns_P = results[case_id]["normal_shock"]["P2_P1"]
        ws_P = results[case_id]["weak_shock"]["P2_P1"]
        ss_P = results[case_id]["strong_shock"]["P2_P1"]
        assert ns_P >= ss_P >= ws_P, (
            f"{case_id}: pressure ordering violated: NS={ns_P:.2f}, SS={ss_P:.2f}, WS={ws_P:.2f}"
        )


# ------------------------------------------------------------------ #
#  Test: TPG-regime behavior                                          #
# ------------------------------------------------------------------ #

class TestTPGBehavior:
    """Cases 3-6 have high total temperatures where gamma departs from 1.4."""

    @pytest.mark.parametrize("case_id", ["case_3", "case_4", "case_5"])
    def test_reduced_gamma(self, results, case_id):
        """Cases with T1 > 400K should show gamma_eff < 1.39."""
        gamma = results[case_id]["freestream"]["gamma_effective"]
        assert gamma < 1.39, (
            f"{case_id}: gamma = {gamma:.4f}, expected < 1.39 for TPG regime"
        )

    @pytest.mark.parametrize("case_id", ["case_3", "case_4", "case_5", "case_6"])
    def test_gamma_above_minimum(self, results, case_id):
        gamma = results[case_id]["freestream"]["gamma_effective"]
        assert gamma > 1.1, f"{case_id}: gamma = {gamma:.4f} unreasonably low"

    def test_case6_tpg_density_exceeds_cpg(self, results):
        """
        At M=8, the TPG normal shock density ratio should exceed
        the CPG value because gamma drops across the shock as T rises.
        """
        ns_tpg = results["case_6"]["normal_shock"]["rho2_rho1"]
        M = 8.0
        cpg_rho = (GAMMA_CPG + 1) * M**2 / (2 + (GAMMA_CPG - 1) * M**2)
        assert ns_tpg > cpg_rho * 1.05, (
            f"M=8 TPG rho2/rho1 = {ns_tpg:.3f}, expected > CPG value {cpg_rho:.3f} * 1.05"
        )

    def test_case3_detachment_differs_from_cpg(self, results):
        """TPG detachment angle should differ from CPG for same Mach number."""
        det_tpg = results["case_3"]["detachment_angle_deg"]
        det_cpg = cpg_detachment_angle(3.0)
        assert abs(det_tpg - det_cpg) > 0.5, (
            f"TPG detach={det_tpg:.2f}, CPG detach={det_cpg:.2f}: "
            "TPG should differ from CPG by > 0.5 deg"
        )

    def test_case6_high_mach_normal_shock(self, results):
        """M=8 normal shock: very high pressure and temperature ratios."""
        ns = results["case_6"]["normal_shock"]
        assert ns["P2_P1"] > 50.0, f"M=8 P2/P1 = {ns['P2_P1']:.2f}, expected > 50"
        assert ns["T2_T1"] > 5.0, f"M=8 T2/T1 = {ns['T2_T1']:.2f}, expected > 5"

    def test_tpg_normal_shock_density_limit(self, results):
        """
        For high Mach TPG, density ratio should exceed the CPG limit of
        (gamma+1)/(gamma-1) = 6.0 because effective gamma < 1.4.
        """
        ns = results["case_6"]["normal_shock"]
        cpg_limit = (GAMMA_CPG + 1) / (GAMMA_CPG - 1)  # 6.0
        gamma_eff = results["case_6"]["freestream"]["gamma_effective"]
        tpg_limit = (gamma_eff + 1) / (gamma_eff - 1)
        # For M=8, rho ratio approaches the limit; it should exceed CPG limit
        # since gamma < 1.4 implies (g+1)/(g-1) > 6
        assert ns["rho2_rho1"] > cpg_limit * 0.90, (
            f"M=8 rho ratio = {ns['rho2_rho1']:.3f}, "
            f"expected near TPG limit = {tpg_limit:.2f}"
        )


# ------------------------------------------------------------------ #
#  Test: cross-validation between normal and oblique shock             #
# ------------------------------------------------------------------ #

class TestCrossValidation:

    @pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"])
    def test_strong_shock_weaker_than_normal(self, results, case_id):
        """Strong oblique shock should have lower pressure ratio than normal shock."""
        ns_P = results[case_id]["normal_shock"]["P2_P1"]
        ss_P = results[case_id]["strong_shock"]["P2_P1"]
        assert ss_P <= ns_P * 1.001, (
            f"{case_id}: strong oblique P2/P1={ss_P:.4f} > normal P2/P1={ns_P:.4f}"
        )

    @pytest.mark.parametrize("case_id", ["case_1", "case_2"])
    def test_cpg_weak_M2_supersonic(self, results, case_id):
        """At M=2 with moderate deflection, weak shock should be supersonic."""
        M2_w = results[case_id]["weak_shock"]["M2"]
        assert M2_w > 1.0, f"{case_id}: weak shock M2 = {M2_w:.4f}, expected > 1.0"
