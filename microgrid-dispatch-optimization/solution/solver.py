#!/usr/bin/env python3

"""Solve the two-stage stochastic microgrid dispatch with CVaR risk measure."""
import json
import os
import sys
from pulp import *


def load_data():
    with open("/app/data/microgrid_stochastic.json") as f:
        return json.load(f)


def solve_milp(data, fix_eon=None, risk_weight_override=None):
    """
    Solve the two-stage stochastic MILP with CVaR.

    First stage: electrolyzer commitment eon_t (binary), shared across scenarios.
    Second stage: continuous dispatch + PWL segment binaries per scenario.

    Args:
        data: parsed JSON data dict
        fix_eon: if provided, list of 0/1 ints fixing first-stage decisions
        risk_weight_override: override risk_weight (e.g. 0.0 for EV problem)

    Returns dict with solution details, or None if infeasible.
    """
    T = data["planning_horizon_hours"]
    S = data["num_scenarios"]
    sp = data["system"]
    rp = data["risk_parameters"]
    scens = data["scenarios"]
    alpha = rp["alpha"]
    lam = risk_weight_override if risk_weight_override is not None else rp["risk_weight"]

    pwl_x = sp["electrolyzer_pwl_input_kw"]
    pwl_y = sp["electrolyzer_pwl_output_kwh"]
    K = len(pwl_x) - 1  # number of PWL segments

    probs = [scens[s]["probability"] for s in range(S)]
    fci = 1.0 / sp["fuel_cell_efficiency"]
    dg = sp["battery_degradation_cost_per_kwh"]
    dr = sp["demand_charge_rate"]

    prob = LpProblem("StochMG", LpMinimize)

    # --- First stage ---
    fixed = fix_eon is not None
    if fixed:
        eon = fix_eon
    else:
        eon = [LpVariable(f"eon_{t}", cat="Binary") for t in range(T)]

    # --- Second stage per scenario ---
    so = {}; wi = {}; bc = {}; bd = {}; bs = {}
    gi = {}; ge = {}; fc = {}; h2 = {}
    ei = {}; hp = {}; sw = {}; sl = {}; pk = {}

    for s in range(S):
        ts = scens[s]["time_series"]
        pk[s] = LpVariable(f"pk_{s}", 0)
        for t in range(T):
            so[t, s] = LpVariable(f"so_{t}_{s}", 0, sp["solar_capacity_kw"] * ts[t]["solar_cf"])
            wi[t, s] = LpVariable(f"wi_{t}_{s}", 0, sp["wind_capacity_kw"] * ts[t]["wind_cf"])
            bc[t, s] = LpVariable(f"bc_{t}_{s}", 0, sp["battery_max_power_kw"])
            bd[t, s] = LpVariable(f"bd_{t}_{s}", 0, sp["battery_max_power_kw"])
            bs[t, s] = LpVariable(f"bs_{t}_{s}", 0, sp["battery_capacity_kwh"])
            gi[t, s] = LpVariable(f"gi_{t}_{s}", 0, sp["grid_import_max_kw"])
            ge[t, s] = LpVariable(f"ge_{t}_{s}", 0, sp["grid_export_max_kw"])
            fc[t, s] = LpVariable(f"fc_{t}_{s}", 0, sp["fuel_cell_max_output_kw"])
            h2[t, s] = LpVariable(f"h2_{t}_{s}", 0, sp["h2_tank_capacity_kwh"])
            ei[t, s] = LpVariable(f"ei_{t}_{s}", 0, sp["electrolyzer_max_input_kw"])
            hp[t, s] = LpVariable(f"hp_{t}_{s}", 0)
            for k in range(K):
                sw[t, s, k] = LpVariable(f"sw_{t}_{s}_{k}", cat="Binary")
                sl[t, s, k] = LpVariable(f"sl_{t}_{s}_{k}", 0, 1)

    # --- CVaR variables ---
    eta = LpVariable("eta")  # VaR (free sign)
    u = [LpVariable(f"u_{s}", 0) for s in range(S)]

    # --- Scenario cost expressions ---
    c = {}
    for s in range(S):
        ts = scens[s]["time_series"]
        c[s] = (
            lpSum(
                ts[t]["grid_import_price"] * gi[t, s]
                - ts[t]["grid_export_price"] * ge[t, s]
                for t in range(T)
            )
            + dr * pk[s]
            + dg * lpSum(bc[t, s] + bd[t, s] for t in range(T))
        )

    # --- Objective: (1-λ)*E[c] + λ*CVaR_α(c) ---
    exp_cost = lpSum(probs[s] * c[s] for s in range(S))
    cvar_expr = eta + (1.0 / (1.0 - alpha)) * lpSum(probs[s] * u[s] for s in range(S))
    prob += (1 - lam) * exp_cost + lam * cvar_expr

    # --- CVaR constraints ---
    for s in range(S):
        prob += u[s] >= c[s] - eta

    # --- Operational constraints per scenario ---
    for s in range(S):
        ts = scens[s]["time_series"]
        for t in range(T):
            # Energy balance
            prob += (
                so[t, s] + wi[t, s] + bd[t, s] + fc[t, s] + gi[t, s]
                == ts[t]["demand_kw"] + bc[t, s] + ei[t, s] + ge[t, s]
            )
            # Battery SOC dynamics
            prev_soc = sp["battery_initial_soc_kwh"] if t == 0 else bs[t - 1, s]
            prob += bs[t, s] == prev_soc + sp["battery_charge_efficiency"] * bc[t, s] - bd[t, s]
            # H2 tank dynamics
            prev_h2 = sp["h2_initial_level_kwh"] if t == 0 else h2[t - 1, s]
            prob += h2[t, s] == prev_h2 + hp[t, s] - fci * fc[t, s]
            # Peak import tracking
            prob += pk[s] >= gi[t, s]
            # Grid ramp rate
            if t >= 1:
                prob += gi[t, s] - gi[t - 1, s] <= sp["grid_ramp_rate_kw_per_hour"]
                prob += gi[t - 1, s] - gi[t, s] <= sp["grid_ramp_rate_kw_per_hour"]
            # Reserve requirement
            prob += (
                (sp["grid_import_max_kw"] - gi[t, s])
                + (sp["battery_max_power_kw"] - bd[t, s])
                >= sp["reserve_fraction"] * ts[t]["demand_kw"]
            )
            # PWL electrolyzer: disaggregated convex combination
            eon_t = eon[t]
            prob += lpSum(sw[t, s, k] for k in range(K)) == eon_t
            for k in range(K):
                prob += sl[t, s, k] <= sw[t, s, k]
            prob += ei[t, s] == lpSum(
                pwl_x[k] * sw[t, s, k] + (pwl_x[k + 1] - pwl_x[k]) * sl[t, s, k]
                for k in range(K)
            )
            prob += hp[t, s] == lpSum(
                pwl_y[k] * sw[t, s, k] + (pwl_y[k + 1] - pwl_y[k]) * sl[t, s, k]
                for k in range(K)
            )

        # End-of-horizon sustainability per scenario
        prob += bs[T - 1, s] >= sp["battery_initial_soc_kwh"]
        prob += h2[T - 1, s] >= sp["h2_initial_level_kwh"]

    # --- First-stage constraints (min uptime/downtime) ---
    if not fixed:
        mu = sp["electrolyzer_min_uptime_hours"]
        md = sp["electrolyzer_min_downtime_hours"]
        ist = sp["electrolyzer_initial_state"]
        for t in range(T):
            prev = ist if t == 0 else eon[t - 1]
            for j in range(1, mu):
                if t + j < T:
                    prob += eon[t + j] >= eon[t] - prev
            for j in range(1, md):
                if t + j < T:
                    prob += eon[t + j] <= 1 - (prev - eon[t])

    # --- Solve ---
    prob.solve(PULP_CBC_CMD(msg=0, gapRel=0.002, timeLimit=180))

    if prob.status != 1:
        print(f"Solver status: {LpStatus[prob.status]}", file=sys.stderr)
        return None

    # --- Extract results ---
    eon_vals = [int(round(value(eon[t]))) if not fixed else eon[t] for t in range(T)]
    sc_costs = [value(c[s]) for s in range(S)]
    ec = sum(probs[s] * sc_costs[s] for s in range(S))
    cv = value(eta) + sum(probs[s] * value(u[s]) for s in range(S)) / (1.0 - alpha)

    ren_fracs = []
    for s in range(S):
        ts = scens[s]["time_series"]
        td = sum(ts[t]["demand_kw"] for t in range(T))
        tr = sum(value(so[t, s]) + value(wi[t, s]) for t in range(T))
        ren_fracs.append(tr / td if td > 0 else 0)

    return {
        "objective": value(prob.objective),
        "eon_values": eon_vals,
        "scenario_costs": sc_costs,
        "expected_cost": ec,
        "eta": value(eta),
        "cvar": cv,
        "renewable_fractions": ren_fracs,
    }


