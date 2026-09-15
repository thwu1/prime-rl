#!/usr/bin/env python3
"""Solve the warehouse network optimization problem."""

import csv
import json
import os
import sqlite3
from pulp import LpProblem, LpMinimize, LpVariable, lpSum, PULP_CBC_CMD, value

FACILITIES_CSV = "/app/data/network/facilities.csv"
TRANSPORT_CSV = "/app/data/network/transport_matrix.csv"
DEMAND_DB = "/app/data/forecasts/demand_scenarios.db"
OUTPUT_PATH = "/app/output/solution.json"


def load_data():
    """Load and integrate data from CSV files and SQLite database."""
    locations = []
    opening_costs = []
    capacities = []
    with open(FACILITIES_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            locations.append(row["location"])
            opening_costs.append(float(row["setup_cost"]))
            capacities.append(float(row["throughput_limit"]))
    nf = len(locations)

    transport_costs = []
    with open(TRANSPORT_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            costs = [float(row[loc]) for loc in locations]
            transport_costs.append(costs)
    nc = len(transport_costs)

    conn = sqlite3.connect(DEMAND_DB)
    c = conn.cursor()
    c.execute("SELECT scenario_id, probability FROM scenario_info ORDER BY scenario_id")
    scenario_rows = c.fetchall()
    scenarios = []
    for sid, prob in scenario_rows:
        c.execute(
            "SELECT projected_demand FROM zone_demands "
            "WHERE scenario_id=? ORDER BY zone_id",
            (sid,),
        )
        demands = [int(r[0]) for r in c.fetchall()]
        scenarios.append({"probability": prob, "demands": demands})
    conn.close()
    ns = len(scenarios)

    return nf, nc, ns, opening_costs, capacities, transport_costs, scenarios


def solve():
    nf, nc, ns, fc, cap, tc, scenarios = load_data()

    prob = LpProblem("warehouse_optimization", LpMinimize)
    y = [LpVariable(f"y_{j}", cat="Binary") for j in range(nf)]
    x = {}
    for s in range(ns):
        for i in range(nc):
            for j in range(nf):
                x[s, i, j] = LpVariable(f"x_{s}_{i}_{j}", lowBound=0)

    prob += lpSum(fc[j] * y[j] for j in range(nf)) + lpSum(
        scenarios[s]["probability"] * tc[i][j] * x[s, i, j]
        for s in range(ns)
        for i in range(nc)
        for j in range(nf)
    )

    for s in range(ns):
        for i in range(nc):
            prob += (
                lpSum(x[s, i, j] for j in range(nf)) == scenarios[s]["demands"][i]
            )

    for s in range(ns):
        for j in range(nf):
            prob += lpSum(x[s, i, j] for i in range(nc)) <= cap[j] * y[j]

    prob.solve(PULP_CBC_CMD(msg=0))
    assert prob.status == 1, "Problem must be feasible"

    y_val = [int(round(value(y[j]))) for j in range(nf)]
    opened = sorted([j for j in range(nf) if y_val[j] > 0.5])
    oc = sum(fc[j] for j in opened)

    etc_val = sum(
        scenarios[s]["probability"] * tc[i][j] * value(x[s, i, j])
        for s in range(ns)
        for i in range(nc)
        for j in range(nf)
    )

    solution = {
        "objective_value": round(oc + etc_val, 6),
        "facilities_opened": opened,
        "opening_cost": round(oc, 6),
        "expected_transport_cost": round(etc_val, 6),
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(solution, f, indent=2)

    print(f"Solution written to {OUTPUT_PATH}")
    print(f"Objective:  {oc + etc_val:.4f}")
    print(f"Opened:     {opened}")
    print(f"Open cost:  {oc:.2f}")
    print(f"E[transp]:  {etc_val:.4f}")


if __name__ == "__main__":
    solve()
