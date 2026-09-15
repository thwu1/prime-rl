#!/usr/bin/env python3
"""
Cascade refrigeration system optimizer with exergy and TEWI analysis.

Reads /app/config.json and writes /app/results.json.
"""


import json
import math
from CoolProp.CoolProp import PropsSI
from scipy.optimize import minimize_scalar


def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


def cascade_cycle_analysis(T_cascade_C, T_evap_C, T_cond_C, eta_s,
                           approach_K, Q_evap_kW, ltc_fluid, htc_fluid,
                           T_dead_C):
    """Full thermodynamic analysis of a cascade system at a given cascade temperature.

    Returns a dict with COP, work, mass flows, exergy destruction, etc.
    All internal calculations in SI (K, Pa, J/kg, J/(kg*K), W).
    Output in kW and kg/s.
    """
    T_evap = T_evap_C + 273.15
    T_cond = T_cond_C + 273.15
    T_cascade = T_cascade_C + 273.15
    T_evap_htc = T_cascade - approach_K
    T_0 = T_dead_C + 273.15
    Q_evap = Q_evap_kW * 1000.0  # W

    # ---- LTC state points ----
    # State 1: Sat vapor at T_evap (evaporator exit)
    h1 = PropsSI("H", "T", T_evap, "Q", 1, ltc_fluid)
    s1 = PropsSI("S", "T", T_evap, "Q", 1, ltc_fluid)

    # State 2: Compressor discharge (actual, non-isentropic)
    P_cond_ltc = PropsSI("P", "T", T_cascade, "Q", 0, ltc_fluid)
    h2s = PropsSI("H", "P", P_cond_ltc, "S", s1, ltc_fluid)
    h2 = h1 + (h2s - h1) / eta_s
    s2 = PropsSI("S", "H", h2, "P", P_cond_ltc, ltc_fluid)

    # State 3: Sat liquid at T_cascade (cascade HX exit, LTC side)
    h3 = PropsSI("H", "T", T_cascade, "Q", 0, ltc_fluid)
    s3 = PropsSI("S", "T", T_cascade, "Q", 0, ltc_fluid)

    # State 4: After expansion valve (isenthalpic)
    h4 = h3
    P_evap_ltc = PropsSI("P", "T", T_evap, "Q", 0, ltc_fluid)
    s4 = PropsSI("S", "H", h4, "P", P_evap_ltc, ltc_fluid)

    # ---- HTC state points ----
    # State 5: Sat vapor at T_evap_htc (cascade HX exit, HTC side)
    h5 = PropsSI("H", "T", T_evap_htc, "Q", 1, htc_fluid)
    s5 = PropsSI("S", "T", T_evap_htc, "Q", 1, htc_fluid)

    # State 6: Compressor discharge (actual)
    P_cond_htc = PropsSI("P", "T", T_cond, "Q", 0, htc_fluid)
    h6s = PropsSI("H", "P", P_cond_htc, "S", s5, htc_fluid)
    h6 = h5 + (h6s - h5) / eta_s
    s6 = PropsSI("S", "H", h6, "P", P_cond_htc, htc_fluid)

    # State 7: Sat liquid at T_cond (condenser exit)
    h7 = PropsSI("H", "T", T_cond, "Q", 0, htc_fluid)
    s7 = PropsSI("S", "T", T_cond, "Q", 0, htc_fluid)

    # State 8: After expansion valve (isenthalpic)
    h8 = h7
    P_evap_htc = PropsSI("P", "T", T_evap_htc, "Q", 0, htc_fluid)
    s8 = PropsSI("S", "H", h8, "P", P_evap_htc, htc_fluid)

    # ---- Mass flow rates ----
    m_dot_ltc = Q_evap / (h1 - h4)
    W_ltc = m_dot_ltc * (h2 - h1)  # W
    Q_cascade = m_dot_ltc * (h2 - h3)  # W

    m_dot_htc = Q_cascade / (h5 - h8)
    W_htc = m_dot_htc * (h6 - h5)  # W
    W_total = W_ltc + W_htc

    # ---- COP ----
    COP = Q_evap / W_total
    COP_carnot = T_evap / (T_cond - T_evap)
    eta_II = COP / COP_carnot

    # ---- Exergy destruction (all in W) ----
    # Compressors (adiabatic): Ed = T_0 * m_dot * (s_out - s_in)
    Ed_comp_ltc = T_0 * m_dot_ltc * (s2 - s1)
    Ed_comp_htc = T_0 * m_dot_htc * (s6 - s5)

    # Expansion valves (adiabatic, isenthalpic): Ed = T_0 * m_dot * (s_out - s_in)
    Ed_exp_ltc = T_0 * m_dot_ltc * (s4 - s3)
    Ed_exp_htc = T_0 * m_dot_htc * (s8 - s7)

    # Condenser: rejects heat Q_cond to environment at T_0
    Q_cond = m_dot_htc * (h6 - h7)
    Ed_cond = T_0 * m_dot_htc * (s7 - s6) + Q_cond

    # Evaporator: absorbs heat Q_evap from cold space at T_evap
    # For ideal model (cold space at T_evap = refrigerant T), Ed_evap ≈ 0
    # But we compute it properly:
    Ed_evap = T_0 * m_dot_ltc * (s1 - s4) - Q_evap * T_0 / T_evap + Q_evap
    # Simplify: Ed_evap = T_0 * [m_dot_ltc*(s1 - s4) - Q_evap/T_evap]
    # For constant-T phase change, h1-h4 = T_evap*(s1-s4) approximately, so Ed_evap ≈ 0
    # Recompute more carefully:
    Ed_evap = T_0 * (m_dot_ltc * (s1 - s4) - Q_evap / T_evap)

    # Cascade HX: adiabatic, two-stream
    Ed_cascade = T_0 * (m_dot_ltc * (s3 - s2) + m_dot_htc * (s5 - s8))

    Ed_total = Ed_comp_ltc + Ed_comp_htc + Ed_exp_ltc + Ed_exp_htc + Ed_cond + Ed_evap + Ed_cascade

    # Exergetic efficiency
    product_exergy = Q_evap * (T_0 / T_evap - 1.0)
    exergetic_eff = product_exergy / W_total

    return {
        "COP": COP,
        "carnot_COP": COP_carnot,
        "second_law_efficiency": eta_II,
        "W_total_kW": W_total / 1000.0,
        "W_ltc_kW": W_ltc / 1000.0,
        "W_htc_kW": W_htc / 1000.0,
        "m_dot_ltc_kg_s": m_dot_ltc,
        "m_dot_htc_kg_s": m_dot_htc,
        "exergy_destruction": {
            "compressor_ltc_kW": Ed_comp_ltc / 1000.0,
            "compressor_htc_kW": Ed_comp_htc / 1000.0,
            "condenser_kW": Ed_cond / 1000.0,
            "evaporator_kW": Ed_evap / 1000.0,
            "expansion_valve_ltc_kW": Ed_exp_ltc / 1000.0,
            "expansion_valve_htc_kW": Ed_exp_htc / 1000.0,
            "cascade_hx_kW": Ed_cascade / 1000.0,
            "total_kW": Ed_total / 1000.0,
        },
        "exergetic_efficiency": exergetic_eff,
    }


