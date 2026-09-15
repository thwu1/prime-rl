#!/usr/bin/env python3

"""
Cutting stock solver using Dantzig-Wolfe column generation.

Algorithm:
  1. Initialize with trivial single-item patterns.
  2. Solve master LP relaxation to obtain dual prices.
  3. Solve knapsack pricing subproblem to find pattern with min reduced cost.
  4. If reduced cost < 0, add column and repeat from step 2.
  5. Record LP relaxation bound.
  6. Solve restricted MIP with all generated columns.
  7. Output results.
"""

import json
import math
from pulp import (
    LpProblem, LpMinimize, LpMaximize, LpVariable,
    lpSum, value, PULP_CBC_CMD, LpStatusOptimal
)


def solve():
    # Load problem data
    with open('/app/data/problem.json') as f:
        data = json.load(f)

    stock_width = data['stock_width']
    items = data['items']
    n = len(items)
    widths = [item['width'] for item in items]
    demands = [item['demand'] for item in items]

    # Phase 1: Initialize with basic (trivial) patterns
    # Each initial pattern fills a roll with as many copies of one item as possible
    patterns = []  # list of lists: patterns[j][i] = count of item i in pattern j
    for i in range(n):
        max_fit = stock_width // widths[i]
        if max_fit > 0:
            pat = [0] * n
            pat[i] = max_fit
            patterns.append(pat)

    # Phase 2: Column generation loop
    lp_obj = None
    max_iterations = 1000
    for iteration in range(max_iterations):
        # Build and solve master LP relaxation
        master = LpProblem("CuttingStock_Master", LpMinimize)
        x = [LpVariable(f"x_{j}", lowBound=0) for j in range(len(patterns))]

        # Objective: minimize total rolls
        master += lpSum(x)

        # Demand constraints: for each item, total production >= demand
        demand_cstrs = []
        for i in range(n):
            cstr = lpSum(patterns[j][i] * x[j] for j in range(len(patterns))) >= demands[i]
            master += cstr
            demand_cstrs.append(cstr)

        master.solve(PULP_CBC_CMD(msg=0))

        if master.status != LpStatusOptimal:
            raise RuntimeError(f"Master LP not optimal at iteration {iteration}")

        lp_obj = value(master.objective)

        # Extract dual variables (shadow prices)
        duals = []
        for i in range(n):
            pi_val = demand_cstrs[i].pi
            if pi_val is None:
                pi_val = 0.0
            duals.append(pi_val)

        # Phase 2b: Solve pricing subproblem (bounded knapsack)
        # Maximize sum_i(dual_i * y_i) subject to sum_i(width_i * y_i) <= stock_width
        # Reduced cost of new column = 1 - knapsack_value
        # If knapsack_value > 1 + eps, the new column improves the LP
        knapsack = LpProblem("Knapsack_Pricing", LpMaximize)
        y = []
        for i in range(n):
            ub = stock_width // widths[i]
            yi = LpVariable(f"y_{i}", lowBound=0, upBound=ub, cat='Integer')
            y.append(yi)

        knapsack += lpSum(duals[i] * y[i] for i in range(n))
        knapsack += lpSum(widths[i] * y[i] for i in range(n)) <= stock_width

        knapsack.solve(PULP_CBC_CMD(msg=0))

        if knapsack.status != LpStatusOptimal:
            break

        knap_obj = value(knapsack.objective)

        # Check reduced cost: 1 - knap_obj
        if knap_obj <= 1.0 + 1e-6:
            # No improving column found — column generation complete
            break

        # Extract new pattern and add to the pool
        new_pat = [int(round(value(y[i]))) for i in range(n)]

        # Verify the pattern is valid and non-trivial
        total_width = sum(widths[i] * new_pat[i] for i in range(n))
        if total_width > stock_width:
            break  # numerical issue
        if all(c == 0 for c in new_pat):
            break

        patterns.append(new_pat)

    lp_bound = lp_obj if lp_obj is not None else 0.0

    # Phase 3: Solve final MIP with all generated columns
    mip = LpProblem("CuttingStock_MIP", LpMinimize)
    x_int = [LpVariable(f"x_{j}", lowBound=0, cat='Integer')
             for j in range(len(patterns))]

    mip += lpSum(x_int)

    for i in range(n):
        mip += lpSum(patterns[j][i] * x_int[j]
                     for j in range(len(patterns))) >= demands[i]

    mip.solve(PULP_CBC_CMD(msg=0))

    if mip.status != LpStatusOptimal:
        raise RuntimeError("MIP not optimal")

    total_rolls = int(round(value(mip.objective)))

    # Collect active patterns
    result_patterns = []
    for j in range(len(patterns)):
        count = int(round(value(x_int[j])))
        if count > 0:
            cuts = {}
            for i in range(n):
                if patterns[j][i] > 0:
                    cuts[str(widths[i])] = patterns[j][i]
            result_patterns.append({
                "cuts": cuts,
                "count": count
            })

    results = {
        "total_rolls": total_rolls,
        "lp_bound": round(lp_bound, 6),
        "patterns": result_patterns
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Column generation converged after generating {len(patterns)} patterns")
    print(f"LP relaxation bound: {lp_bound:.4f}")
    print(f"Integer solution:    {total_rolls} rolls")
    print(f"Integrality gap:     {total_rolls - lp_bound:.4f}")
    print(f"Active patterns:     {len(result_patterns)}")


if __name__ == '__main__':
    solve()