def solve_ev_problem(data):
    """Solve the deterministic Expected Value problem using mean scenario."""
    T = data["planning_horizon_hours"]
    S = data["num_scenarios"]
    scens = data["scenarios"]
    probs = [scens[s]["probability"] for s in range(S)]

    mean_ts = []
    for t in range(T):
        solar_cf = sum(probs[s] * scens[s]["time_series"][t]["solar_cf"] for s in range(S))
        wind_cf = sum(probs[s] * scens[s]["time_series"][t]["wind_cf"] for s in range(S))
        demand_kw = sum(probs[s] * scens[s]["time_series"][t]["demand_kw"] for s in range(S))
        mean_ts.append({
            "hour": t,
            "solar_cf": solar_cf,
            "wind_cf": wind_cf,
            "demand_kw": demand_kw,
            "grid_import_price": scens[0]["time_series"][t]["grid_import_price"],
            "grid_export_price": scens[0]["time_series"][t]["grid_export_price"],
        })

    ev_data = {
        "planning_horizon_hours": T,
        "num_scenarios": 1,
        "system": data["system"],
        "risk_parameters": {"alpha": 0.90, "risk_weight": 0.0},
        "scenarios": [{"name": "mean", "probability": 1.0, "time_series": mean_ts}],
    }

    result = solve_milp(ev_data, risk_weight_override=0.0)
    if result is None:
        return None
    return {
        "ev_objective": result["objective"],
        "ev_eon_values": result["eon_values"],
    }