def cop_objective(T_cascade_C, T_evap_C, T_cond_C, eta_s, approach_K,
                  Q_evap_kW, ltc_fluid, htc_fluid, T_dead_C):
    """Return negative COP (for minimization)."""
    try:
        result = cascade_cycle_analysis(
            T_cascade_C, T_evap_C, T_cond_C, eta_s, approach_K,
            Q_evap_kW, ltc_fluid, htc_fluid, T_dead_C
        )
        return -result["COP"]
    except Exception:
        return 1e6  # infeasible point


def get_feasible_range(T_evap_C, T_cond_C, approach_K, ltc_fluid, htc_fluid):
    """Determine feasible cascade temperature range respecting critical points."""
    # LTC critical temperature (cascade condenser temp must be below this)
    T_crit_ltc = PropsSI("Tcrit", "", 0, "", 0, ltc_fluid) - 273.15
    # HTC must evaporate at T_cascade - approach, so T_cascade - approach > T_evap_C
    # Also need T_cascade > T_evap_C (for LTC to have positive compression ratio)

    T_min = T_evap_C + 5.0  # at least 5°C above evaporator
    T_max = min(T_crit_ltc - 3.0, T_cond_C - approach_K - 2.0)

    return T_min, T_max


def compute_tewi(W_total_kW, config, pair):
    """Compute TEWI for a cascade system."""
    n = config["system_lifetime_years"]
    L = config["annual_leakage_rate"]
    alpha = config["recovery_efficiency"]
    beta = config["grid_carbon_intensity_kgCO2_per_kWh"]
    hours = config["annual_operating_hours"]

    gwp_ltc = pair["gwp_ltc"]
    gwp_htc = pair["gwp_htc"]
    m_ltc = pair["charge_ltc_kg"]
    m_htc = pair["charge_htc_kg"]

    total_gwp_charge = gwp_ltc * m_ltc + gwp_htc * m_htc

    # Direct emissions: leakage + end-of-life
    direct = total_gwp_charge * L * n + total_gwp_charge * (1 - alpha)

    # Indirect emissions: energy consumption
    E_annual = W_total_kW * hours  # kWh/year
    indirect = n * E_annual * beta

    return {
        "direct_kg_CO2": direct,
        "indirect_kg_CO2": indirect,
        "total_kg_CO2": direct + indirect,
    }


