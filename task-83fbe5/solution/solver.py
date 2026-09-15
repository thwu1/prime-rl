#!/usr/bin/env python3
"""
Reference solver for stochastic capacitated facility location with tail-risk.
Reads data from /app/data/, solves all required problems, writes /app/results.json.
"""

import csv
import json
import os
import shutil
import pulp

_counter = [0]


def _ensure_data():
    """Ensure data files exist in /app/data/, copying from backup if needed."""
    if not os.path.exists("/app/data/facilities.csv"):
        os.makedirs("/app/data", exist_ok=True)
        if os.path.isdir("/opt/task_instance"):
            for fn in os.listdir("/opt/task_instance"):
                src = f"/opt/task_instance/{fn}"
                if os.path.isfile(src):
                    shutil.copy2(src, f"/app/data/{fn}")


def load_data():
    """Load instance data from CSV/JSON files."""
    _ensure_data()
    with open("/app/data/facilities.csv") as f:
        reader = csv.DictReader(f)
        fac_rows = list(reader)
    n_fac = len(fac_rows)
    f_costs = [float(r["fixed_cost"]) for r in fac_rows]
    caps = [float(r["capacity"]) for r in fac_rows]

    with open("/app/data/shipping_costs.csv") as f:
        reader = csv.DictReader(f)
        cust_cols = [c for c in reader.fieldnames if c != "facility_id"]
        t_costs = []
        for row in reader:
            t_costs.append([float(row[c]) for c in cust_cols])
    n_cust = len(cust_cols)

    with open("/app/data/demand_scenarios.csv") as f:
        reader = csv.DictReader(f)
        dem_cols = [c for c in reader.fieldnames if c != "scenario_id"]
        demands = []
        for row in reader:
            demands.append([float(row[c]) for c in dem_cols])
    n_scen = len(demands)

    with open("/app/data/parameters.json") as f:
        params = json.load(f)

    if params.get("scenario_weighting") == "equiprobable":
        probs = [1.0 / n_scen] * n_scen
    else:
        raise ValueError("Unknown scenario_weighting")

    return {
        "n_fac": n_fac, "n_cust": n_cust, "n_scen": n_scen,
        "f_costs": f_costs, "caps": caps, "t_costs": t_costs,
        "demands": demands, "probs": probs,
        "penalty": params["shortage_penalty_per_unit"],
        "alpha": params["tail_quantile"],
        "risk_weight": params["risk_weight"],
    }


def solve_fl(n_fac, n_cust, f_costs, caps, t_costs, demands_list, probs_list,
             penalty, risk_weight=0.0, alpha=0.95, fixed_facilities=None):
    """Solve stochastic capacitated facility location problem.

    When risk_weight > 0, minimizes:
        facility_cost + (1-lambda)*E[Q] + lambda*CVaR_alpha(Q)
    using the Rockafellar-Uryasev linearization for CVaR.
    """
    _counter[0] += 1
    p = f"c{_counter[0]}_"
    n_scen = len(demands_list)

    prob = pulp.LpProblem(f"SFL_{_counter[0]}", pulp.LpMinimize)

    # First-stage: facility open/close
    y = [pulp.LpVariable(f"{p}y_{i}", cat="Binary") for i in range(n_fac)]

    if fixed_facilities is not None:
        for i in range(n_fac):
            if i in fixed_facilities:
                prob += y[i] == 1
            else:
                prob += y[i] == 0

    # Second-stage: shipping and unmet demand per scenario
    x = [[[pulp.LpVariable(f"{p}x_{i}_{j}_{s}", lowBound=0)
            for s in range(n_scen)]
           for j in range(n_cust)]
          for i in range(n_fac)]

    u = [[pulp.LpVariable(f"{p}u_{j}_{s}", lowBound=0)
          for s in range(n_scen)]
         for j in range(n_cust)]

    # Per-scenario recourse cost
    Q = []
    for s in range(n_scen):
        q = pulp.lpSum(t_costs[i][j] * x[i][j][s]
                       for i in range(n_fac) for j in range(n_cust)) \
            + penalty * pulp.lpSum(u[j][s] for j in range(n_cust))
        Q.append(q)

    fac_cost_expr = pulp.lpSum(f_costs[i] * y[i] for i in range(n_fac))
    exp_cost_expr = pulp.lpSum(probs_list[s] * Q[s] for s in range(n_scen))

    # Objective
    if risk_weight > 1e-12:
        eta = pulp.LpVariable(f"{p}eta")
        z = [pulp.LpVariable(f"{p}z_{s}", lowBound=0) for s in range(n_scen)]
        cvar_expr = eta + (1.0 / (1.0 - alpha)) * pulp.lpSum(
            probs_list[s] * z[s] for s in range(n_scen))
        prob += fac_cost_expr + (1.0 - risk_weight) * exp_cost_expr \
                + risk_weight * cvar_expr
        for s in range(n_scen):
            prob += z[s] >= Q[s] - eta
    else:
        eta = None
        z = None
        prob += fac_cost_expr + exp_cost_expr

    # Capacity constraints
    for i in range(n_fac):
        for s in range(n_scen):
            prob += pulp.lpSum(x[i][j][s] for j in range(n_cust)) <= caps[i] * y[i]

    # Demand satisfaction
    for j in range(n_cust):
        for s in range(n_scen):
            prob += pulp.lpSum(x[i][j][s] for i in range(n_fac)) \
                    + u[j][s] >= demands_list[s][j]

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=120)
    prob.solve(solver)
    assert prob.status == 1, f"Solver status {prob.status} != Optimal"

    open_facs = sorted([i for i in range(n_fac) if pulp.value(y[i]) > 0.5])
    obj_val = pulp.value(prob.objective)

    sc_costs = []
    for s in range(n_scen):
        sc = sum(t_costs[i][j] * pulp.value(x[i][j][s])
                 for i in range(n_fac) for j in range(n_cust)) \
             + penalty * sum(pulp.value(u[j][s]) for j in range(n_cust))
        sc_costs.append(round(sc, 8))

    fc = sum(f_costs[i] for i in open_facs)
    ec = sum(probs_list[s] * sc_costs[s] for s in range(n_scen))

    result = {
        "objective_value": round(obj_val, 8),
        "facilities_open": open_facs,
        "facility_cost": round(fc, 8),
        "expected_second_stage_cost": round(ec, 8),
        "scenario_costs": sc_costs,
    }

    if risk_weight > 1e-12 and eta is not None:
        eta_v = pulp.value(eta)
        cvar_v = eta_v + (1.0 / (1.0 - alpha)) * sum(
            probs_list[s] * pulp.value(z[s]) for s in range(n_scen))
        result["var_value"] = round(eta_v, 8)
        result["cvar_value"] = round(cvar_v, 8)

    return result


