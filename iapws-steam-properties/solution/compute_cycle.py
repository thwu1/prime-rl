#!/usr/bin/env python3
"""
Compute Rankine cycle analysis from corrected IAPWS-IF97 module.

"""
import sys
import json
import tomllib

sys.path.insert(0, '/app')
from wrapper import IF97Engine


def main():
    with open('/app/cycle_config.toml', 'rb') as f:
        cfg = tomllib.load(f)

    p_boiler = cfg['boiler']['pressure_mpa']
    T_boiler = cfg['boiler']['temperature_k']
    p_cond = cfg['condenser']['pressure_mpa']
    eta_t = cfg['turbine']['isentropic_efficiency']
    eta_p = cfg['pump']['isentropic_efficiency']

    eng = IF97Engine()

    # State 1: Turbine inlet (superheated steam, Region 2)
    r2 = eng.region2_props(T_boiler, p_boiler)
    h1 = r2['h']
    s1 = r2['s']
    v1 = r2['v']

    # State 3: Condenser outlet (saturated liquid at p_cond)
    T_sat = eng.saturation_temperature(p_cond)
    r1_sat = eng.region1_props(T_sat, p_cond)
    r2_sat = eng.region2_props(T_sat, p_cond)
    hf = r1_sat['h']
    sf = r1_sat['s']
    vf = r1_sat['v']
    hg = r2_sat['h']
    sg = r2_sat['s']

    # State 2s: Isentropic turbine outlet
    x2s = (s1 - sf) / (sg - sf)
    h2s = hf + x2s * (hg - hf)

    # State 2: Actual turbine outlet
    h2 = h1 - eta_t * (h1 - h2s)
    x2 = (h2 - hf) / (hg - hf) if h2 < hg else 1.0
    s2 = sf + x2 * (sg - sf) if h2 < hg else sg

    # State 4: Pump outlet
    w_pump_ideal = vf * (p_boiler - p_cond) * 1000.0  # kJ/kg
    w_pump = w_pump_ideal / eta_p
    h4 = hf + w_pump

    # Cycle performance
    w_turbine = h1 - h2
    w_net = w_turbine - w_pump
    q_in = h1 - h4
    cycle_eff = w_net / q_in
    bwr = w_pump / w_turbine

    # Transport properties at turbine inlet
    rho1 = 1.0 / v1
    mu1 = eng.viscosity(rho1, T_boiler)
    k1 = eng.thermal_conductivity(rho1, T_boiler)

    results = {
        "turbine_inlet": {
            "T": T_boiler, "p": p_boiler,
            "h": h1, "s": s1
        },
        "turbine_outlet_actual": {
            "h": h2
        },
        "condenser_outlet": {
            "T": T_sat, "p": p_cond,
            "h": hf, "s": sf, "v": vf
        },
        "pump_outlet": {
            "h": h4
        },
        "cycle_efficiency": cycle_eff,
        "net_specific_work_kj_per_kg": w_net,
        "heat_input_kj_per_kg": q_in,
        "back_work_ratio": bwr,
        "turbine_inlet_viscosity_pa_s": mu1,
        "turbine_inlet_conductivity_w_per_m_k": k1
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Cycle efficiency: {cycle_eff:.4f}")
    print(f"Net specific work: {w_net:.2f} kJ/kg")
    print(f"Results written to /app/results.json")


if __name__ == '__main__':
    main()
