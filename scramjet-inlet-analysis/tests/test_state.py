"""
Tests for supersonic multi-ramp inlet oblique shock analyzer.

Verifies CPG normal/oblique shocks against exact analytical and NACA 1135 reference
values, multi-ramp sequential shock chaining, inlet optimization, and TPG conservation.

"""

import json
import math
import os
import pytest


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.exists(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        data = json.load(f)
    assert "cases" in data, "results.json must have a top-level 'cases' array"
    return data


def get_case(results, case_id):
    for case in results["cases"]:
        if case["id"] == case_id:
            return case
    pytest.fail(f"Case '{case_id}' not found in results.json")


# =========================================================================
# Normal Shock at M=2.0 (exact rational reference values)
# =========================================================================

class TestNormalShockM2:

    def test_downstream_mach(self, results):
        c = get_case(results, "normal_shock_m2")
        # Exact: M2^2 = (M1^2 + 2/(gamma-1)) / (2*gamma/(gamma-1)*M1^2 - 1)
        #       = (4+5)/(7*4-1) = 9/27 = 1/3  =>  M2 = 1/sqrt(3)
        assert abs(c["M2"] - 1.0 / math.sqrt(3)) < 1e-4

    def test_pressure_ratio(self, results):
        c = get_case(results, "normal_shock_m2")
        # Exact: p2/p1 = 1 + 2*gamma/(gamma+1)*(M1^2-1) = 1 + 7/2 = 9/2
        assert abs(c["p2_p1"] - 4.5) < 1e-4

    def test_density_ratio(self, results):
        c = get_case(results, "normal_shock_m2")
        # Exact: rho2/rho1 = (gamma+1)*M1^2 / ((gamma-1)*M1^2+2) = 9.6/3.6 = 8/3
        assert abs(c["rho2_rho1"] - 8.0 / 3.0) < 1e-4

    def test_temperature_ratio(self, results):
        c = get_case(results, "normal_shock_m2")
        # Exact: T2/T1 = (p2/p1)/(rho2/rho1) = (9/2)/(8/3) = 27/16
        assert abs(c["T2_T1"] - 27.0 / 16.0) < 1e-4

    def test_total_pressure_ratio(self, results):
        c = get_case(results, "normal_shock_m2")
        # Known: p02/p01 ~ 0.7209 for M=2 normal shock, gamma=1.4
        assert abs(c["p02_p01"] - 0.7209) < 0.003


# =========================================================================
# Normal Shock at M=4.0 (exact rational reference values)
# =========================================================================

class TestNormalShockM4:

    def test_downstream_mach(self, results):
        c = get_case(results, "normal_shock_m4")
        # M2^2 = (16+5)/(7*16-1) = 21/111 = 7/37
        expected = math.sqrt(7.0 / 37.0)
        assert abs(c["M2"] - expected) < 1e-4

    def test_pressure_ratio(self, results):
        c = get_case(results, "normal_shock_m4")
        # p2/p1 = 1 + 2*1.4/2.4*(16-1) = 1 + 7/6*15 = 1+17.5 = 18.5
        assert abs(c["p2_p1"] - 18.5) < 1e-3

    def test_density_ratio(self, results):
        c = get_case(results, "normal_shock_m4")
        # rho2/rho1 = 2.4*16/(0.4*16+2) = 38.4/8.4 = 32/7
        assert abs(c["rho2_rho1"] - 32.0 / 7.0) < 1e-3

    def test_temperature_ratio(self, results):
        c = get_case(results, "normal_shock_m4")
        # T2/T1 = 18.5 / (32/7) = 18.5*7/32 = 129.5/32 = 4.046875
        assert abs(c["T2_T1"] - 129.5 / 32.0) < 1e-3

    def test_total_pressure_ratio(self, results):
        c = get_case(results, "normal_shock_m4")
        # Known: ~ 0.1388
        assert abs(c["p02_p01"] - 0.1388) < 0.005


# =========================================================================
# Oblique Shock M=2.0, theta=10 deg
# =========================================================================

class TestObliqueShockM2:

    def test_shock_angle(self, results):
        c = get_case(results, "oblique_weak_m2_t10")
        # NACA 1135 / standard tables: beta ~ 39.31 deg
        assert abs(c["beta_deg"] - 39.31) < 0.25

    def test_downstream_mach(self, results):
        c = get_case(results, "oblique_weak_m2_t10")
        # Known: M2 ~ 1.6405
        assert abs(c["M2"] - 1.6405) < 0.02

    def test_theta_beta_m_consistency(self, results):
        """Plug beta back into theta-beta-M and verify theta=10 deg."""
        c = get_case(results, "oblique_weak_m2_t10")
        M, gamma = 2.0, 1.4
        beta = math.radians(c["beta_deg"])
        num = 2.0 * (math.cos(beta) / math.sin(beta)) * (M**2 * math.sin(beta)**2 - 1)
        den = M**2 * (gamma + math.cos(2 * beta)) + 2
        theta_back = math.degrees(math.atan(num / den))
        assert abs(theta_back - 10.0) < 0.15

    def test_weak_shock_high_p0(self, results):
        """Weak oblique shock at M=2, theta=10 should have p0 recovery > 0.95."""
        c = get_case(results, "oblique_weak_m2_t10")
        assert 0.95 < c["p02_p01"] < 1.0

    def test_ideal_gas_relation(self, results):
        """T ratio = p ratio / rho ratio for ideal gas."""
        c = get_case(results, "oblique_weak_m2_t10")
        expected_T = c["p2_p1"] / c["rho2_rho1"]
        assert abs(c["T2_T1"] - expected_T) / expected_T < 1e-4

    def test_pressure_from_normal_component(self, results):
        """Verify p2/p1 using M1n = M1*sin(beta)."""
        c = get_case(results, "oblique_weak_m2_t10")
        M1n = 2.0 * math.sin(math.radians(c["beta_deg"]))
        expected_p = 1 + 2 * 1.4 / 2.4 * (M1n**2 - 1)
        assert abs(c["p2_p1"] - expected_p) / expected_p < 0.005


# =========================================================================
# Oblique Shock M=3.0, theta=20 deg
# =========================================================================

class TestObliqueShockM3:

    def test_shock_angle(self, results):
        c = get_case(results, "oblique_weak_m3_t20")
        # Standard tables: beta ~ 37.76 deg
        assert abs(c["beta_deg"] - 37.76) < 0.3

    def test_downstream_supersonic(self, results):
        c = get_case(results, "oblique_weak_m3_t20")
        assert c["M2"] > 1.0

    def test_pressure_from_normal_component(self, results):
        c = get_case(results, "oblique_weak_m3_t20")
        M1n = 3.0 * math.sin(math.radians(c["beta_deg"]))
        expected_p = 1 + 2 * 1.4 / 2.4 * (M1n**2 - 1)
        assert abs(c["p2_p1"] - expected_p) / expected_p < 0.005

    def test_theta_beta_m_consistency(self, results):
        c = get_case(results, "oblique_weak_m3_t20")
        M, gamma = 3.0, 1.4
        beta = math.radians(c["beta_deg"])
        num = 2.0 * (math.cos(beta) / math.sin(beta)) * (M**2 * math.sin(beta)**2 - 1)
        den = M**2 * (gamma + math.cos(2 * beta)) + 2
        theta_back = math.degrees(math.atan(num / den))
        assert abs(theta_back - 20.0) < 0.15


# =========================================================================
# Maximum Deflection Angle
# =========================================================================

class TestMaxDeflection:

    def test_max_deflection_m2(self, results):
        c = get_case(results, "max_deflection_m2")
        # theta_max ~ 22.97 deg for M=2.0, gamma=1.4
        assert abs(c["theta_max_deg"] - 22.97) < 0.5

    def test_max_deflection_m3(self, results):
        c = get_case(results, "max_deflection_m3")
        # theta_max ~ 34.07 deg for M=3.0, gamma=1.4
        assert abs(c["theta_max_deg"] - 34.07) < 0.5

    def test_increases_with_mach(self, results):
        c2 = get_case(results, "max_deflection_m2")
        c3 = get_case(results, "max_deflection_m3")
        assert c3["theta_max_deg"] > c2["theta_max_deg"]


# =========================================================================
# Multi-Ramp Inlet (3 ramps: 10, 8, 6 deg at M=4.0)
# =========================================================================

class TestMultiRamp:

    def test_three_shocks_present(self, results):
        c = get_case(results, "three_ramp_inlet")
        assert "shocks" in c
        assert len(c["shocks"]) == 3

    def test_first_shock_m1(self, results):
        c = get_case(results, "three_ramp_inlet")
        assert abs(c["shocks"][0]["M1"] - 4.0) < 1e-6

    def test_sequential_mach_consistency(self, results):
        """M2 of shock i must equal M1 of shock i+1."""
        c = get_case(results, "three_ramp_inlet")
        for i in range(len(c["shocks"]) - 1):
            assert abs(c["shocks"][i]["M2"] - c["shocks"][i + 1]["M1"]) < 1e-6

    def test_mach_decreases(self, results):
        c = get_case(results, "three_ramp_inlet")
        machs = [c["shocks"][0]["M1"]] + [s["M2"] for s in c["shocks"]]
        for i in range(len(machs) - 1):
            assert machs[i] > machs[i + 1], f"Mach must decrease: {machs}"

    def test_total_pressure_product(self, results):
        """total_p0_recovery equals product of individual p02/p01."""
        c = get_case(results, "three_ramp_inlet")
        product = 1.0
        for s in c["shocks"]:
            product *= s["p02_p01"]
        assert abs(c["total_p0_recovery"] - product) < 1e-6

    def test_total_pressure_less_than_one(self, results):
        c = get_case(results, "three_ramp_inlet")
        assert 0 < c["total_p0_recovery"] < 1

    def test_better_than_normal_shock(self, results):
        """Multi-ramp must give better p0 recovery than single normal shock at same M."""
        c_ramp = get_case(results, "three_ramp_inlet")
        c_normal = get_case(results, "normal_shock_m4")
        assert c_ramp["total_p0_recovery"] > c_normal["p02_p01"]

    def test_final_mach_supersonic(self, results):
        c = get_case(results, "three_ramp_inlet")
        assert c["shocks"][-1]["M2"] > 1.0

    def test_each_shock_properties_consistent(self, results):
        """T ratio = p ratio / rho ratio for each shock."""
        c = get_case(results, "three_ramp_inlet")
        for i, s in enumerate(c["shocks"]):
            expected_T = s["p2_p1"] / s["rho2_rho1"]
            assert abs(s["T2_T1"] - expected_T) / expected_T < 1e-4, f"Shock {i}"


# =========================================================================
# Optimization (3 equal ramps at M=4.0)
# =========================================================================

class TestOptimization:

    def test_optimal_angle_range(self, results):
        c = get_case(results, "optimal_three_ramp")
        # For M=4.0 with 3 equal ramps, optimal ~ 12-15 deg per ramp
        assert 9.0 < c["optimal_theta_deg"] < 18.0

    def test_recovery_reasonable(self, results):
        c = get_case(results, "optimal_three_ramp")
        # Optimized 3-ramp at M=4 should yield 0.40 < p0_recovery < 0.85
        assert 0.40 < c["total_p0_recovery"] < 0.85

    def test_recovery_better_than_normal(self, results):
        c_opt = get_case(results, "optimal_three_ramp")
        c_normal = get_case(results, "normal_shock_m4")
        assert c_opt["total_p0_recovery"] > c_normal["p02_p01"]

    def test_final_mach_supersonic(self, results):
        c = get_case(results, "optimal_three_ramp")
        assert c["final_M"] > 1.0

    def test_has_required_fields(self, results):
        c = get_case(results, "optimal_three_ramp")
        for key in ["optimal_theta_deg", "total_p0_recovery", "final_M"]:
            assert key in c, f"Missing field: {key}"


# =========================================================================
# Thermally Perfect Gas (M=8.0, theta=15 deg)
# =========================================================================

class TestTPG:

    def test_required_fields(self, results):
        c = get_case(results, "tpg_high_mach")
        for key in ["beta_deg", "M2", "T2_K", "p2_Pa", "rho2_rho1", "p02_p01"]:
            assert key in c, f"Missing field: {key}"

    def test_shock_angle_range(self, results):
        c = get_case(results, "tpg_high_mach")
        mu = math.degrees(math.asin(1.0 / 8.0))  # ~7.18 deg
        assert mu < c["beta_deg"] < 90.0
        # Weak shock for M=8, theta=15: beta should be 20-30 deg
        assert 18.0 < c["beta_deg"] < 35.0

    def test_downstream_supersonic(self, results):
        c = get_case(results, "tpg_high_mach")
        assert c["M2"] > 1.0
        assert c["M2"] < 8.0

    def test_temperature_increase(self, results):
        c = get_case(results, "tpg_high_mach")
        assert c["T2_K"] > 220.0  # Must be hotter than upstream
        assert c["T2_K"] < 5000.0  # Sanity bound

    def test_pressure_increase(self, results):
        c = get_case(results, "tpg_high_mach")
        assert c["p2_Pa"] > 1166.0

    def test_density_increase(self, results):
        c = get_case(results, "tpg_high_mach")
        assert c["rho2_rho1"] > 1.0

    def test_total_pressure_loss(self, results):
        c = get_case(results, "tpg_high_mach")
        assert 0 < c["p02_p01"] < 1.0

    def test_state_equation_consistency(self, results):
        """Check rho2/rho1 is consistent with p2, T2 via p=rho*R*T."""
        c = get_case(results, "tpg_high_mach")
        T1, p1, R_gas = 220.0, 1166.0, 287.05
        rho1 = p1 / (R_gas * T1)
        rho2_from_state = c["p2_Pa"] / (R_gas * c["T2_K"])
        rho_ratio_from_state = rho2_from_state / rho1
        assert abs(c["rho2_rho1"] - rho_ratio_from_state) / rho_ratio_from_state < 0.01

    def test_energy_conservation(self, results):
        """Verify h1 + V1n^2/2 = h2 + V2n^2/2 (adiabatic shock)."""
        c = get_case(results, "tpg_high_mach")
        T1, p1, R_gas = 220.0, 1166.0, 287.05
        cp_coeffs = [979.0, 0.12, 4.5e-5, -1.2e-8]
        M1 = 8.0

        def h_poly(T):
            return sum(cp_coeffs[i] * T ** (i + 1) / (i + 1) for i in range(4))

        # Upstream speed of sound and velocity
        cp1 = sum(cp_coeffs[i] * T1 ** i for i in range(4))
        gamma1 = cp1 / (cp1 - R_gas)
        a1 = math.sqrt(gamma1 * R_gas * T1)
        V1 = M1 * a1
        beta_rad = math.radians(c["beta_deg"])
        V1n = V1 * math.sin(beta_rad)

        h1 = h_poly(T1)

        # Downstream
        T2 = c["T2_K"]
        rho1_val = p1 / (R_gas * T1)
        rho2 = rho1_val * c["rho2_rho1"]
        V2n = rho1_val * V1n / rho2  # mass conservation
        h2 = h_poly(T2)

        total_h1 = h1 + V1n ** 2 / 2.0
        total_h2 = h2 + V2n ** 2 / 2.0

        rel_error = abs(total_h1 - total_h2) / abs(total_h1)
        assert rel_error < 0.01, (
            f"Energy not conserved: total_h1={total_h1:.1f}, total_h2={total_h2:.1f}, "
            f"rel_error={rel_error:.4f}"
        )

    def test_momentum_conservation(self, results):
        """Verify p1 + rho1*V1n^2 = p2 + rho2*V2n^2."""
        c = get_case(results, "tpg_high_mach")
        T1, p1, R_gas = 220.0, 1166.0, 287.05
        cp_coeffs = [979.0, 0.12, 4.5e-5, -1.2e-8]
        M1 = 8.0

        cp1 = sum(cp_coeffs[i] * T1 ** i for i in range(4))
        gamma1 = cp1 / (cp1 - R_gas)
        a1 = math.sqrt(gamma1 * R_gas * T1)
        V1 = M1 * a1
        beta_rad = math.radians(c["beta_deg"])
        V1n = V1 * math.sin(beta_rad)
        rho1 = p1 / (R_gas * T1)

        mom1 = p1 + rho1 * V1n ** 2

        rho2 = rho1 * c["rho2_rho1"]
        V2n = rho1 * V1n / rho2
        p2 = c["p2_Pa"]
        mom2 = p2 + rho2 * V2n ** 2

        rel_error = abs(mom1 - mom2) / abs(mom1)
        assert rel_error < 0.01, (
            f"Momentum not conserved: mom1={mom1:.1f}, mom2={mom2:.1f}, "
            f"rel_error={rel_error:.4f}"
        )
