"""
Solver for multi-width stock roll cutting optimisation.

Reads operational data from the SQLite database, computes remaining demand,
and solves the multi-width cutting stock problem via column generation with
bounded-knapsack pricing per stock type, followed by IP rounding.

"""

import json
import os
import sqlite3
from pulp import (
    LpProblem, LpMinimize, LpVariable, lpSum,
    value, PULP_CBC_CMD, constants,
)


def load_problem():
    conn = sqlite3.connect("/app/data/operations.db")
    conn.row_factory = sqlite3.Row

    # Available stock rolls
    stock = [
        dict(r)
        for r in conn.execute(
            "SELECT type_id, width_mm, unit_cost, inventory "
            "FROM stock_rolls WHERE status='available'"
        ).fetchall()
    ]

    # Products alphabetically
    products = [
        dict(r)
        for r in conn.execute(
            "SELECT product_code, cut_width_mm FROM products ORDER BY product_code"
        ).fetchall()
    ]

    # Active orders
    active_orders = conn.execute(
        "SELECT order_id, product_code, quantity "
        "FROM customer_orders WHERE status='active'"
    ).fetchall()

    active_ids = set()
    product_demand = {}
    for o in active_orders:
        active_ids.add(o["order_id"])
        pc = o["product_code"]
        product_demand[pc] = product_demand.get(pc, 0) + o["quantity"]

    # Subtract production for active orders only
    for row in conn.execute(
        "SELECT order_id, product_code, pieces_produced FROM production_log"
    ).fetchall():
        if row["order_id"] in active_ids:
            pc = row["product_code"]
            product_demand[pc] = product_demand.get(pc, 0) - row["pieces_produced"]

    conn.close()

    pcodes = [p["product_code"] for p in products]
    widths = [p["cut_width_mm"] for p in products]
    demands = [max(0, product_demand.get(pc, 0)) for pc in pcodes]

    return stock, widths, demands, pcodes


def solve():
    stock, widths, demands, pcodes = load_problem()
    n = len(widths)

    stock_map = {s["type_id"]: s for s in stock}
    sids = sorted(stock_map.keys())

    # Initialise trivial patterns per stock type
    patterns = {sid: [] for sid in sids}
    for sid in sids:
        W = stock_map[sid]["width_mm"]
        for i in range(n):
            if widths[i] <= W:
                p = [0] * n
                p[i] = W // widths[i]
                patterns[sid].append(p)

    EPS = 1e-6

    # Column generation loop
    for iteration in range(500):
        prob = LpProblem(f"MW_{iteration}", LpMinimize)

        x = {}
        for sid in sids:
            x[sid] = [
                LpVariable(f"x_{sid}_{j}", lowBound=0)
                for j in range(len(patterns[sid]))
            ]

        prob += lpSum(
            stock_map[sid]["unit_cost"] * xv
            for sid in sids
            for xv in x[sid]
        )

        # Store constraint objects directly to avoid PuLP name-sanitization issues
        demand_ctrs = []
        for i in range(n):
            ctr = (
                lpSum(
                    patterns[sid][j][i] * x[sid][j]
                    for sid in sids
                    for j in range(len(patterns[sid]))
                )
                >= demands[i]
            )
            prob += (ctr, f"d{i}")
            demand_ctrs.append(ctr)

        inv_ctrs = {}
        for sid in sids:
            ctr = lpSum(x[sid]) <= stock_map[sid]["inventory"]
            prob += (ctr, f"inv_{sid}")
            inv_ctrs[sid] = ctr

        prob.solve(PULP_CBC_CMD(msg=0))
        if prob.status != constants.LpStatusOptimal:
            break

        # Get duals from stored constraint objects (avoids name-lookup issues)
        pi = []
        for i in range(n):
            pv = demand_ctrs[i].pi
            pi.append(pv if pv is not None else 0.0)

        inv_pi = {}
        for sid in sids:
            iv = inv_ctrs[sid].pi
            inv_pi[sid] = iv if iv is not None else 0.0

        improved = False
        for sid in sids:
            W = stock_map[sid]["width_mm"]
            c = stock_map[sid]["unit_cost"]

            knap = LpProblem(f"KP_{sid}_{iteration}", LpMinimize)
            y = [LpVariable(f"y{i}", lowBound=0, cat="Integer") for i in range(n)]
            knap += -lpSum(pi[i] * y[i] for i in range(n))
            knap += lpSum(widths[i] * y[i] for i in range(n)) <= W
            for i in range(n):
                ub = W // widths[i]
                if ub > 0:
                    knap += y[i] <= ub

            knap.solve(PULP_CBC_CMD(msg=0))
            if knap.status != constants.LpStatusOptimal:
                continue

            dual_profit = -value(knap.objective)
            reduced_cost = c - dual_profit - inv_pi[sid]

            if reduced_cost < -EPS:
                new_pat = [int(round(value(y[i]))) for i in range(n)]
                if not any(new_pat == p for p in patterns[sid]):
                    patterns[sid].append(new_pat)
                    improved = True

        if not improved:
            break

    # Solve IP
    prob_ip = LpProblem("MW_IP", LpMinimize)
    x_ip = {}
    for sid in sids:
        x_ip[sid] = [
            LpVariable(f"x_{sid}_{j}", lowBound=0, cat="Integer")
            for j in range(len(patterns[sid]))
        ]

    prob_ip += lpSum(
        stock_map[sid]["unit_cost"] * xv
        for sid in sids
        for xv in x_ip[sid]
    )

    for i in range(n):
        prob_ip += (
            lpSum(
                patterns[sid][j][i] * x_ip[sid][j]
                for sid in sids
                for j in range(len(patterns[sid]))
            )
            >= demands[i],
            f"d{i}",
        )

    for sid in sids:
        prob_ip += lpSum(x_ip[sid]) <= stock_map[sid]["inventory"]

    prob_ip.solve(PULP_CBC_CMD(msg=0, timeLimit=300))

    # Build output
    cutting_plan = []
    for sid in sids:
        for j in range(len(patterns[sid])):
            cnt = int(round(value(x_ip[sid][j])))
            if cnt > 0:
                cutting_plan.append({
                    "stock_type": sid,
                    "cuts": patterns[sid][j],
                    "num_rolls": cnt,
                })

    total_cost = sum(
        stock_map[e["stock_type"]]["unit_cost"] * e["num_rolls"]
        for e in cutting_plan
    )

    total_waste = 0
    for e in cutting_plan:
        W = stock_map[e["stock_type"]]["width_mm"]
        used = sum(e["cuts"][j] * widths[j] for j in range(n))
        total_waste += (W - used) * e["num_rolls"]

    result = {
        "total_cost": total_cost,
        "cutting_plan": cutting_plan,
        "total_waste_mm": total_waste,
    }

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/solution.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Solution written to /app/results/solution.json")
    print(f"  Total cost:  ${total_cost:.2f}")
    print(f"  Total waste: {total_waste} mm")
    print(f"  Plan entries: {len(cutting_plan)}")


if __name__ == "__main__":
    solve()
