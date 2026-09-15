#!/usr/bin/env python3

"""
Correct PWR thermal-hydraulic analysis and power uprate assessment.

Independently computes all values, compares against the prior analysis
to identify errors, and determines maximum safe power uprate.
"""

import json
import math
import tomllib
from iapws import IAPWS97


def compute_primary_side(core):
    """Subchannel thermal-hydraulic analysis with correct correlations."""
    D_in = core["fuel_pin_od_in"]
    PD = core["pitch_to_diameter_ratio"]
    P_in = PD * D_in
    L_ft = core["active_fuel_length_ft"]
    V_fps = core["avg_coolant_velocity_fps"]

    # Central subchannel geometry (square lattice)
    A_in2 = P_in ** 2 - math.pi * D_in ** 2 / 4
    pw_in = math.pi * D_in
    Dh_in = 4 * A_in2 / pw_in

    # Coolant properties at average conditions via IAPWS-97
    P_sys_MPa = core["system_pressure_psia"] * 0.00689476
    T_avg_K = (core["avg_coolant_temp_F"] - 32) * 5 / 9 + 273.15

    coolant = IAPWS97(P=P_sys_MPa, T=T_avg_K)
    rho = coolant.rho
    mu = coolant.mu
    k_th = coolant.k
    Pr = coolant.Prandt

    Dh_m = Dh_in * 0.0254
    V_ms = V_fps * 0.3048
    Re = rho * V_ms * Dh_m / mu

    # Blasius: Fanning friction factor
    f_fanning = 0.0791 * Re ** (-0.25)
    f_darcy = 4.0 * f_fanning

    # Fanning equation for frictional pressure drop (Imperial)
    gc = 32.174
    rho_lbft3 = rho * 0.062428
    Dh_ft = Dh_in / 12.0

    dP_lbf_ft2 = (4.0 * f_fanning * (L_ft / Dh_ft)
                  * (rho_lbft3 * V_fps ** 2) / (2.0 * gc))
    dP_psi = dP_lbf_ft2 / 144.0

    # Dittus-Boelter for heating (coefficient 0.023, Pr exponent 0.4)
    Nu = 0.023 * Re ** 0.8 * Pr ** 0.4
    h_conv = Nu * k_th / Dh_m

    return {
        "subchannel_hydraulic_diameter_in": Dh_in,
        "subchannel_flow_area_in2": A_in2,
        "reynolds_number": Re,
        "fanning_friction_factor": f_fanning,
        "darcy_friction_factor": f_darcy,
        "frictional_pressure_drop_psi": dP_psi,
        "nusselt_number": Nu,
        "heat_transfer_coefficient_W_m2K": h_conv,
    }


