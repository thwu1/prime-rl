#!/usr/bin/env python3
"""
Solve the cutting stock problem via Gilmore-Gomory column generation.

Algorithm:
  1. Initialize restricted master LP with trivial single-item patterns.
  2. Solve master LP to get dual prices (shadow prices on demand constraints).
  3. Solve pricing subproblem: bounded knapsack maximizing dual profit.
     If best reduced cost < 0, add new pattern column to master.
  4. Repeat until no improving column exists (LP optimality).
  5. Solve restricted master as integer program for feasible cutting plan.
  6. Report LP bound, integer solution, and optimality gap.
"""

import csv
import json
import os
import sqlite3

from pulp import (
    PULP_CBC_CMD,
    LpInteger,
    LpMinimize,
    LpProblem,
    LpVariable,
    lpSum,
    value,
)

REGULAR_CSV = "/app/data/orders/regular_orders.csv"
PRIORITY_CSV = "/app/data/orders/priority_orders.csv"
STOCK_DB = "/app/data/inventory/stock.db"
CONFIG_JSON = "/app/data/config/cutting_params.json"


def load_data():
    """Load and integrate data from all sources."""
    orders = []

    # Regular orders
    with open(REGULAR_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append(
                {
                    "product_code": row["product_code"],
                    "width": int(row["width_mm"]),
                    "demand": int(row["quantity_required"]),
                }
            )

    # Priority orders (different column names)
    with open(PRIORITY_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            orders.append(
                {
                    "product_code": row["item_code"],
                    "width": int(row["cut_width_mm"]),
                    "demand": int(row["units_needed"]),
                }
            )

    orders.sort(key=lambda x: x["product_code"])

    # Stock width from SQLite
    conn = sqlite3.connect(STOCK_DB)
    c = conn.cursor()
    c.execute("SELECT width_mm FROM stock_rolls LIMIT 1")
    stock_width = c.fetchone()[0]
    conn.close()

    # Output config
    with open(CONFIG_JSON) as f:
        config = json.load(f)
    output_dir = config["output"]["directory"]
    output_file = config["output"]["filename"]
    output_path = os.path.join(output_dir, output_file)

    return orders, stock_width, output_path


def solve_bounded_knapsack(widths, profits, capacity, upper_bounds):
    """
    Bounded knapsack via DP with binary expansion.

    Finds pattern maximizing sum(profits[i] * a[i])
    subject to sum(widths[i] * a[i]) <= capacity, 0 <= a[i] <= upper_bounds[i].

    Returns (max_profit, pattern_dict).
    """
    n = len(widths)

    # Binary expansion of bounded items into 0-1 items
    bin_items = []
    for i in range(n):
        if profits[i] <= 1e-10 or widths[i] > capacity:
            continue
        u = min(upper_bounds[i], capacity // widths[i])
        if u <= 0:
            continue
        rem = u
        k = 1
        while rem > 0:
            take = min(k, rem)
            bin_items.append((take * widths[i], take * profits[i], i, take))
            rem -= take
            k *= 2

    if not bin_items:
        return 0.0, {}

    nb = len(bin_items)
    dp = [0.0] * (capacity + 1)
    used = [[False] * (capacity + 1) for _ in range(nb)]

    for bi in range(nb):
        bw, bp = bin_items[bi][0], bin_items[bi][1]
        for w in range(capacity, bw - 1, -1):
            if dp[w - bw] + bp > dp[w] + 1e-12:
                dp[w] = dp[w - bw] + bp
                used[bi][w] = True

    # Find capacity level with best profit
    best_w = 0
    for w in range(capacity + 1):
        if dp[w] > dp[best_w] + 1e-12:
            best_w = w

    # Backtrack to recover pattern
    pattern = {}
    w = best_w
    for bi in range(nb - 1, -1, -1):
        if used[bi][w]:
            _, _, orig_i, count = bin_items[bi]
            pattern[orig_i] = pattern.get(orig_i, 0) + count
            w -= bin_items[bi][0]

    return dp[best_w], pattern


def column_generation(widths, demands, stock_width):
    """
    Solve LP relaxation of cutting stock via column generation.

    Returns (lp_bound, patterns_list).
    """
    n = len(widths)

    # Initialize with trivial single-item patterns
    patterns = []
    for i in range(n):
        if widths[i] <= stock_width:
            patterns.append({i: 1})

    max_iter = 500
    lp_val = None

    for iteration in range(max_iter):
        num_p = len(patterns)
        prob = LpProblem(f"master_{iteration}", LpMinimize)
        x = [LpVariable(f"x_{p}", lowBound=0) for p in range(num_p)]
        prob += lpSum(x)

        for i in range(n):
            prob += (
                lpSum(patterns[p].get(i, 0) * x[p] for p in range(num_p))
                >= demands[i],
                f"demand_{i}",
            )

        prob.solve(PULP_CBC_CMD(msg=0))

        if prob.status != 1:
            raise RuntimeError(f"Master LP infeasible at iteration {iteration}")

        lp_val = value(prob.objective)

        # Extract dual prices
        duals = []
        for i in range(n):
            pi = prob.constraints[f"demand_{i}"].pi
            duals.append(float(pi) if pi is not None else 0.0)

        # Solve pricing subproblem (bounded knapsack)
        ub = [min(demands[i], stock_width // widths[i]) for i in range(n)]
        max_profit, new_pattern = solve_bounded_knapsack(
            widths, duals, stock_width, ub
        )

        # Reduced cost of new column = 1 - max_profit
        if max_profit <= 1.0 + 1e-6:
            print(f"Column generation converged after {iteration + 1} iterations")
            break

        patterns.append(new_pattern)

    return lp_val, patterns


def solve_integer(patterns, demands, n):
    """Solve restricted master as integer program."""
    num_p = len(patterns)
    prob = LpProblem("master_ip", LpMinimize)
    x = [LpVariable(f"x_{p}", lowBound=0, cat=LpInteger) for p in range(num_p)]
    prob += lpSum(x)

    for i in range(n):
        prob += lpSum(patterns[p].get(i, 0) * x[p] for p in range(num_p)) >= demands[i]

    prob.solve(PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        raise RuntimeError("Integer master infeasible")

    ip_value = value(prob.objective)
    counts = [int(round(value(x[p]))) for p in range(num_p)]

    return int(ip_value), counts


def main():
    orders, stock_width, output_path = load_data()

    n = len(orders)
    widths = [o["width"] for o in orders]
    demands = [o["demand"] for o in orders]
    product_codes = [o["product_code"] for o in orders]

    print(f"Problem: {n} item types, stock width = {stock_width}mm")
    print(f"Volume lower bound: {sum(w * d for w, d in zip(widths, demands)) / stock_width:.2f}")

    # Phase 1: Column generation for LP bound
    lp_bound, patterns = column_generation(widths, demands, stock_width)
    print(f"LP relaxation bound: {lp_bound:.4f}")
    print(f"Patterns generated: {len(patterns)}")

    # Phase 2: Integer recovery
    total_rolls, pattern_counts = solve_integer(patterns, demands, n)
    print(f"Integer solution: {total_rolls} rolls")

    # Build output
    output_patterns = []
    total_waste = 0
    for p in range(len(patterns)):
        if pattern_counts[p] > 0:
            items = {}
            width_used = 0
            for i, count in patterns[p].items():
                items[product_codes[i]] = count
                width_used += widths[i] * count
            waste = stock_width - width_used
            total_waste += waste * pattern_counts[p]
            output_patterns.append(
                {
                    "items": items,
                    "width_used": width_used,
                    "rolls": pattern_counts[p],
                }
            )

    gap_pct = ((total_rolls - lp_bound) / lp_bound) * 100

    solution = {
        "patterns": output_patterns,
        "total_rolls": total_rolls,
        "lp_relaxation_bound": round(lp_bound, 4),
        "optimality_gap_pct": round(gap_pct, 4),
        "total_waste_mm": total_waste,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(solution, f, indent=2)

    print(f"\nSolution written to {output_path}")
    print(f"Total rolls:  {total_rolls}")
    print(f"LP bound:     {lp_bound:.4f}")
    print(f"Gap:          {gap_pct:.4f}%")
    print(f"Total waste:  {total_waste} mm")
    print(f"Patterns used: {len(output_patterns)}")


if __name__ == "__main__":
    main()