def main():
    config = load_config()

    T_evap_C = config["T_evap_C"]
    T_cond_C = config["T_cond_C"]
    Q_evap_kW = config["Q_evap_kW"]
    eta_s = config["eta_s"]
    approach_K = config["cascade_approach_K"]
    T_dead_C = config["T_dead_C"]

    configurations = []

    for pair in config["refrigerant_pairs"]:
        ltc_fluid = pair["ltc"]
        htc_fluid = pair["htc"]

        # Determine feasible range
        T_min, T_max = get_feasible_range(
            T_evap_C, T_cond_C, approach_K, ltc_fluid, htc_fluid
        )

        # Optimize cascade temperature
        result = minimize_scalar(
            cop_objective,
            bounds=(T_min, T_max),
            method="bounded",
            args=(T_evap_C, T_cond_C, eta_s, approach_K, Q_evap_kW,
                  ltc_fluid, htc_fluid, T_dead_C),
            options={"xatol": 0.01, "maxiter": 200},
        )

        T_opt = result.x

        # Full analysis at optimal point
        analysis = cascade_cycle_analysis(
            T_opt, T_evap_C, T_cond_C, eta_s, approach_K,
            Q_evap_kW, ltc_fluid, htc_fluid, T_dead_C
        )

        # TEWI
        tewi = compute_tewi(analysis["W_total_kW"], config, pair)

        cfg_result = {
            "ltc_fluid": ltc_fluid,
            "htc_fluid": htc_fluid,
            "optimal_cascade_T_C": round(T_opt, 2),
            **analysis,
            "TEWI": tewi,
        }
        configurations.append(cfg_result)

    # Identify minimum TEWI and maximum COP
    min_tewi_cfg = min(configurations, key=lambda c: c["TEWI"]["total_kg_CO2"])
    max_cop_cfg = max(configurations, key=lambda c: c["COP"])

    output = {
        "configurations": configurations,
        "minimum_TEWI_config": {
            "ltc_fluid": min_tewi_cfg["ltc_fluid"],
            "htc_fluid": min_tewi_cfg["htc_fluid"],
        },
        "maximum_COP_config": {
            "ltc_fluid": max_cop_cfg["ltc_fluid"],
            "htc_fluid": max_cop_cfg["htc_fluid"],
        },
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")
    print(f"Minimum TEWI: {min_tewi_cfg['ltc_fluid']}/{min_tewi_cfg['htc_fluid']} "
          f"({min_tewi_cfg['TEWI']['total_kg_CO2']:.0f} kg CO2)")
    print(f"Maximum COP: {max_cop_cfg['ltc_fluid']}/{max_cop_cfg['htc_fluid']} "
          f"({max_cop_cfg['COP']:.4f})")


if __name__ == "__main__":
    main()
