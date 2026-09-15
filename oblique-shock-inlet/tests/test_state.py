"""
Tests for the multi-ramp supersonic inlet performance analyzer.
Uses an independent reference implementation for CPG oblique shock relations.
"""

import json
import math
import os
import pytest
import numpy as np
from scipy.optimize import brentq, minimize_scalar

RESULTS_PATH = "/app/results.json"
CONFIG_PATH = "/app/inlet_config.json"
RTOL = 2e-3  # 0.2% relative tolerance for CPG cases


# ===== Independent CPG reference implementation =====

def _ref_theta_from_beta(M, beta_rad, gamma=1.4):
    """Compute flow deflection angle from Mach number and shock angle."""
    sin2b = math.sin(beta_rad) ** 2
    Mn1_sq = M ** 2 * sin2b
    if Mn1_sq <= 1.0:
        return 0.0
    num = 2.0 * (Mn1_sq - 1.0) / math.tan(beta_rad)
    den = M ** 2 * (gamma + math.cos(2.0 * beta_rad)) + 2.0
    if abs(den) < 1e-15:
        return 0.0
    return math.atan2(num, den)


def _ref_solve_weak_beta(M, theta_deg, gamma=1.4):
    """Solve theta-beta-M relation for weak shock angle."""
    theta_rad = math.radians(theta_deg)
    mu = math.asin(1.0 / M)

    res = minimize_scalar(
        lambda b: -_ref_theta_from_beta(M, b, gamma),
        bounds=(mu + 1e-8, math.pi / 2 - 1e-8),
        method="bounded",
    )
    beta_peak = res.x

    if theta_rad > -res.fun + 1e-10:
        raise ValueError("Detached shock")

    beta = brentq(
        lambda b: _ref_theta_from_beta(M, b, gamma) - theta_rad,
        mu + 1e-10,
        beta_peak - 1e-10,
    )
    return beta


def _ref_normal_shock(Mn1, gamma=1.4):
    """Compute CPG normal shock properties from upstream normal Mach number."""
    Mn1_sq = Mn1 ** 2
    gp1 = gamma + 1.0
    gm1 = gamma - 1.0

    P_ratio = (2.0 * gamma * Mn1_sq - gm1) / gp1
    rho_ratio = gp1 * Mn1_sq / (gm1 * Mn1_sq + 2.0)
    T_ratio = P_ratio / rho_ratio
    Mn2 = math.sqrt((gm1 * Mn1_sq + 2.0) / (2.0 * gamma * Mn1_sq - gm1))

    # Total pressure ratio (Rayleigh Pitot tube formula)
    term1 = (gp1 * Mn1_sq / (gm1 * Mn1_sq + 2.0)) ** (gamma / gm1)
    term2 = (gp1 / (2.0 * gamma * Mn1_sq - gm1)) ** (1.0 / gm1)
    Pt_ratio = term1 * term2

    return {
        "P_ratio": P_ratio,
        "T_ratio": T_ratio,
        "rho_ratio": rho_ratio,
        "Mn2": Mn2,
        "Pt_ratio": Pt_ratio,
    }


def _ref_oblique_shock(M1, theta_deg, gamma=1.4):
    """Full CPG oblique shock solution (weak)."""
    beta_rad = _ref_solve_weak_beta(M1, theta_deg, gamma)
    theta_rad = math.radians(theta_deg)

    Mn1 = M1 * math.sin(beta_rad)
    ns = _ref_normal_shock(Mn1, gamma)

    M2 = ns["Mn2"] / math.sin(beta_rad - theta_rad)

    return {
        "shock_angle_deg": math.degrees(beta_rad),
        "downstream_mach": M2,
        "pressure_ratio": ns["P_ratio"],
        "temperature_ratio": ns["T_ratio"],
        "density_ratio": ns["rho_ratio"],
        "total_pressure_ratio": ns["Pt_ratio"],
    }


def _ref_inlet(M_inf, ramp_angles_deg, gamma=1.4):
    """Compute full inlet analysis: oblique shocks + terminal normal shock."""
    M = M_inf
    overall_Pt = 1.0
    shocks = []

    for theta in ramp_angles_deg:
        s = _ref_oblique_shock(M, theta, gamma)
        shocks.append(s)
        M = s["downstream_mach"]
        overall_Pt *= s["total_pressure_ratio"]

    ns = _ref_normal_shock(M, gamma)
    overall_Pt *= ns["Pt_ratio"]

    return {
        "oblique_shocks": shocks,
        "terminal_upstream_mach": M,
        "terminal_Pt_ratio": ns["Pt_ratio"],
        "terminal_downstream_mach": ns["Mn2"],
        "overall_total_pressure_recovery": overall_Pt,
    }


# ===== Helper =====

def _close(a, b, rtol=RTOL):
    """Check if two values are relatively close."""
    if abs(b) < 1e-12:
        return abs(a) < 1e-8
    return abs(a - b) / abs(b) < rtol


# ===== Fixtures =====

