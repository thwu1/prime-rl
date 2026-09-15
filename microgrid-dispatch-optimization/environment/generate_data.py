#!/usr/bin/env python3
"""Generate stochastic microgrid data for two-stage risk-constrained dispatch optimization."""
import json
import math
import os
import random

random.seed(20240601)

T = 48  # 2-day horizon
NUM_SCENARIOS = 5

system = {
    "solar_capacity_kw": 500,
    "wind_capacity_kw": 300,
    "battery_capacity_kwh": 2000,
    "battery_max_power_kw": 500,
    "battery_charge_efficiency": 0.93,
    "battery_initial_soc_kwh": 1000.0,
    "battery_degradation_cost_per_kwh": 0.025,
    "electrolyzer_max_input_kw": 200,
    "electrolyzer_min_load_fraction": 0.3,
    "electrolyzer_min_uptime_hours": 3,
    "electrolyzer_min_downtime_hours": 2,
    "electrolyzer_initial_state": 0,
    "electrolyzer_pwl_input_kw": [60.0, 140.0, 200.0],
    "electrolyzer_pwl_output_kwh": [30.0, 70.0, 108.0],
    "fuel_cell_max_output_kw": 150,
    "fuel_cell_efficiency": 0.50,
    "h2_tank_capacity_kwh": 5000,
    "h2_initial_level_kwh": 1000.0,
    "grid_import_max_kw": 800,
    "grid_export_max_kw": 400,
    "grid_ramp_rate_kw_per_hour": 250,
    "demand_charge_rate": 15.0,
    "reserve_fraction": 0.10,
}

risk_parameters = {
    "alpha": 0.90,
    "risk_weight": 0.3,
}


def gen_base():
    result = []
    for t in range(T):
        hod = t % 24
        if 7 <= hod <= 18:
            solar_cf = math.sin(math.pi * (hod - 7) / 11)
        else:
            solar_cf = 0.0
        wind_cf = 0.35 + 0.2 * math.sin(2 * math.pi * t / 24 + math.pi / 3)
        wind_cf += 0.08 * math.cos(2 * math.pi * t / 72)
        wind_cf = max(0.05, min(0.95, wind_cf))
        base_demand = 450
        morning = 180 * math.exp(-0.5 * ((hod - 9) / 2) ** 2)
        evening = 250 * math.exp(-0.5 * ((hod - 19) / 2.5) ** 2)
        demand = base_demand + morning + evening
        if hod < 6 or hod >= 23:
            p_imp = 0.05
        elif 15 <= hod < 21:
            p_imp = 0.22
        else:
            p_imp = 0.10
        p_exp = round(p_imp * 0.75, 4)
        result.append({
            "solar_cf": round(solar_cf, 4),
            "wind_cf": round(wind_cf, 4),
            "demand_kw": round(demand, 2),
            "p_imp": p_imp,
            "p_exp": p_exp,
        })
    return result


base = gen_base()

sc_defs = [
    {"name": "sunny_calm",   "prob": 0.25, "sm": 1.30, "wm": 0.50, "dm": 0.95},
    {"name": "sunny_windy",  "prob": 0.20, "sm": 1.15, "wm": 1.50, "dm": 0.90},
    {"name": "cloudy_calm",  "prob": 0.25, "sm": 0.45, "wm": 0.45, "dm": 1.05},
    {"name": "cloudy_windy", "prob": 0.15, "sm": 0.50, "wm": 1.35, "dm": 1.00},
    {"name": "peak_demand",  "prob": 0.15, "sm": 0.65, "wm": 0.60, "dm": 1.40},
]
assert abs(sum(d["prob"] for d in sc_defs) - 1.0) < 1e-9

scenarios = []
for si, sd in enumerate(sc_defs):
    ts = []
    for t in range(T):
        random.seed(20240601 + si * 1000 + t)
        bp = base[t]
        sc = bp["solar_cf"] * sd["sm"] + random.gauss(0, 0.015)
        sc = round(min(1.0, max(0.0, sc)), 4)
        wc = bp["wind_cf"] * sd["wm"] + random.gauss(0, 0.02)
        wc = round(min(0.95, max(0.05, wc)), 4)
        dk = bp["demand_kw"] * sd["dm"] + random.gauss(0, 10)
        dk = round(max(100, dk), 2)
        ts.append({
            "hour": t,
            "solar_cf": sc,
            "wind_cf": wc,
            "demand_kw": dk,
            "grid_import_price": bp["p_imp"],
            "grid_export_price": bp["p_exp"],
        })
    scenarios.append({
        "name": sd["name"],
        "probability": sd["prob"],
        "time_series": ts,
    })

data = {
    "planning_horizon_hours": T,
    "num_scenarios": NUM_SCENARIOS,
    "system": system,
    "risk_parameters": risk_parameters,
    "scenarios": scenarios,
}

os.makedirs("/app/data", exist_ok=True)
with open("/app/data/microgrid_stochastic.json", "w") as f:
    json.dump(data, f, indent=2)

# Verification
with open("/app/data/microgrid_stochastic.json") as f:
    chk = json.load(f)
assert len(chk["scenarios"]) == NUM_SCENARIOS
assert all(len(s["time_series"]) == T for s in chk["scenarios"])
probs = [s["probability"] for s in chk["scenarios"]]
assert abs(sum(probs) - 1.0) < 1e-6
assert "electrolyzer_pwl_input_kw" in chk["system"]
assert "risk_parameters" in chk
print(f"Generated stochastic microgrid data: {T}h x {NUM_SCENARIOS} scenarios, "
      f"{len(system)} system params")
