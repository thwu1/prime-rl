#!/usr/bin/env python3
"""Solution: Query SQLite benchmarks DB to infer cost model, resolve
transposed operands, run property-aware matrix chain DP optimizer."""


import json
import os
import sqlite3
from collections import defaultdict

DB_PATH = "/app/input/benchmarks.db"
CHAINS_PATH = "/app/input/chains.json"
OUTPUT_PATH = "/app/output/plans.json"


# ---- Database queries ----

def load_propagation_rules():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT left_prop, right_prop, result_prop FROM propagation_rules")
    rules = {(lp, rp): res for lp, rp, res in c.fetchall()}
    conn.close()
    return rules


def load_transpose_map():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT original_prop, transposed_prop FROM transpose_properties")
    tmap = {orig: trans for orig, trans in c.fetchall()}
    conn.close()
    return tmap


def infer_cost_model():
    """Analyze empirical benchmark data to discover cost formulas."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT left_prop, right_prop, m, k, n, measured_cost "
              "FROM cost_measurements")
    rows = c.fetchall()
    conn.close()

    groups = defaultdict(list)
    for lp, rp, m, k, n, cost in rows:
        groups[(lp, rp)].append((m, k, n, cost))

    # For each (left_prop, right_prop) group, determine the cost formula
    # by testing candidate formulas: k, m*n, m*n*k, 2*m*n*k
    formulas = {}
    for (lp, rp), data in groups.items():
        # Test cost = k
        if all(cost == k for m, k, n, cost in data):
            formulas[(lp, rp)] = "k"
            continue
        # Test cost = m*n
        if all(m * n != 0 and cost == m * n for m, k, n, cost in data):
            formulas[(lp, rp)] = "mn"
            continue
        # Test cost = m*n*k
        if all(m * n * k != 0 and cost == m * n * k for m, k, n, cost in data):
            formulas[(lp, rp)] = "mnk"
            continue
        # Test cost = 2*m*n*k
        if all(m * n * k != 0 and cost == 2 * m * n * k
               for m, k, n, cost in data):
            formulas[(lp, rp)] = "2mnk"
            continue

    # Build hierarchical cost function from discovered patterns
    structured = {"symmetric", "upper_triangular", "lower_triangular"}

    def cost_fn(left_prop, right_prop, m, k, n):
        key = (left_prop, right_prop)
        if key in formulas:
            f = formulas[key]
            if f == "k":
                return k
            elif f == "mn":
                return m * n
            elif f == "mnk":
                return m * n * k
            elif f == "2mnk":
                return 2 * m * n * k
        # Fallback for unseen combinations — use hierarchy
        if left_prop == "diagonal" and right_prop == "diagonal":
            return k
        if left_prop == "diagonal":
            return m * n
        if right_prop == "diagonal":
            return m * n
        if left_prop in structured or right_prop in structured:
            return m * n * k
        return 2 * m * n * k

    return cost_fn


# ---- Transpose resolution ----

def resolve_operands(chain, trans_map):
    """Convert chain operands to effective dimensions and properties,
    applying transpose transformations where specified."""
    effective = []
    for op in chain["operands"]:
        mat = chain["matrices"][op["matrix"]]
        if op.get("transpose", False):
            rows, cols = mat["cols"], mat["rows"]
            prop = trans_map.get(mat["property"], mat["property"])
        else:
            rows, cols = mat["rows"], mat["cols"]
            prop = mat["property"]
        effective.append({
            "name": op["matrix"],
            "rows": rows,
            "cols": cols,
            "property": prop,
        })
    return effective


# ---- Generalized Matrix Chain DP ----

def optimize_chain(matrices, cost_fn, prop_rules):
    n = len(matrices)
    if n == 1:
        return {"steps": [], "total_cost": 0}

    INF = float("inf")
    # dp[i][j] maps result_property -> (cost, split_k, left_prop, right_prop)
    dp = [[{} for _ in range(n)] for _ in range(n)]

    for i in range(n):
        dp[i][i] = {matrices[i]["property"]: (0, -1, None, None)}

    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            for k in range(i, j):
                for lp, (lc, _, _, _) in dp[i][k].items():
                    for rp, (rc, _, _, _) in dp[k + 1][j].items():
                        m = matrices[i]["rows"]
                        inner = matrices[k]["cols"]
                        n_dim = matrices[j]["cols"]
                        combine = cost_fn(lp, rp, m, inner, n_dim)
                        total = lc + rc + combine
                        result_prop = prop_rules.get((lp, rp), "general")
                        if (result_prop not in dp[i][j] or
                                total < dp[i][j][result_prop][0]):
                            dp[i][j][result_prop] = (total, k, lp, rp)

    best_cost = INF
    best_prop = None
    for prop, (cost, _, _, _) in dp[0][n - 1].items():
        if cost < best_cost:
            best_cost = cost
            best_prop = prop

    steps = []
    counter = [0]

    def reconstruct(i, j, target_prop):
        if i == j:
            return matrices[i]["name"], matrices[i]["property"]
        _, k, lp_used, rp_used = dp[i][j][target_prop]
        left_name, left_actual = reconstruct(i, k, lp_used)
        right_name, right_actual = reconstruct(k + 1, j, rp_used)
        m = matrices[i]["rows"]
        inner = matrices[k]["cols"]
        n_dim = matrices[j]["cols"]
        step_cost = cost_fn(left_actual, right_actual, m, inner, n_dim)
        result_prop = prop_rules.get((left_actual, right_actual), "general")
        result_name = f"T{counter[0]}"
        counter[0] += 1
        steps.append({
            "left": left_name,
            "right": right_name,
            "result": result_name,
            "result_properties": [result_prop],
            "cost": step_cost,
        })
        return result_name, result_prop

    reconstruct(0, n - 1, best_prop)
    return {"steps": steps, "total_cost": best_cost}


# ---- Main ----

def main():
    prop_rules = load_propagation_rules()
    trans_map = load_transpose_map()
    cost_fn = infer_cost_model()

    with open(CHAINS_PATH) as f:
        data = json.load(f)

    plans = {}
    for chain_id, chain in data["chains"].items():
        effective = resolve_operands(chain, trans_map)
        plans[chain_id] = optimize_chain(effective, cost_fn, prop_rules)

    os.makedirs("/app/output", exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({"plans": plans}, f, indent=2)

    for chain_id, plan in plans.items():
        print(f"  {chain_id}: total_cost = {plan['total_cost']}")


if __name__ == "__main__":
    main()
