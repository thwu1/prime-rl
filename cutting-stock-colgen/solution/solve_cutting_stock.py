"""
Solve the production planning recovery problem.


Phase 1: Data gathering
  - Parse stock_specs.toml for active material width
  - Aggregate orders from batch CSV files
  - Subtract canceled orders
  - Subtract prior production run fulfillments from crash log

Phase 2: Optimization
  - Gilmore-Gomory column generation (LP master + knapsack pricing)
  - Pattern pool augmentation for integrality gap closure
  - Final integer program solve
"""

import csv
import json
import math
import os
import re
import sys
import tomllib
from collections import defaultdict
from pulp import (
    LpProblem, LpMinimize, LpMaximize, LpVariable, lpSum, value, PULP_CBC_CMD,
)


# ── Phase 1: Data Gathering ─────────────────────────────────────────────────


def find_stock_width():
    """Parse stock_specs.toml and return the width of the active material."""
    toml_path = "/app/materials/stock_specs.toml"
    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    for name, spec in config["material"].items():
        if spec.get("status") == "active":
            width = spec["width_mm"]
            print(f"Active material: {name}, width={width}mm", file=sys.stderr)
            return width

    raise ValueError("No active material found in stock_specs.toml")


def aggregate_orders():
    """Read all batch CSV files under /app/orders/ and aggregate by width."""
    orders_dir = "/app/orders"
    demand = defaultdict(int)

    for fname in sorted(os.listdir(orders_dir)):
        fpath = os.path.join(orders_dir, fname)
        if not os.path.isfile(fpath):
            continue
        if not fname.startswith("batch_") or not fname.endswith(".csv"):
            continue

        with open(fpath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                w = int(row["width_mm"])
                q = int(row["quantity"])
                demand[w] += q

        print(f"  Loaded orders from {fname}", file=sys.stderr)

    print(f"Total ordered widths: {len(demand)}", file=sys.stderr)
    return demand


def subtract_cancellations(demand):
    """Read canceled.csv and subtract from demand."""
    cancel_path = "/app/orders/canceled.csv"
    if not os.path.exists(cancel_path):
        return demand

    with open(cancel_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            w = int(row["width_mm"])
            q = int(row["quantity"])
            demand[w] -= q

    print("Subtracted cancellations", file=sys.stderr)
    return demand


def subtract_prior_fulfillments(demand):
    """Parse prior_run.log for the partial fulfillment summary."""
    log_path = "/app/production/prior_run.log"
    if not os.path.exists(log_path):
        return demand

    with open(log_path) as f:
        content = f.read()

    # Find the PARTIAL FULFILLMENT SUMMARY section
    summary_match = re.search(
        r"PARTIAL FULFILLMENT SUMMARY.*?END LOG",
        content,
        re.DOTALL,
    )
    if not summary_match:
        print("WARNING: No fulfillment summary found in prior_run.log", file=sys.stderr)
        return demand

    summary = summary_match.group()
    # Parse lines like "  2200mm: 4 units"
    for match in re.finditer(r"(\d+)mm:\s*(\d+)\s*unit", summary):
        w = int(match.group(1))
        q = int(match.group(2))
        demand[w] -= q

    print("Subtracted prior run fulfillments", file=sys.stderr)
    return demand


def gather_problem_data():
    """Gather and reconcile all data to produce the final problem instance."""
    stock_width = find_stock_width()

    print("Aggregating orders...", file=sys.stderr)
    demand = aggregate_orders()

    print("Applying cancellations...", file=sys.stderr)
    demand = subtract_cancellations(demand)

    print("Applying prior fulfillments...", file=sys.stderr)
    demand = subtract_prior_fulfillments(demand)

    # Sort by decreasing width and build items list
    widths_sorted = sorted(demand.keys(), reverse=True)
    items = []
    for w in widths_sorted:
        d = demand[w]
        if d > 0:
            items.append({"width": w, "demand": d})

    print(f"\nFinal problem: stock_width={stock_width}, {len(items)} items", file=sys.stderr)
    for it in items:
        print(f"  width={it['width']}mm, demand={it['demand']}", file=sys.stderr)

    return stock_width, items


# ── Phase 2: Column Generation ───────────────────────────────────────────────


def column_generation(stock_width, items):
    """Run Gilmore-Gomory column generation to solve the LP relaxation."""
    n = len(items)
    widths = [it["width"] for it in items]
    demands = [it["demand"] for it in items]
    max_per_stock = [stock_width // widths[i] for i in range(n)]

    # Initialize with trivial patterns (one item type fills the roll)
    patterns = set()
    for i in range(n):
        pat = [0] * n
        pat[i] = max_per_stock[i]
        patterns.add(tuple(pat))

    # Add greedy heuristic patterns using different item orderings
    for start_idx in range(n):
        pat = [0] * n
        remaining = stock_width
        order = sorted(range(n), key=lambda i: -widths[i])
        try:
            pos = order.index(start_idx)
            order = order[pos:] + order[:pos]
        except ValueError:
            pass
        for i in order:
            count = remaining // widths[i]
            if count > 0:
                pat[i] = count
                remaining -= count * widths[i]
        if sum(pat) > 0:
            patterns.add(tuple(pat))

    # Also add some mixed greedy patterns
    for i in range(n):
        for j in range(i + 1, n):
            pat = [0] * n
            remaining = stock_width
            pat[i] = remaining // widths[i]
            remaining -= pat[i] * widths[i]
            pat[j] = remaining // widths[j]
            remaining -= pat[j] * widths[j]
            for k in range(n):
                if k != i and k != j:
                    add = remaining // widths[k]
                    if add > 0:
                        pat[k] = add
                        remaining -= add * widths[k]
            if sum(pat) > 0:
                patterns.add(tuple(pat))

    patterns = [list(p) for p in patterns]

    # Column generation loop
    lp_obj = None
    for iteration in range(1000):
        master = LpProblem("CuttingStock_Master", LpMinimize)
        x = [LpVariable(f"x_{j}", lowBound=0) for j in range(len(patterns))]
        master += lpSum(x)

        demand_cstrs = []
        for i in range(n):
            c = (
                lpSum(patterns[j][i] * x[j] for j in range(len(patterns)))
                >= demands[i]
            )
            master += c
            demand_cstrs.append(c)

        master.solve(PULP_CBC_CMD(msg=0))
        if master.status != 1:
            print(f"Master problem failed at iteration {iteration}", file=sys.stderr)
            break

        lp_obj = value(master.objective)
        duals = []
        for c in demand_cstrs:
            duals.append(c.pi if c.pi is not None else 0.0)

        # Pricing subproblem: integer knapsack
        knapsack = LpProblem("Knapsack", LpMaximize)
        y = [
            LpVariable(f"y_{i}", lowBound=0, upBound=max_per_stock[i], cat="Integer")
            for i in range(n)
        ]
        knapsack += lpSum(duals[i] * y[i] for i in range(n))
        knapsack += lpSum(widths[i] * y[i] for i in range(n)) <= stock_width
        knapsack.solve(PULP_CBC_CMD(msg=0))

        reduced_cost = value(knapsack.objective) - 1.0
        if reduced_cost <= 1e-6:
            print(
                f"Column generation converged at iteration {iteration}, "
                f"LP optimal = {lp_obj:.6f}",
                file=sys.stderr,
            )
            break

        new_pat = [int(round(value(y[i]))) for i in range(n)]
        if new_pat not in patterns:
            patterns.append(new_pat)
        else:
            print(f"Duplicate column at iteration {iteration}, stopping", file=sys.stderr)
            break

    return patterns, lp_obj


def augment_patterns(stock_width, items, base_patterns):
    """Add diverse heuristic patterns to the pool for better IP solutions."""
    n = len(items)
    widths = [it["width"] for it in items]
    max_per_stock = [stock_width // widths[i] for i in range(n)]

    pattern_set = set(tuple(p) for p in base_patterns)

    # Strategy 1: for each pair (i, j), try all feasible combinations
    for i in range(n):
        for ci in range(1, max_per_stock[i] + 1):
            if ci * widths[i] > stock_width:
                break
            for j in range(n):
                if j == i:
                    continue
                remaining_after_i = stock_width - ci * widths[i]
                cj = remaining_after_i // widths[j]
                if cj == 0:
                    continue
                for actual_cj in range(1, cj + 1):
                    pat = [0] * n
                    pat[i] = ci
                    pat[j] = actual_cj
                    remaining = stock_width - ci * widths[i] - actual_cj * widths[j]
                    for k in range(n):
                        if k != i and k != j and remaining >= widths[k]:
                            add = remaining // widths[k]
                            pat[k] = add
                            remaining -= add * widths[k]
                    if sum(pat) > 0:
                        pattern_set.add(tuple(pat))

    # Strategy 2: triples among the 6 largest items
    large_items = sorted(range(n), key=lambda i: -widths[i])[:6]
    for i in large_items:
        for ci in range(1, min(4, max_per_stock[i] + 1)):
            if ci * widths[i] > stock_width:
                break
            for j in large_items:
                if j <= i:
                    continue
                for cj in range(1, min(4, max_per_stock[j] + 1)):
                    used = ci * widths[i] + cj * widths[j]
                    if used > stock_width:
                        break
                    for k in large_items:
                        if k <= j:
                            continue
                        remaining = stock_width - used
                        ck = min(remaining // widths[k], 3)
                        if ck == 0:
                            continue
                        for actual_ck in range(1, ck + 1):
                            pat = [0] * n
                            pat[i] = ci
                            pat[j] = cj
                            pat[k] = actual_ck
                            rem = stock_width - used - actual_ck * widths[k]
                            for m in range(n):
                                if m not in (i, j, k) and rem >= widths[m]:
                                    add = rem // widths[m]
                                    pat[m] = add
                                    rem -= add * widths[m]
                            pattern_set.add(tuple(pat))

    # Filter out infeasible patterns
    valid = []
    for pat in pattern_set:
        total = sum(pat[i] * widths[i] for i in range(n))
        if total <= stock_width and sum(pat) > 0:
            valid.append(list(pat))

    print(f"Augmented pattern pool: {len(valid)} patterns", file=sys.stderr)
    return valid


def solve_ip(stock_width, items, patterns):
    """Solve the integer cutting stock problem given a set of patterns."""
    n = len(items)
    demands = [it["demand"] for it in items]

    ip = LpProblem("CuttingStock_IP", LpMinimize)
    x = [LpVariable(f"x_{j}", lowBound=0, cat="Integer") for j in range(len(patterns))]
    ip += lpSum(x)

    for i in range(n):
        ip += lpSum(patterns[j][i] * x[j] for j in range(len(patterns))) >= demands[i]

    ip.solve(PULP_CBC_CMD(msg=0, timeLimit=120))
    ip_obj = int(round(value(ip.objective)))

    solution_patterns = []
    for j in range(len(patterns)):
        val = int(round(value(x[j])))
        if val > 0:
            solution_patterns.append({"pattern": patterns[j], "count": val})

    return ip_obj, solution_patterns


def verify_solution(stock_width, items, objective, solution_patterns):
    """Verify feasibility of the solution."""
    n = len(items)
    widths = [it["width"] for it in items]
    demands = [it["demand"] for it in items]

    total_rolls = sum(sp["count"] for sp in solution_patterns)
    assert total_rolls == objective, f"Objective mismatch: {total_rolls} != {objective}"

    for sp in solution_patterns:
        pat = sp["pattern"]
        total_width = sum(pat[i] * widths[i] for i in range(n))
        assert total_width <= stock_width, f"Pattern {pat} exceeds stock width"

    produced = [0] * n
    for sp in solution_patterns:
        for i in range(n):
            produced[i] += sp["pattern"][i] * sp["count"]

    for i in range(n):
        assert produced[i] >= demands[i], (
            f"Item {i}: produced {produced[i]} < demand {demands[i]}"
        )

    print(f"Solution verified: {objective} rolls, all demands met", file=sys.stderr)


def main():
    output_path = "/app/output/solution.json"

    # Phase 1: Gather and reconcile data
    print("=== Phase 1: Data Gathering ===", file=sys.stderr)
    stock_width, items = gather_problem_data()

    n = len(items)
    total_area = sum(it["width"] * it["demand"] for it in items)
    area_lb = math.ceil(total_area / stock_width)
    print(f"\nArea lower bound: {area_lb} rolls", file=sys.stderr)

    # Phase 2: Column generation
    print("\n=== Phase 2: Column Generation ===", file=sys.stderr)
    cg_patterns, lp_obj = column_generation(stock_width, items)
    lp_ceiling = math.ceil(lp_obj - 1e-6)
    print(f"LP ceiling: {lp_ceiling}", file=sys.stderr)

    # Phase 3: Solve IP with CG patterns
    print("\n=== Phase 3: Integer Program ===", file=sys.stderr)
    ip_obj, sol = solve_ip(stock_width, items, cg_patterns)
    print(f"IP with CG patterns: {ip_obj} rolls", file=sys.stderr)

    # Phase 4: If not at LP ceiling, augment patterns and re-solve
    if ip_obj > lp_ceiling:
        print("\nAugmenting pattern pool...", file=sys.stderr)
        augmented = augment_patterns(stock_width, items, cg_patterns)
        ip_obj, sol = solve_ip(stock_width, items, augmented)
        print(f"IP with augmented patterns: {ip_obj} rolls", file=sys.stderr)

    # Verify and write output
    verify_solution(stock_width, items, ip_obj, sol)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result = {"objective": ip_obj, "patterns": sol}
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nSolution written to {output_path}", file=sys.stderr)
    print(f"Final answer: {ip_obj} rolls", file=sys.stderr)


if __name__ == "__main__":
    main()
