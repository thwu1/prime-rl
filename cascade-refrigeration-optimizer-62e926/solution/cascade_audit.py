#!/usr/bin/env python3
"""Cascade refrigeration facility performance audit.

Reads scattered data files from /app/data/ and writes comprehensive
audit results to /app/audit_results.json.
"""


import json
import csv
import os
from CoolProp.CoolProp import PropsSI
from scipy.optimize import minimize_scalar


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_csv_dicts(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_all_data():
    """Discover and load all data files from /app/data/."""
    systems = load_json("/app/data/systems.json")["systems"]
    conditions = load_json("/app/data/site/conditions.json")

    ambient_raw = load_csv_dicts("/app/data/site/ambient_profile.csv")
    ambient = [{"T_ambient_C": float(r["T_ambient_C"]),
                "hours": float(r["hours_per_year"])} for r in ambient_raw]

    environmental = load_json("/app/data/site/environmental.json")

    # Load compressor specs by model ID
    compressors = {}
    for sys in systems:
        for circuit in ["ltc", "htc"]:
            model = sys[circuit]["compressor_model"]
            if model not in compressors:
                path = f"/app/data/equipment/compressors/{model}.json"
                compressors[model] = load_json(path)

    # Load refrigerant inventory
    inventory = {}
    for row in load_csv_dicts("/app/data/refrigerant_inventory.csv"):
        sid = row["system_id"]
        if sid not in inventory:
            inventory[sid] = {}
        inventory[sid][row["circuit"]] = {
            "fluid": row["fluid"],
            "charge_kg": float(row["charge_kg"]),
            "gwp": float(row["gwp"])
        }

    return systems, conditions, ambient, environmental, compressors, inventory


def compressor_eta(spec, pressure_ratio):
    """Evaluate compressor isentropic efficiency from polynomial curve."""
    c = spec["efficiency_curve"]["coefficients"]
    PR = pressure_ratio
    eta = c[0] + c[1] * PR + c[2] * PR ** 2
    return max(0.1, min(0.95, eta))


def cascade_analysis(T_cascade_C, T_evap_C, T_cond_C, cascade_approach_K,
                     Q_evap_kW, ltc_fluid, htc_fluid, ltc_comp, htc_comp, T_dead_C):
    """Full thermodynamic analysis at a given cascade temperature.

    Returns dict with COP, work, mass flows, exergy destruction.
    All internal calculations in SI (K, Pa, J/kg, J/(kg*K), W).
    Output in kW and kg/s.
    """
    T_evap_K = T_evap_C + 273.15
    T_cond_K = T_cond_C + 273.15
    T_cascade_K = T_cascade_C + 273.15
    T_evap_htc_K = T_cascade_K - cascade_approach_K
    T_0 = T_dead_C + 273.15
    Q_evap_W = Q_evap_kW * 1000.0

    # LTC states 1-4
    h1 = PropsSI("H", "T", T_evap_K, "Q", 1, ltc_fluid)
    s1 = PropsSI("S", "T", T_evap_K, "Q", 1, ltc_fluid)
    P_evap_ltc = PropsSI("P", "T", T_evap_K, "Q", 0, ltc_fluid)
    P_cond_ltc = PropsSI("P", "T", T_cascade_K, "Q", 0, ltc_fluid)

    PR_ltc = P_cond_ltc / P_evap_ltc
    eta_ltc = compressor_eta(ltc_comp, PR_ltc)

    h2s = PropsSI("H", "P", P_cond_ltc, "S", s1, ltc_fluid)
    h2 = h1 + (h2s - h1) / eta_ltc
    s2 = PropsSI("S", "H", h2, "P", P_cond_ltc, ltc_fluid)

    h3 = PropsSI("H", "T", T_cascade_K, "Q", 0, ltc_fluid)
    s3 = PropsSI("S", "T", T_cascade_K, "Q", 0, ltc_fluid)
    h4 = h3  # isenthalpic expansion
    s4 = PropsSI("S", "H", h4, "P", P_evap_ltc, ltc_fluid)

    # HTC states 5-8
    h5 = PropsSI("H", "T", T_evap_htc_K, "Q", 1, htc_fluid)
    s5 = PropsSI("S", "T", T_evap_htc_K, "Q", 1, htc_fluid)
    P_evap_htc = PropsSI("P", "T", T_evap_htc_K, "Q", 0, htc_fluid)
    P_cond_htc = PropsSI("P", "T", T_cond_K, "Q", 0, htc_fluid)

    PR_htc = P_cond_htc / P_evap_htc
    eta_htc = compressor_eta(htc_comp, PR_htc)

    h6s = PropsSI("H", "P", P_cond_htc, "S", s5, htc_fluid)
    h6 = h5 + (h6s - h5) / eta_htc
    s6 = PropsSI("S", "H", h6, "P", P_cond_htc, htc_fluid)

    h7 = PropsSI("H", "T", T_cond_K, "Q", 0, htc_fluid)
    s7 = PropsSI("S", "T", T_cond_K, "Q", 0, htc_fluid)
    h8 = h7  # isenthalpic expansion
    s8 = PropsSI("S", "H", h8, "P", P_evap_htc, htc_fluid)

    # Mass flows and work
    m_ltc = Q_evap_W / (h1 - h4)
    W_ltc = m_ltc * (h2 - h1)
    Q_cascade = m_ltc * (h2 - h3)

    m_htc = Q_cascade / (h5 - h8)
    W_htc = m_htc * (h6 - h5)
    W_total = W_ltc + W_htc

    COP = Q_evap_W / W_total
    COP_carnot = T_evap_K / (T_cond_K - T_evap_K)
    eta_II = COP / COP_carnot

    # Exergy destruction (W)
    Ed_comp_ltc = T_0 * m_ltc * (s2 - s1)
    Ed_comp_htc = T_0 * m_htc * (s6 - s5)
    Ed_exp_ltc = T_0 * m_ltc * (s4 - s3)
    Ed_exp_htc = T_0 * m_htc * (s8 - s7)
    Q_cond_W = m_htc * (h6 - h7)
    Ed_cond = T_0 * m_htc * (s7 - s6) + Q_cond_W
    Ed_evap = T_0 * (m_ltc * (s1 - s4) - Q_evap_W / T_evap_K)
    Ed_cascade = T_0 * (m_ltc * (s3 - s2) + m_htc * (s5 - s8))

    components = {
        "compressor_ltc": Ed_comp_ltc / 1000.0,
        "compressor_htc": Ed_comp_htc / 1000.0,
        "condenser": Ed_cond / 1000.0,
        "evaporator": Ed_evap / 1000.0,
        "expansion_valve_ltc": Ed_exp_ltc / 1000.0,
        "expansion_valve_htc": Ed_exp_htc / 1000.0,
        "cascade_hx": Ed_cascade / 1000.0,
    }
    Ed_total = sum(components.values())
    dominant = max(components, key=lambda k: components[k])

    return {
        "COP": COP,
        "carnot_COP": COP_carnot,
        "second_law_efficiency": eta_II,
        "W_total_kW": W_total / 1000.0,
        "W_ltc_kW": W_ltc / 1000.0,
        "W_htc_kW": W_htc / 1000.0,
        "exergy_destruction_total_kW": Ed_total,
        "dominant_irreversibility": dominant,
    }


def feasible_cascade_range(T_evap_C, T_cond_C, cascade_approach_K, ltc_fluid):
    """Determine feasible cascade temperature range respecting critical points."""
    T_crit_ltc = PropsSI("Tcrit", "", 0, "", 0, ltc_fluid) - 273.15
    T_min = T_evap_C + 5.0
    T_max = min(T_crit_ltc - 3.0, T_cond_C - cascade_approach_K - 2.0)
    return T_min, T_max


def optimize_cascade(T_evap_C, T_cond_C, cascade_approach_K, Q_evap_kW,
                     ltc_fluid, htc_fluid, ltc_comp, htc_comp, T_dead_C):
    """Find cascade temperature that maximizes COP."""
    T_min, T_max = feasible_cascade_range(
        T_evap_C, T_cond_C, cascade_approach_K, ltc_fluid)

    def neg_cop(Tc):
        try:
            return -cascade_analysis(
                Tc, T_evap_C, T_cond_C, cascade_approach_K, Q_evap_kW,
                ltc_fluid, htc_fluid, ltc_comp, htc_comp, T_dead_C
            )["COP"]
        except Exception:
            return 1e6

    res = minimize_scalar(neg_cop, bounds=(T_min, T_max), method="bounded",
                          options={"xatol": 0.01, "maxiter": 200})
    T_opt = res.x
    analysis = cascade_analysis(
        T_opt, T_evap_C, T_cond_C, cascade_approach_K, Q_evap_kW,
        ltc_fluid, htc_fluid, ltc_comp, htc_comp, T_dead_C
    )
    return T_opt, analysis


def compute_tewi(annual_energy_kWh, env_params, inv):
    """Compute Total Equivalent Warming Impact."""
    n = env_params["system_lifetime_years"]
    L = env_params["annual_leakage_rate"]
    alpha = env_params["recovery_efficiency"]
    beta = env_params["grid_carbon_intensity_kgCO2_per_kWh"]

    gwp_charge = (inv["ltc"]["gwp"] * inv["ltc"]["charge_kg"] +
                  inv["htc"]["gwp"] * inv["htc"]["charge_kg"])
    direct = gwp_charge * L * n + gwp_charge * (1 - alpha)
    indirect = n * annual_energy_kWh * beta

    return {
        "direct_kg_CO2": direct,
        "indirect_kg_CO2": indirect,
        "total_kg_CO2": direct + indirect,
    }


def main():
    systems, cond, ambient, env, compressors, inventory = load_all_data()

    T_evap_C = cond["evaporator_temperature_C"]
    casc_approach = cond["cascade_approach_K"]
    cond_approach = cond["condenser_approach_K"]
    T_dead_C = cond["dead_state_temperature_C"]
    T_amb_nom = cond["nominal_ambient_C"]
    T_cond_design = T_amb_nom + cond_approach

    results = []
    for sys in systems:
        sid = sys["id"]
        ltc_f = sys["ltc"]["fluid"]
        htc_f = sys["htc"]["fluid"]
        Q = sys["cooling_capacity_kW"]
        ltc_c = compressors[sys["ltc"]["compressor_model"]]
        htc_c = compressors[sys["htc"]["compressor_model"]]

        # Design-point analysis
        T_opt_d, d_analysis = optimize_cascade(
            T_evap_C, T_cond_design, casc_approach, Q,
            ltc_f, htc_f, ltc_c, htc_c, T_dead_C
        )

        # Seasonal analysis
        per_bin = []
        sum_h_over_cop = 0.0
        total_h = 0.0
        for b in ambient:
            T_cond_b = b["T_ambient_C"] + cond_approach
            T_opt_b, b_analysis = optimize_cascade(
                T_evap_C, T_cond_b, casc_approach, Q,
                ltc_f, htc_f, ltc_c, htc_c, T_dead_C
            )
            cop_b = b_analysis["COP"]
            per_bin.append({
                "T_ambient_C": b["T_ambient_C"],
                "COP": cop_b,
                "optimal_cascade_T_C": round(T_opt_b, 2),
            })
            sum_h_over_cop += b["hours"] / cop_b
            total_h += b["hours"]

        seasonal_cop = total_h / sum_h_over_cop
        annual_energy = Q * sum_h_over_cop

        # TEWI
        tewi = compute_tewi(annual_energy, env, inventory[sid])

        results.append({
            "system_id": sid,
            "ltc_fluid": ltc_f,
            "htc_fluid": htc_f,
            "design_point": {
                "T_cond_C": T_cond_design,
                "optimal_cascade_T_C": round(T_opt_d, 2),
                "COP": d_analysis["COP"],
                "carnot_COP": d_analysis["carnot_COP"],
                "second_law_efficiency": d_analysis["second_law_efficiency"],
                "W_total_kW": d_analysis["W_total_kW"],
                "W_ltc_kW": d_analysis["W_ltc_kW"],
                "W_htc_kW": d_analysis["W_htc_kW"],
                "exergy_destruction_total_kW": d_analysis["exergy_destruction_total_kW"],
                "dominant_irreversibility": d_analysis["dominant_irreversibility"],
            },
            "seasonal": {
                "COP": seasonal_cop,
                "annual_energy_kWh": annual_energy,
                "per_bin": per_bin,
            },
            "TEWI": tewi,
        })

    # Rankings
    best_cop = max(results, key=lambda r: r["seasonal"]["COP"])
    lowest_tewi = min(results, key=lambda r: r["TEWI"]["total_kg_CO2"])

    output = {
        "systems": results,
        "best_seasonal_COP": best_cop["system_id"],
        "lowest_TEWI": lowest_tewi["system_id"],
    }

    with open("/app/audit_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Audit complete. Results written to /app/audit_results.json")
    for r in results:
        print(f"  {r['system_id']} ({r['ltc_fluid']}/{r['htc_fluid']}): "
              f"Design COP={r['design_point']['COP']:.3f}, "
              f"Seasonal COP={r['seasonal']['COP']:.3f}, "
              f"TEWI={r['TEWI']['total_kg_CO2']:.0f} kgCO2")
    print(f"Best seasonal COP: {best_cop['system_id']}")
    print(f"Lowest TEWI: {lowest_tewi['system_id']}")


if __name__ == "__main__":
    main()