@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ===== Tests =====

class TestResultsStructure:
    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_all_cases_present(self, results):
        for name in [
            "case_single_ramp",
            "case_two_ramp",
            "case_three_ramp",
            "case_optimize_2ramp",
            "case_optimize_3ramp",
            "case_tpg",
        ]:
            assert name in results, f"Missing case: {name}"


class TestSingleRamp:
    """M=2.0, delta=15 deg, gamma=1.4, single ramp + terminal normal shock."""

    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.case = results["case_single_ramp"]
        self.ref = _ref_oblique_shock(2.0, 15.0, 1.4)
        self.ref_inlet = _ref_inlet(2.0, [15.0], 1.4)

    def test_shock_count(self):
        assert len(self.case["oblique_shocks"]) == 1

    def test_shock_angle(self):
        got = self.case["oblique_shocks"][0]["shock_angle_deg"]
        assert _close(got, self.ref["shock_angle_deg"]), (
            f"shock_angle_deg: got {got}, expected {self.ref['shock_angle_deg']:.4f}"
        )

    def test_downstream_mach(self):
        got = self.case["oblique_shocks"][0]["downstream_mach"]
        assert _close(got, self.ref["downstream_mach"]), (
            f"downstream_mach: got {got}, expected {self.ref['downstream_mach']:.4f}"
        )

    def test_pressure_ratio(self):
        got = self.case["oblique_shocks"][0]["pressure_ratio"]
        assert _close(got, self.ref["pressure_ratio"]), (
            f"pressure_ratio: got {got}, expected {self.ref['pressure_ratio']:.4f}"
        )

    def test_temperature_ratio(self):
        got = self.case["oblique_shocks"][0]["temperature_ratio"]
        assert _close(got, self.ref["temperature_ratio"]), (
            f"temperature_ratio: got {got}, expected {self.ref['temperature_ratio']:.4f}"
        )

    def test_total_pressure_ratio(self):
        got = self.case["oblique_shocks"][0]["total_pressure_ratio"]
        assert _close(got, self.ref["total_pressure_ratio"]), (
            f"total_pressure_ratio: got {got}, expected {self.ref['total_pressure_ratio']:.6f}"
        )

    def test_terminal_shock_upstream_mach(self):
        got = self.case["terminal_normal_shock"]["upstream_mach"]
        assert _close(got, self.ref["downstream_mach"]), (
            f"terminal upstream_mach: got {got}, expected {self.ref['downstream_mach']:.4f}"
        )

    def test_terminal_shock_total_pressure(self):
        got = self.case["terminal_normal_shock"]["total_pressure_ratio"]
        assert _close(got, self.ref_inlet["terminal_Pt_ratio"]), (
            f"terminal Pt_ratio: got {got}, expected {self.ref_inlet['terminal_Pt_ratio']:.6f}"
        )

    def test_overall_recovery(self):
        got = self.case["overall_total_pressure_recovery"]
        exp = self.ref_inlet["overall_total_pressure_recovery"]
        assert _close(got, exp), (
            f"overall recovery: got {got}, expected {exp:.6f}"
        )


class TestTwoRamp:
    """M=3.0, [10, 10] deg, gamma=1.4."""

    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.case = results["case_two_ramp"]
        self.ref = _ref_inlet(3.0, [10.0, 10.0], 1.4)

    def test_shock_count(self):
        assert len(self.case["oblique_shocks"]) == 2

    def test_first_shock_angle(self):
        got = self.case["oblique_shocks"][0]["shock_angle_deg"]
        exp = self.ref["oblique_shocks"][0]["shock_angle_deg"]
        assert _close(got, exp), f"first shock angle: got {got}, expected {exp:.4f}"

    def test_second_shock_downstream_mach(self):
        got = self.case["oblique_shocks"][1]["downstream_mach"]
        exp = self.ref["oblique_shocks"][1]["downstream_mach"]
        assert _close(got, exp), f"second shock M2: got {got}, expected {exp:.4f}"

    def test_overall_recovery(self):
        got = self.case["overall_total_pressure_recovery"]
        exp = self.ref["overall_total_pressure_recovery"]
        assert _close(got, exp), f"overall recovery: got {got}, expected {exp:.6f}"


class TestThreeRamp:
    """M=4.0, [8, 8, 8] deg, gamma=1.4."""

    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.case = results["case_three_ramp"]
        self.ref = _ref_inlet(4.0, [8.0, 8.0, 8.0], 1.4)

    def test_shock_count(self):
        assert len(self.case["oblique_shocks"]) == 3

    def test_first_shock_angle(self):
        got = self.case["oblique_shocks"][0]["shock_angle_deg"]
        exp = self.ref["oblique_shocks"][0]["shock_angle_deg"]
        assert _close(got, exp), f"first shock angle: got {got}, expected {exp:.4f}"

    def test_third_shock_total_pressure(self):
        got = self.case["oblique_shocks"][2]["total_pressure_ratio"]
        exp = self.ref["oblique_shocks"][2]["total_pressure_ratio"]
        assert _close(got, exp), f"3rd shock Pt ratio: got {got}, expected {exp:.6f}"

    def test_overall_recovery(self):
        got = self.case["overall_total_pressure_recovery"]
        exp = self.ref["overall_total_pressure_recovery"]
        assert _close(got, exp), f"overall recovery: got {got}, expected {exp:.6f}"


