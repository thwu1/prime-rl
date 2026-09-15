
"""
Verification tests for PWR thermal-hydraulic analysis review task.
Independently computes all correct values using iapws (IAPWS-97) and
verifies the agent's /app/results.json.
"""

import json
import math
import pytest
import tomllib
from iapws import IAPWS97


@pytest.fixture(scope="module")
def config():
    with open("/app/plant_specs.toml", "rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="module")
def prior():
    with open("/app/prior_analysis.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected(config):
    """Independently compute all correct values."""
    core = config["core"]
    cycle = config["rankine_cycle"]
    limits = config["thermal_limits"]

    # ---- Subchannel Geometry ----
    D = core["fuel_pin_od_in"]
    PD = core["pitch_to_diameter_ratio"]
    P = PD * D
    A = P ** 2 - math.pi * D ** 2 / 4
    pw = math.pi * D
    Dh = 4 * A / pw

    # ---- Coolant Properties via IAPWS-97 ----
    P_sys_MPa = core["system_pressure_psia"] * 0.00689476
    T_avg_K = (core["avg_coolant_temp_F"] - 32) * 5 / 9 + 273.15
    V_fps = core["avg_coolant_velocity_fps"]
    L_ft = core["active_fuel_length_ft"]

    coolant = IAPWS97(P=P_sys_MPa, T=T_avg_K)
    rho = coolant.rho
    mu = coolant.mu
    k_th = coolant.k
    Pr_val = coolant.Prandt

    Dh_m = Dh * 0.0254
    V_ms = V_fps * 0.3048
    Re = rho * V_ms * Dh_m / mu

    # Blasius Fanning friction factor
    f_fan = 0.0791 * Re ** (-0.25)
    f_dar = 4 * f_fan

    # Fanning equation for pressure drop (Imperial units)
    gc = 32.174
    rho_lbft3 = rho * 0.062428
    Dh_ft = Dh / 12
    dP_lbf_ft2 = (4 * f_fan * (L_ft / Dh_ft)
                  * (rho_lbft3 * V_fps ** 2) / (2 * gc))
    dP_psi = dP_lbf_ft2 / 144

    # Dittus-Boelter (heating: Pr^0.4)
    Nu = 0.023 * Re ** 0.8 * Pr_val ** 0.4
    h_conv = Nu * k_th / Dh_m

    # ---- Rankine Cycle ----
    P1_MPa = cycle["turbine_inlet_pressure_psia"] * 0.00689476
    T1_K = (cycle["turbine_inlet_temp_F"] - 32) * 5 / 9 + 273.15
    P_ext_MPa = cycle["extraction_pressure_psia"] * 0.00689476
    P_cond_MPa = cycle["condenser_pressure_psia"] * 0.00689476
    eta_t = cycle["turbine_isentropic_efficiency"]
    eta_cp = cycle["condensate_pump_isentropic_efficiency"]
    eta_fp = cycle["feedwater_pump_isentropic_efficiency"]

    st1 = IAPWS97(P=P1_MPa, T=T1_K)
    h1, s1 = st1.h, st1.s

    st2s = IAPWS97(P=P_ext_MPa, s=s1)
    h2s = st2s.h
    h2 = h1 - eta_t * (h1 - h2s)

    st2 = IAPWS97(P=P_ext_MPa, h=h2)
    s2 = st2.s

    st3s = IAPWS97(P=P_cond_MPa, s=s2)
    h3s = st3s.h
    h3 = h2 - eta_t * (h2 - h3s)

    st4 = IAPWS97(P=P_cond_MPa, x=0)
    h4, s4 = st4.h, st4.s

    st5s = IAPWS97(P=P_ext_MPa, s=s4)
    h5s = st5s.h
    h5 = h4 + (h5s - h4) / eta_cp

    st6 = IAPWS97(P=P_ext_MPa, x=0)
    h6, s6 = st6.h, st6.s

    st7s = IAPWS97(P=P1_MPa, s=s6)
    h7s = st7s.h
    h7 = h6 + (h7s - h6) / eta_fp

    y = (h6 - h5) / (h2 - h5)

    w_t = (h1 - h2) + (1 - y) * (h2 - h3)
    w_p = (1 - y) * (h5 - h4) + (h7 - h6)
    w_net = w_t - w_p
    q_in = h1 - h7
    eta_cycle = w_net / q_in
    heat_rate = 3412.14 / eta_cycle

    # ---- Maximum power uprate ----
    D_m = D * 0.0254
    rated_q_prime_kw_ft = core["rated_linear_heat_rate_kw_per_ft"]
    rated_q_prime_W_m = rated_q_prime_kw_ft * 1000.0 / 0.3048

    T_clad_max_K = (limits["max_cladding_outer_wall_temp_F"] - 32) * 5 / 9 + 273.15
    delta_T_max_K = T_clad_max_K - T_avg_K

    max_q_pp = h_conv * delta_T_max_K
    max_q_prime_W_m = max_q_pp * math.pi * D_m
    max_q_prime_kw_ft = max_q_prime_W_m * 0.3048 / 1000.0
    max_uprate_pct = (max_q_prime_kw_ft / rated_q_prime_kw_ft - 1) * 100.0

    return {
        "subchannel_hydraulic_diameter_in": Dh,
        "subchannel_flow_area_in2": A,
        "reynolds_number": Re,
        "fanning_friction_factor": f_fan,
        "darcy_friction_factor": f_dar,
        "frictional_pressure_drop_psi": dP_psi,
        "nusselt_number": Nu,
        "heat_transfer_coefficient_W_m2K": h_conv,
        "extraction_mass_fraction": y,
        "cycle_thermal_efficiency": eta_cycle,
        "cycle_heat_rate_btu_kwh": heat_rate,
        "max_uprate_percentage": max_uprate_pct,
    }


def _reltol(actual, expected_val, tol):
    """Assert relative tolerance."""
    assert abs(actual - expected_val) / abs(expected_val) < tol, (
        f"got {actual}, expected {expected_val} (tol={tol})"
    )


# ---- Subchannel Geometry ----

class TestSubchannelGeometry:
    def test_hydraulic_diameter(self, results, expected):
        _reltol(results["subchannel_hydraulic_diameter_in"],
                expected["subchannel_hydraulic_diameter_in"], 0.005)

    def test_flow_area(self, results, expected):
        _reltol(results["subchannel_flow_area_in2"],
                expected["subchannel_flow_area_in2"], 0.005)


# ---- Flow Analysis (agent must fix friction factor error) ----

class TestFlowAnalysis:
    def test_reynolds_number(self, results, expected):
        _reltol(results["reynolds_number"],
                expected["reynolds_number"], 0.02)

    def test_fanning_friction_factor(self, results, expected):
        _reltol(results["fanning_friction_factor"],
                expected["fanning_friction_factor"], 0.02)

    def test_darcy_friction_factor(self, results, expected):
        _reltol(results["darcy_friction_factor"],
                expected["darcy_friction_factor"], 0.02)

    def test_frictional_pressure_drop(self, results, expected):
        _reltol(results["frictional_pressure_drop_psi"],
                expected["frictional_pressure_drop_psi"], 0.02)


# ---- Heat Transfer (agent must fix Nusselt coefficient error) ----

class TestHeatTransfer:
    def test_nusselt_number(self, results, expected):
        _reltol(results["nusselt_number"],
                expected["nusselt_number"], 0.02)

    def test_heat_transfer_coefficient(self, results, expected):
        _reltol(results["heat_transfer_coefficient_W_m2K"],
                expected["heat_transfer_coefficient_W_m2K"], 0.02)


# ---- Rankine Cycle (agent must fix LP turbine efficiency error) ----

class TestRankineCycle:
    def test_extraction_fraction(self, results, expected):
        _reltol(results["extraction_mass_fraction"],
                expected["extraction_mass_fraction"], 0.02)

    def test_cycle_efficiency(self, results, expected):
        _reltol(results["cycle_thermal_efficiency"],
                expected["cycle_thermal_efficiency"], 0.02)

    def test_heat_rate(self, results, expected):
        _reltol(results["cycle_heat_rate_btu_kwh"],
                expected["cycle_heat_rate_btu_kwh"], 0.02)


# ---- Uprate Assessment ----

class TestUprate:
    def test_max_uprate_percentage(self, results, expected):
        _reltol(results["max_uprate_percentage"],
                expected["max_uprate_percentage"], 0.05)


# ---- Error Count ----

class TestErrorDetection:
    def test_num_errors_found(self, results):
        n = results["num_errors_found"]
        assert 2 <= n <= 4, (
            f"Expected 3 root-cause errors (tolerance: 2-4), got {n}"
        )


# ---- Consistency Checks ----

class TestConsistency:
    def test_darcy_is_4x_fanning(self, results):
        ratio = results["darcy_friction_factor"] / results["fanning_friction_factor"]
        assert abs(ratio - 4.0) < 0.01, (
            f"Darcy should be 4x Fanning, got ratio {ratio}"
        )

    def test_heat_rate_consistency(self, results):
        expected_hr = 3412.14 / results["cycle_thermal_efficiency"]
        _reltol(results["cycle_heat_rate_btu_kwh"], expected_hr, 0.001)

    def test_efficiency_in_range(self, results):
        eta = results["cycle_thermal_efficiency"]
        assert 0.20 < eta < 0.45, f"Efficiency {eta} outside physical range"

    def test_extraction_in_range(self, results):
        y = results["extraction_mass_fraction"]
        assert 0.05 < y < 0.40, f"Extraction fraction {y} outside physical range"

    def test_reynolds_turbulent(self, results):
        Re = results["reynolds_number"]
        assert Re > 10000, f"Re = {Re}, expected turbulent flow"

    def test_uprate_positive(self, results):
        pct = results["max_uprate_percentage"]
        assert pct > 0, f"Max uprate should be positive, got {pct}"

    def test_corrected_differs_from_prior(self, results, prior):
        """Verify the agent did NOT just copy the prior analysis."""
        # At least friction factor or pressure drop should differ significantly
        if "fanning_friction_factor" in prior:
            prior_ff = prior["fanning_friction_factor"]
            corr_ff = results["fanning_friction_factor"]
            diff = abs(prior_ff - corr_ff) / abs(corr_ff)
            assert diff > 0.5, (
                f"Corrected fanning_friction_factor {corr_ff} too close to "
                f"prior {prior_ff} — agent may not have identified the error"
            )