def main():
    data = load_data()

    # 1. Solve stochastic problem (RP)
    print("Solving stochastic problem (RP)...")
    rp = solve_milp(data)
    assert rp is not None, "Stochastic problem infeasible"
    print(f"  RP objective: {rp['objective']:.2f}")
    print(f"  Expected cost: {rp['expected_cost']:.2f}")
    print(f"  CVaR: {rp['cvar']:.2f}")
    print(f"  VaR (eta): {rp['eta']:.2f}")

    # 2. Solve EV problem
    print("Solving Expected Value problem (EV)...")
    ev = solve_ev_problem(data)
    assert ev is not None, "EV problem infeasible"
    print(f"  EV objective: {ev['ev_objective']:.2f}")

    # 3. Evaluate EV commitment in stochastic setting (EEV)
    print("Evaluating EV commitment stochastically (EEV)...")
    eev = solve_milp(data, fix_eon=ev["ev_eon_values"])
    assert eev is not None, "EEV evaluation infeasible"
    eev_ec = eev["expected_cost"]
    print(f"  EEV expected cost: {eev_ec:.2f}")

    # 4. Compute VSS
    vss = eev_ec - rp["expected_cost"]
    print(f"  VSS: {vss:.2f}")

    # 5. Compile results
    S = data["num_scenarios"]
    probs = [data["scenarios"][s]["probability"] for s in range(S)]

    results = {
        "stochastic_objective": round(rp["objective"], 2),
        "expected_cost": round(rp["expected_cost"], 2),
        "cvar_cost": round(rp["cvar"], 2),
        "var_cost": round(rp["eta"], 2),
        "ev_objective": round(ev["ev_objective"], 2),
        "eev_cost": round(eev_ec, 2),
        "vss": round(vss, 2),
        "worst_scenario_cost": round(max(rp["scenario_costs"]), 2),
        "best_scenario_cost": round(min(rp["scenario_costs"]), 2),
        "total_electrolyzer_on_hours": sum(rp["eon_values"]),
        "expected_renewable_fraction": round(
            sum(probs[s] * rp["renewable_fractions"][s] for s in range(S)), 4
        ),
    }

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/solution.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results/solution.json")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