class TestOptimize2Ramp:
    """Optimized 2-ramp inlet at M=3.0, total deflection 24 deg."""

    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.case = results["case_optimize_2ramp"]
        self.ref_equal = _ref_inlet(3.0, [12.0, 12.0], 1.4)

    def test_has_optimized_angles(self):
        assert "optimized_ramp_angles_deg" in self.case
        assert len(self.case["optimized_ramp_angles_deg"]) == 2

    def test_angles_sum_to_total(self):
        angles = self.case["optimized_ramp_angles_deg"]
        assert abs(sum(angles) - 24.0) < 0.2, (
            f"angles sum to {sum(angles)}, expected 24.0"
        )

    def test_all_angles_positive(self):
        for a in self.case["optimized_ramp_angles_deg"]:
            assert a > 0.5, f"ramp angle too small: {a}"

    def test_recovery_at_least_equal_angle(self):
        got = self.case["overall_total_pressure_recovery"]
        baseline = self.ref_equal["overall_total_pressure_recovery"]
        assert got >= baseline - 0.005, (
            f"optimized recovery {got:.6f} < baseline {baseline:.6f} - 0.005"
        )

    def test_recovery_reasonable_range(self):
        got = self.case["overall_total_pressure_recovery"]
        assert 0.55 < got < 1.0, f"recovery {got} outside reasonable range"


class TestOptimize3Ramp:
    """Optimized 3-ramp inlet at M=4.0, total deflection 30 deg."""

    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.case = results["case_optimize_3ramp"]
        self.ref_equal = _ref_inlet(4.0, [10.0, 10.0, 10.0], 1.4)

    def test_has_optimized_angles(self):
        assert "optimized_ramp_angles_deg" in self.case
        assert len(self.case["optimized_ramp_angles_deg"]) == 3

    def test_angles_sum_to_total(self):
        angles = self.case["optimized_ramp_angles_deg"]
        assert abs(sum(angles) - 30.0) < 0.2, (
            f"angles sum to {sum(angles)}, expected 30.0"
        )

    def test_recovery_at_least_equal_angle(self):
        got = self.case["overall_total_pressure_recovery"]
        baseline = self.ref_equal["overall_total_pressure_recovery"]
        assert got >= baseline - 0.005, (
            f"optimized recovery {got:.6f} < baseline {baseline:.6f} - 0.005"
        )

    def test_recovery_reasonable_range(self):
        got = self.case["overall_total_pressure_recovery"]
        assert 0.40 < got < 1.0, f"recovery {got} outside reasonable range"


class TestTPG:
    """Thermally perfect gas case: M=5.0, T=250K, two 10-deg ramps."""

    @pytest.fixture(autouse=True)
    def setup(self, results):
        self.case = results["case_tpg"]
        self.ref_cpg = _ref_inlet(5.0, [10.0, 10.0], 1.4)

    def test_has_shocks(self):
        assert len(self.case["oblique_shocks"]) == 2

    def test_has_terminal(self):
        assert "terminal_normal_shock" in self.case

    def test_has_recovery(self):
        assert "overall_total_pressure_recovery" in self.case
        got = self.case["overall_total_pressure_recovery"]
        assert 0.05 < got < 1.0, f"TPG recovery {got} outside physical range"

    def test_differs_from_cpg(self):
        """At M=5 with total temp ~1500K, TPG must differ from CPG."""
        tpg_recovery = self.case["overall_total_pressure_recovery"]
        cpg_recovery = self.ref_cpg["overall_total_pressure_recovery"]
        rel_diff = abs(tpg_recovery - cpg_recovery) / abs(cpg_recovery)
        assert rel_diff > 0.005, (
            f"TPG recovery ({tpg_recovery:.6f}) too close to CPG ({cpg_recovery:.6f}), "
            f"relative difference {rel_diff:.4f} should be > 0.005"
        )

    def test_shock_angles_physical(self):
        for s in self.case["oblique_shocks"]:
            beta = s["shock_angle_deg"]
            M_up = s["upstream_mach"]
            mu = math.degrees(math.asin(1.0 / M_up))
            assert beta > mu, f"shock angle {beta} <= Mach angle {mu:.2f}"
            assert beta < 90.0, f"shock angle {beta} >= 90"

    def test_downstream_mach_decreases(self):
        M_prev = 5.0
        for s in self.case["oblique_shocks"]:
            assert s["downstream_mach"] < M_prev, (
                f"M did not decrease: {s['downstream_mach']} >= {M_prev}"
            )
            M_prev = s["downstream_mach"]