def main():
    data = load_data()
    common = dict(n_fac=data["n_fac"], n_cust=data["n_cust"],
                  f_costs=data["f_costs"], caps=data["caps"],
                  t_costs=data["t_costs"], penalty=data["penalty"])

    # 1. Risk-neutral recourse problem (RP)
    rp = solve_fl(demands_list=data["demands"], probs_list=data["probs"],
                  risk_weight=0.0, **common)
    print(f"Risk-neutral objective: {rp['objective_value']}")

    # 2. Risk-averse recourse problem (RA) with CVaR
    ra = solve_fl(demands_list=data["demands"], probs_list=data["probs"],
                  risk_weight=data["risk_weight"], alpha=data["alpha"], **common)
    print(f"Risk-averse objective:  {ra['objective_value']}")

    # 3. VSS: solve EV problem then evaluate EV facilities under full scenarios
    n_scen = data["n_scen"]
    mean_demands = [[sum(data["demands"][s][j] * data["probs"][s]
                         for s in range(n_scen))
                     for j in range(data["n_cust"])]]
    ev = solve_fl(demands_list=mean_demands, probs_list=[1.0],
                  risk_weight=0.0, **common)
    eev = solve_fl(demands_list=data["demands"], probs_list=data["probs"],
                   risk_weight=0.0,
                   fixed_facilities=set(ev["facilities_open"]), **common)
    vss = eev["objective_value"] - rp["objective_value"]
    print(f"VSS: {vss}")

    # 4. EVPI: solve each scenario individually (wait-and-see)
    ws_total = 0.0
    for s in range(n_scen):
        ws_s = solve_fl(demands_list=[data["demands"][s]], probs_list=[1.0],
                        risk_weight=0.0, **common)
        ws_total += data["probs"][s] * ws_s["objective_value"]
    evpi = rp["objective_value"] - ws_total
    print(f"EVPI: {evpi}")

    results = {
        "risk_neutral": {
            "objective_value": rp["objective_value"],
            "facilities_open": rp["facilities_open"],
            "facility_cost": rp["facility_cost"],
            "expected_second_stage_cost": rp["expected_second_stage_cost"],
            "scenario_costs": rp["scenario_costs"],
        },
        "risk_averse": {
            "objective_value": ra["objective_value"],
            "facilities_open": ra["facilities_open"],
            "facility_cost": ra["facility_cost"],
            "expected_second_stage_cost": ra["expected_second_stage_cost"],
            "var_value": ra["var_value"],
            "cvar_value": ra["cvar_value"],
            "scenario_costs": ra["scenario_costs"],
        },
        "vss": round(vss, 8),
        "evpi": round(evpi, 8),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
