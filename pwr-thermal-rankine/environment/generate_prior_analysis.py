#!/usr/bin/env python3

"""
Build-time script to generate the prior analysis with embedded engineering errors.
This file is removed after execution during Docker build.
"""

import json
import math
import tomllib
from iapws import IAPWS97


def main():
    with open("/app/plant_specs.toml", "rb") as f:
        config = tomllib.load(f)

    core = config["core"]
    cycle = config["rankine_cycle"]

    # ---- Subchannel Geometry (CORRECT) ----
    D = core["fuel_pin_od_in"]
    PD = core["pitch_to_diameter_ratio"]
    P = PD * D
    A = P ** 2 - math.pi * D ** 2 / 4
    pw = math.pi * D
    Dh = 4 * A / pw

    # ---- Coolant Properties via IAPWS-97 (CORRECT) ----
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

    # ---- ERROR 1: Darcy coefficient labeled as Fanning ----
    # Uses 0.316*Re^(-0.25) which yields Darcy, but labels it "fanning"
    f_labeled_fanning = 0.316 * Re ** (-0.25)
    f_labeled_darcy = 4 * f_labeled_fanning

    gc = 32.174
    rho_lbft3 = rho * 0.062428
    Dh_ft = Dh / 12
    dP_lbf_ft2 = (4 * f_labeled_fanning * (L_ft / Dh_ft)
                  * (rho_lbft3 * V_fps ** 2) / (2 * gc))
    dP_psi = dP_lbf_ft2 / 144

    # ---- ERROR 2: Nusselt coefficient 0.028 instead of 0.023 ----
    Nu_err = 0.028 * Re ** 0.8 * Pr_val ** 0.4
    h_err = Nu_err * k_th / Dh_m

    # ---- Rankine Cycle (ERROR 3 in LP turbine stage) ----
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

    # ERROR 3: LP treated as isentropic — uses h3s directly instead of
    # h3 = h2 - eta_t*(h2-h3s)
    st3s = IAPWS97(P=P_cond_MPa, s=s2)
    h3s = st3s.h
    h3_err = h3s  # Missing isentropic efficiency application

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

    w_t = (h1 - h2) + (1 - y) * (h2 - h3_err)
    w_p = (1 - y) * (h5 - h4) + (h7 - h6)
    w_net = w_t - w_p
    q_in = h1 - h7
    eta_cycle = w_net / q_in
    hr = 3412.14 / eta_cycle

    results = {
        "subchannel_hydraulic_diameter_in": round(Dh, 6),
        "subchannel_flow_area_in2": round(A, 6),
        "reynolds_number": round(Re, 1),
        "fanning_friction_factor": round(f_labeled_fanning, 7),
        "darcy_friction_factor": round(f_labeled_darcy, 7),
        "frictional_pressure_drop_psi": round(dP_psi, 4),
        "nusselt_number": round(Nu_err, 2),
        "heat_transfer_coefficient_W_m2K": round(h_err, 1),
        "extraction_mass_fraction": round(y, 6),
        "cycle_thermal_efficiency": round(eta_cycle, 6),
        "cycle_heat_rate_btu_kwh": round(hr, 2),
        "methodology_notes": {
            "friction": "Smooth-tube Blasius correlation for Fanning friction factor",
            "heat_transfer": "Winterton (1998) turbulent forced-convection correlation",
            "rankine": "State-point analysis with isentropic expansion paths and real pumps"
        }
    }

    with open("/app/prior_analysis.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
