#!/usr/bin/env python3
"""Solver for the stock roll cutting optimization problem."""

import csv
import json
import math
import os

import numpy as np
from scipy.optimize import linprog
from pulp import (
    PULP_CBC_CMD,
    LpMinimize,
    LpProblem,
    LpVariable,
    lpSum,
    value,
)


def parse_data():
    """Parse stock specs and customer orders from /app/data/."""
    with open("/app/data/stock_specs.json") as f:
        specs = json.load(f)
    roll_width = specs["raw_material"]["roll_width_mm"]

    orders = []
    with open("/app/data/customer_orders.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            width = int(row["part_width_mm"])
            demand = int(row["quantity_needed"])
            orders.append({"width": width, "demand": demand})

    orders.sort(key=lambda x: x["width"])
    widths = [o["width"] for o in orders]
    demands = [o["demand"] for o in orders]
    return roll_width, widths, demands


def solve_knapsack(values, weights, capacity):
    """Unbounded integer knapsack via dynamic programming."""
    n = len(values)
    dp = [0.0] * (capacity + 1)
    choice = [-1] * (capacity + 1)

    for w in range(1, capacity + 1):
        for i in range(n):
            if weights[i] <= w:
                candidate = dp[w - weights[i]] + values[i]
                if candidate > dp[w] + 1e-12:
                    dp[w] = candidate
                    choice[w] = i

    pattern = [0] * n
    w = capacity
    while w > 0 and choice[w] >= 0:
        i = choice[w]
        pattern[i] += 1
        w -= weights[i]

    return dp[capacity], pattern


def generate_patterns(roll_width, widths, demands):
    """Iteratively generate cutting patterns via LP relaxation and pricing."""
    n = len(widths)

    # Initial patterns: single-item fills
    patterns = []
    for i in range(n):
        pat = [0] * n
        pat[i] = roll_width // widths[i]
        patterns.append(pat)

    iterations = 0
    lp_obj = None

    while True:
        iterations += 1
        m = len(patterns)

        # Solve LP: min 1'x s.t. Ax >= d, x >= 0
        # scipy form: min c'x s.t. A_ub x <= b_ub
        c_vec = np.ones(m)
        A_ub = np.zeros((n, m))
        for i in range(n):
            for j in range(m):
                A_ub[i, j] = -patterns[j][i]
        b_ub = np.array([-float(d) for d in demands])

        result = linprog(
            c_vec,
            A_ub=A_ub,
            b_ub=b_ub,
            bounds=[(0, None)] * m,
            method="highs",
        )
        if not result.success:
            raise RuntimeError(f"LP solve failed: {result.message}")

        lp_obj = float(result.fun)

        # Extract dual prices
        marginals = result.ineqlin.marginals
        duals = [-float(marginals[i]) for i in range(n)]

        # Pricing subproblem
        knap_val, new_pat = solve_knapsack(duals, widths, roll_width)

        if knap_val <= 1.0 + 1e-6:
            break  # no improving pattern
        if new_pat in patterns:
            break  # duplicate guard

        patterns.append(new_pat)

    return patterns, lp_obj, iterations


def solve_integer(patterns, roll_width, widths, demands):
    """Solve the integer problem over the generated pattern set."""
    n = len(widths)
    m = len(patterns)

    prob = LpProblem("CuttingStock_MIP", LpMinimize)
    x = [LpVariable(f"x{j}", lowBound=0, cat="Integer") for j in range(m)]

    prob += lpSum(x)

    for i in range(n):
        prob += (
            lpSum(patterns[j][i] * x[j] for j in range(m)) >= demands[i]
        )

    prob.solve(PULP_CBC_CMD(msg=0))

    int_obj = int(round(value(prob.objective)))
    quantities = [int(round(value(x[j]))) for j in range(m)]
    return int_obj, quantities


def main():
    roll_width, widths, demands = parse_data()
    n = len(widths)

    # Phase 1: generate patterns and compute lower bound
    patterns, lower_bound, iterations = generate_patterns(
        roll_width, widths, demands
    )

    # Phase 2: integer solution
    int_obj, quantities = solve_integer(
        patterns, roll_width, widths, demands
    )

    # Build output
    result_patterns = []
    for j in range(len(patterns)):
        if quantities[j] > 0:
            cuts = {}
            for i in range(n):
                if patterns[j][i] > 0:
                    cuts[str(widths[i])] = patterns[j][i]
            result_patterns.append({"cuts": cuts, "quantity": quantities[j]})

    total_area = sum(w * d for w, d in zip(widths, demands))
    total_waste = int_obj * roll_width - total_area

    solution = {
        "lower_bound": round(lower_bound, 6),
        "integer_objective": int_obj,
        "patterns": result_patterns,
        "total_waste": total_waste,
        "num_distinct_patterns": len(patterns),
        "optimization_iterations": iterations,
    }

    os.makedirs("/app/results", exist_ok=True)
    with open("/app/results/solution.json", "w") as f:
        json.dump(solution, f, indent=2)

    print(f"Lower bound:         {lower_bound:.4f}")
    print(f"Integer solution:    {int_obj}")
    print(f"Patterns explored:   {len(patterns)}")
    print(f"Iterations:          {iterations}")
    print(f"Total waste:         {total_waste}")


if __name__ == "__main__":
    main()
