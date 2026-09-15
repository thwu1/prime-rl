#!/usr/bin/env python3
"""
Solves the cutting stock optimization task:
1. Explores the production database to assemble the problem instance
2. Implements Gilmore-Gomory column generation for LP bound
3. Solves the integer program over generated columns
"""


import csv
import json
import math
import os
import random
import sqlite3

import pulp


def discover_instance():
    """
    Explore the production database and adjustment files to assemble
    the cutting stock instance (roll_width, item widths, demands).
    """
    db_path = "/app/data/production.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Step 1: Find the active material type from machine_config
    c.execute("SELECT value FROM machine_config WHERE key = 'active_material_type'")
    active_material = c.fetchone()[0]
    print(f"Active material type: {active_material}")

    # Step 2: Find the roll width for the active, available material
    c.execute(
        "SELECT width FROM roll_stock "
        "WHERE material_type = ? AND available = 1",
        (active_material,),
    )
    row = c.fetchone()
    roll_width = row[0]
    print(f"Roll width: {roll_width}")

    # Step 3: Get all pending work order IDs
    c.execute("SELECT id FROM work_orders WHERE status = 'pending'")
    pending_ids = [r[0] for r in c.fetchall()]
    print(f"Pending orders: {len(pending_ids)}")

    # Step 4: Aggregate demands from order_lines for pending orders
    placeholders = ",".join("?" for _ in pending_ids)
    c.execute(
        f"SELECT piece_width, SUM(quantity) FROM order_lines "
        f"WHERE work_order_id IN ({placeholders}) "
        f"GROUP BY piece_width ORDER BY piece_width DESC",
        pending_ids,
    )
    base_demands = {}
    for width, qty in c.fetchall():
        base_demands[width] = qty

    conn.close()

    # Step 5: Apply demand adjustments from CSV
    adj_path = "/app/data/adjustments/2024_q4_adjustments.csv"
    if os.path.isfile(adj_path):
        with open(adj_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                w = int(row["piece_width"])
                change = int(row["quantity_change"])
                base_demands[w] = base_demands.get(w, 0) + change

    # Step 6: Build sorted item list (descending width)
    sorted_widths = sorted(base_demands.keys(), reverse=True)
    widths = sorted_widths
    demands = [base_demands[w] for w in widths]

    print(f"Item types: {len(widths)}")
    for w, d in zip(widths, demands):
        print(f"  width={w}, demand={d}")

    return roll_width, widths, demands


def unbounded_knapsack(profits, weights, capacity):
    """Unbounded knapsack via DP. Returns (max_profit, pattern)."""
    n = len(profits)
    dp = [0.0] * (capacity + 1)
    choice = [-1] * (capacity + 1)

    for c in range(1, capacity + 1):
        for i in range(n):
            if weights[i] <= c:
                val = dp[c - weights[i]] + profits[i]
                if val > dp[c] + 1e-10:
                    dp[c] = val
                    choice[c] = i

    pattern = [0] * n
    c = capacity
    while c > 0 and choice[c] >= 0:
        idx = choice[c]
        pattern[idx] += 1
        c -= weights[idx]

    return dp[capacity], pattern


def solve():
    roll_w, widths, demands = discover_instance()
    n = len(widths)

    # Phase 1: Column generation for LP relaxation
    patterns = []
    for i in range(n):
        p = [0] * n
        p[i] = roll_w // widths[i]
        patterns.append(p)

    lp_bound = None
    final_duals = None

    for iteration in range(1000):
        prob = pulp.LpProblem("CuttingStock_RMP", pulp.LpMinimize)
        m = len(patterns)
        x = [pulp.LpVariable(f"x_{j}", lowBound=0) for j in range(m)]
        prob += pulp.lpSum(x)

        for i in range(n):
            prob += (
                pulp.lpSum(patterns[j][i] * x[j] for j in range(m))
                >= demands[i],
                f"demand_{i}",
            )

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        if prob.status != pulp.constants.LpStatusOptimal:
            raise RuntimeError(f"RMP LP failed, status={prob.status}")

        lp_bound = pulp.value(prob.objective)

        duals = []
        for i in range(n):
            pi_val = prob.constraints[f"demand_{i}"].pi
            duals.append(pi_val if pi_val is not None else 0.0)
        final_duals = duals

        best_rc, new_pattern = unbounded_knapsack(duals, widths, roll_w)

        if best_rc <= 1.0 + 1e-6:
            break

        if new_pattern not in patterns:
            patterns.append(new_pattern)
        else:
            break

    print(f"LP bound: {lp_bound:.6f}")
    print(f"Columns after CG: {len(patterns)}")

    # Phase 2: Column enrichment for IP quality
    pattern_set = set(tuple(p) for p in patterns)

    def add_pattern(pat):
        key = tuple(pat)
        if key not in pattern_set and sum(pat) > 0:
            pattern_set.add(key)
            patterns.append(pat)

    random.seed(12345)

    if final_duals is not None:
        for _ in range(200):
            perturbed = [
                max(0, d * random.uniform(0.3, 3.0)) for d in final_duals
            ]
            _, pat = unbounded_knapsack(perturbed, widths, roll_w)
            add_pattern(pat)

    for _ in range(300):
        profits = [random.uniform(0.001, 1.0) for _ in range(n)]
        _, pat = unbounded_knapsack(profits, widths, roll_w)
        add_pattern(pat)

    for _ in range(200):
        profits = [
            widths[i] / roll_w * random.uniform(0.2, 3.0) for i in range(n)
        ]
        _, pat = unbounded_knapsack(profits, widths, roll_w)
        add_pattern(pat)

    for _ in range(100):
        profits = [
            demands[i] * random.uniform(0.01, 0.1) for i in range(n)
        ]
        _, pat = unbounded_knapsack(profits, widths, roll_w)
        add_pattern(pat)

    print(f"Columns after enrichment: {len(patterns)}")

    # Phase 3: Solve IP with enriched column pool
    prob_ip = pulp.LpProblem("CuttingStock_IP", pulp.LpMinimize)
    m = len(patterns)
    x_ip = [
        pulp.LpVariable(f"x_{j}", lowBound=0, cat="Integer") for j in range(m)
    ]
    prob_ip += pulp.lpSum(x_ip)

    for i in range(n):
        prob_ip += (
            pulp.lpSum(patterns[j][i] * x_ip[j] for j in range(m))
            >= demands[i],
            f"demand_{i}",
        )

    prob_ip.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=120))

    # Collect solution
    solution_patterns = []
    total_rolls = 0
    for j in range(m):
        val = pulp.value(x_ip[j])
        if val is not None and val > 0.5:
            count = int(round(val))
            solution_patterns.append({
                "pattern": patterns[j],
                "num_rolls": count,
            })
            total_rolls += count

    result = {
        "lp_bound": round(lp_bound, 6),
        "num_rolls": total_rolls,
        "patterns": solution_patterns,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/solution.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Integer solution: {total_rolls} rolls")
    print(f"Distinct patterns used: {len(solution_patterns)}")
    print(f"Gap: {total_rolls - math.ceil(lp_bound)} rolls above LP ceiling")


if __name__ == "__main__":
    solve()
