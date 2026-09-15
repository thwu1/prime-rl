
"""
Column generation solver for multi-stock-type 1D cutting stock problem.

Approach:
  1. Initialize with trivial single-item patterns for each stock type.
  2. Solve the restricted master problem (LP relaxation) with PuLP/CBC.
  3. Extract dual values (shadow prices) from demand constraints.
  4. For each stock type, solve a bounded knapsack pricing subproblem
     via dynamic programming to find the pattern with the most negative
     reduced cost.
  5. If no pattern has negative reduced cost, the LP is optimal. Stop.
  6. Otherwise add the new pattern to the master and go to step 2.
  7. After LP convergence, solve the integer master problem using all
     columns generated during CG to obtain the optimal integer solution.
"""

import json
from pulp import (
    LpProblem, LpMinimize, LpVariable, lpSum, value, PULP_CBC_CMD
)


def solve_knapsack_dp(capacity, weights, profits):
    """
    Solve unbounded knapsack via dynamic programming.

    Each item can be used multiple times (up to capacity // weight).
    Returns (max_profit, item_counts_list).
    """
    n = len(weights)
    dp = [0.0] * (capacity + 1)
    last_item = [-1] * (capacity + 1)

    for w in range(1, capacity + 1):
        for i in range(n):
            if weights[i] <= w:
                candidate = dp[w - weights[i]] + profits[i]
                if candidate > dp[w] + 1e-10:
                    dp[w] = candidate
                    last_item[w] = i

    # Reconstruct item counts
    counts = [0] * n
    w = capacity
    while w > 0 and last_item[w] >= 0:
        i = last_item[w]
        counts[i] += 1
        w -= weights[i]

    return dp[capacity], counts


def main():
    with open('/app/instance.json') as f:
        instance = json.load(f)

    stock_types = instance['stock_types']
    items = instance['items']
    n_items = len(items)
    widths = [item['width'] for item in items]
    demands = [item['demand'] for item in items]

    # Initialize with trivial patterns: for each stock type, create a
    # pattern that cuts only one item type (as many as fit).
    patterns = []  # list of (stock_type_idx, [a0, a1, ..., a_{n-1}])

    for s_idx, stock in enumerate(stock_types):
        W = stock['width']
        for i in range(n_items):
            if widths[i] <= W:
                pat = [0] * n_items
                pat[i] = W // widths[i]
                patterns.append((s_idx, pat))

    # Column generation loop
    MAX_ITER = 500
    lp_bound = None

    for iteration in range(MAX_ITER):
        # Build and solve the Restricted Master Problem (LP relaxation)
        prob = LpProblem("RMP", LpMinimize)
        x = [LpVariable(f"x_{j}", lowBound=0) for j in range(len(patterns))]

        # Objective: minimize total stock cost
        prob += lpSum(
            stock_types[patterns[j][0]]['cost'] * x[j]
            for j in range(len(patterns))
        )

        # Demand satisfaction constraints (>=)
        for i in range(n_items):
            prob += (
                lpSum(
                    patterns[j][1][i] * x[j]
                    for j in range(len(patterns))
                ) >= demands[i],
                f"demand_{i}"
            )

        prob.solve(PULP_CBC_CMD(msg=0))

        if prob.status != 1:
            raise RuntimeError(
                f"RMP infeasible or unbounded at iteration {iteration}"
            )

        lp_bound = value(prob.objective)

        # Extract dual values (shadow prices) from demand constraints
        duals = []
        for i in range(n_items):
            constr = prob.constraints[f"demand_{i}"]
            pi = constr.pi
            duals.append(pi if pi is not None else 0.0)

        # Pricing subproblem for each stock type:
        # Find pattern maximizing sum_i pi_i * a_i subject to
        # sum_i w_i * a_i <= W.
        # Reduced cost = stock_cost - max_profit.
        # If reduced cost < 0, we have an improving column.
        best_rc = -1e-6
        best_pattern = None
        best_stock = None

        for s_idx, stock in enumerate(stock_types):
            W = stock['width']
            cost = stock['cost']

            max_profit, best_items = solve_knapsack_dp(W, widths, duals)
            rc = cost - max_profit

            if rc < best_rc:
                best_rc = rc
                best_pattern = best_items
                best_stock = s_idx

        if best_pattern is None:
            # No improving column; LP relaxation is optimal
            break

        patterns.append((best_stock, best_pattern))

    print(f"LP bound: {lp_bound:.6f}")
    print(f"Columns generated: {len(patterns)}")
    print(f"CG iterations: {iteration + 1}")

    # Solve the Integer Master Problem using all generated columns
    prob_ip = LpProblem("IP", LpMinimize)
    x_ip = [
        LpVariable(f"x_{j}", lowBound=0, cat='Integer')
        for j in range(len(patterns))
    ]

    prob_ip += lpSum(
        stock_types[patterns[j][0]]['cost'] * x_ip[j]
        for j in range(len(patterns))
    )

    for i in range(n_items):
        prob_ip += (
            lpSum(
                patterns[j][1][i] * x_ip[j]
                for j in range(len(patterns))
            ) >= demands[i]
        )

    prob_ip.solve(PULP_CBC_CMD(msg=0))

    total_cost = int(round(value(prob_ip.objective)))

    # Collect used patterns
    solution_patterns = []
    for j in range(len(patterns)):
        cnt = int(round(value(x_ip[j])))
        if cnt > 0:
            solution_patterns.append({
                "stock_type": patterns[j][0],
                "cuts": patterns[j][1],
                "count": cnt
            })

    results = {
        "lp_bound": round(lp_bound, 6),
        "total_cost": total_cost,
        "patterns": solution_patterns
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Total cost: {total_cost}")
    print(f"Active patterns: {len(solution_patterns)}")
    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