def compute_rankine_cycle(cycle):
    """Regenerative Rankine cycle with one open feedwater heater."""
    P1_MPa = cycle["turbine_inlet_pressure_psia"] * 0.00689476
    T1_K = (cycle["turbine_inlet_temp_F"] - 32) * 5 / 9 + 273.15
    P_ext_MPa = cycle["extraction_pressure_psia"] * 0.00689476
    P_cond_MPa = cycle["condenser_pressure_psia"] * 0.00689476
    eta_t = cycle["turbine_isentropic_efficiency"]
    eta_cp = cycle["condensate_pump_isentropic_efficiency"]
    eta_fp = cycle["feedwater_pump_isentropic_efficiency"]

    # State 1: Turbine inlet (superheated)
    st1 = IAPWS97(P=P1_MPa, T=T1_K)
    h1, s1 = st1.h, st1.s

    # State 2: HP turbine exhaust at extraction pressure
    st2s = IAPWS97(P=P_ext_MPa, s=s1)
    h2s = st2s.h
    h2 = h1 - eta_t * (h1 - h2s)

    # Actual entropy at state 2 for LP expansion
    st2 = IAPWS97(P=P_ext_MPa, h=h2)
    s2 = st2.s

    # State 3: LP turbine exhaust at condenser pressure
    st3s = IAPWS97(P=P_cond_MPa, s=s2)
    h3s = st3s.h
    h3 = h2 - eta_t * (h2 - h3s)

    # State 4: Condenser outlet (saturated liquid)
    st4 = IAPWS97(P=P_cond_MPa, x=0)
    h4, s4 = st4.h, st4.s

    # State 5: Condensate pump outlet (to extraction pressure)
    st5s = IAPWS97(P=P_ext_MPa, s=s4)
    h5s = st5s.h
    h5 = h4 + (h5s - h4) / eta_cp

    # State 6: OFW heater outlet (saturated liquid at extraction pressure)
    st6 = IAPWS97(P=P_ext_MPa, x=0)
    h6, s6 = st6.h, st6.s

    # State 7: Feedwater pump outlet (to boiler pressure)
    st7s = IAPWS97(P=P1_MPa, s=s6)
    h7s = st7s.h
    h7 = h6 + (h7s - h6) / eta_fp

    # Extraction fraction from OFW energy balance
    y = (h6 - h5) / (h2 - h5)

    # Cycle performance
    w_t = (h1 - h2) + (1.0 - y) * (h2 - h3)
    w_p = (1.0 - y) * (h5 - h4) + (h7 - h6)
    w_net = w_t - w_p
    q_in = h1 - h7
    eta_cycle = w_net / q_in
    heat_rate = 3412.14 / eta_cycle

    return {
        "extraction_mass_fraction": y,
        "cycle_thermal_efficiency": eta_cycle,
        "cycle_heat_rate_btu_kwh": heat_rate,
    }


def compute_uprate(core, limits, h_conv):
    """Determine maximum safe power uprate from cladding temperature limit."""
    D_m = core["fuel_pin_od_in"] * 0.0254
    T_avg_K = (core["avg_coolant_temp_F"] - 32) * 5 / 9 + 273.15
    T_clad_max_K = (limits["max_cladding_outer_wall_temp_F"] - 32) * 5 / 9 + 273.15

    rated_q_prime_kw_ft = core["rated_linear_heat_rate_kw_per_ft"]
    rated_q_prime_W_m = rated_q_prime_kw_ft * 1000.0 / 0.3048

    delta_T_max_K = T_clad_max_K - T_avg_K
    max_q_pp = h_conv * delta_T_max_K
    max_q_prime_W_m = max_q_pp * math.pi * D_m
    max_q_prime_kw_ft = max_q_prime_W_m * 0.3048 / 1000.0

    return (max_q_prime_kw_ft / rated_q_prime_kw_ft - 1) * 100.0


def count_errors(correct, prior, threshold=0.05):
    """Count root-cause errors by grouping causally related fields."""
    error_groups = [
        ["fanning_friction_factor", "darcy_friction_factor",
         "frictional_pressure_drop_psi"],
        ["nusselt_number", "heat_transfer_coefficient_W_m2K"],
        ["cycle_thermal_efficiency", "cycle_heat_rate_btu_kwh"],
        ["extraction_mass_fraction"],
        ["subchannel_hydraulic_diameter_in", "subchannel_flow_area_in2"],
        ["reynolds_number"],
    ]

    n_errors = 0
    for group in error_groups:
        group_has_error = False
        for field in group:
            if field in prior and field in correct:
                rel_diff = abs(correct[field] - prior[field]) / abs(correct[field])
                if rel_diff > threshold:
                    group_has_error = True
                    break
        if group_has_error:
            n_errors += 1
    return n_errors


def main():
    with open("/app/plant_specs.toml", "rb") as f:
        config = tomllib.load(f)

    with open("/app/prior_analysis.json") as f:
        prior = json.load(f)

    results = {}
    primary = compute_primary_side(config["core"])
    results.update(primary)
    results.update(compute_rankine_cycle(config["rankine_cycle"]))

    h_conv = primary["heat_transfer_coefficient_W_m2K"]
    results["max_uprate_percentage"] = compute_uprate(
        config["core"], config["thermal_limits"], h_conv
    )

    results["num_errors_found"] = count_errors(results, prior)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json:")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
