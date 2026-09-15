#!/usr/bin/env python3
"""
Generalized Matrix Chain Optimizer — Reference Solution.

Uses dynamic programming with property-aware kernel selection,
solve-vs-inverse trade-offs, and property propagation.
"""

import json
import os

PROBLEMS_DIR = "/app/problems"
OUTPUT_DIR = "/app/output"

# -------------------------------------------------------------------------
# Property helpers
# -------------------------------------------------------------------------

def inverse_props(props):
    """Properties of inv(A) given properties of A."""
    return set(props)


def transpose_props(props):
    """Properties of A^T given properties of A."""
    result = set()
    for p in props:
        if p == "lower_triangular":
            result.add("upper_triangular")
        elif p == "upper_triangular":
            result.add("lower_triangular")
        else:
            result.add(p)
    return result


def multiply_props(left, right):
    """Properties of A @ B given property sets of A and B."""
    if "diagonal" in left and "diagonal" in right:
        return {"diagonal"}
    if "diagonal" in left:
        return set(right)
    if "diagonal" in right:
        return set(left)
    if "lower_triangular" in left and "lower_triangular" in right:
        return {"lower_triangular"}
    if "upper_triangular" in left and "upper_triangular" in right:
        return {"upper_triangular"}
    return {"general"}


def is_triangular(props):
    return "lower_triangular" in props or "upper_triangular" in props


# -------------------------------------------------------------------------
# Cost functions
# -------------------------------------------------------------------------

def cheapest_multiply(m, k, n, left_props, right_props):
    """Return (cost, kernel_name) for cheapest multiply of [m,k] x [k,n]."""
    options = [(2 * m * k * n, "GEMM")]
    if m == k and is_triangular(left_props):
        options.append((m * k * n, "TRMM"))
    if k == n and is_triangular(right_props):
        options.append((m * k * n, "TRMM"))
    if m == k and "diagonal" in left_props:
        options.append((m * n, "DIAGMM"))
    if k == n and "diagonal" in right_props:
        options.append((m * n, "DIAGMM"))
    return min(options, key=lambda x: x[0])


def cheapest_left_solve(m, n, a_props):
    """Cost to solve A*X = B where A is m×m, B is m×n. Return (cost, kernel)."""
    options = [((2 * m * m * m) // 3 + 2 * m * m * n, "GESV")]
    if is_triangular(a_props):
        options.append((m * m * n, "TRSM"))
    if "spd" in a_props:
        options.append(((m * m * m) // 3 + 2 * m * m * n, "POSV"))
    if "diagonal" in a_props:
        options.append((m * n, "DIAGSOLVE"))
    return min(options, key=lambda x: x[0])


def cheapest_right_solve(m, n, a_props):
    """Cost to solve X*A = B where A is n×n, B is m×n. Return (cost, kernel)."""
    options = [((2 * n * n * n) // 3 + 2 * m * n * n, "GESV_R")]
    if is_triangular(a_props):
        options.append((m * n * n, "TRSM_R"))
    if "spd" in a_props:
        options.append(((n * n * n) // 3 + 2 * m * n * n, "POSV_R"))
    if "diagonal" in a_props:
        options.append((m * n, "DIAGSOLVE_R"))
    return min(options, key=lambda x: x[0])


def explicit_inv_cost(m, props):
    """Cost to compute inv(A) where A is m×m. Return (cost, kernel)."""
    if "diagonal" in props:
        return (m, "DIAG_INV")
    if is_triangular(props):
        return ((m * m * m) // 3, "TRTRI")
    return (2 * m * m * m, "GETRI")


# -------------------------------------------------------------------------
# DP solver
# -------------------------------------------------------------------------

def solve_problem(problem):
    chain = problem["chain"]
    matrices = problem["matrices"]
    n = len(chain)

    # Pre-compute effective dims and props for each term
    terms = []
    for term in chain:
        mat = matrices[term["matrix"]]
        rows, cols = mat["rows"], mat["cols"]
        props = set(mat["properties"])
        if term.get("transpose", False):
            rows, cols = cols, rows
            props = transpose_props(props)
        terms.append({
            "name": term["matrix"],
            "dims": (rows, cols),
            "raw_props": set(mat["properties"]),  # original props for solve
            "eff_props": props,  # after transpose
            "inverted": term.get("invert", False),
            "transpose": term.get("transpose", False),
        })

    INF = float("inf")

    # DP tables
    dp_cost = [[INF] * n for _ in range(n)]
    dp_dims = [[(0, 0)] * n for _ in range(n)]
    dp_props = [[{"general"}] * n for _ in range(n)]
    # Choice info for reconstruction:
    # (split_k, combine_type, kernel, combine_cost)
    # combine_type: 'base', 'base_inv', 'multiply', 'left_solve', 'right_solve'
    dp_choice = [[None] * n for _ in range(n)]

    # Base cases
    for i in range(n):
        t = terms[i]
        if not t["inverted"]:
            dp_cost[i][i] = 0
            dp_dims[i][i] = t["dims"]
            dp_props[i][i] = t["eff_props"]
            dp_choice[i][i] = (-1, "base", None, 0)
        else:
            # Explicit inverse (may be overridden by solve in combine step)
            m = t["dims"][0]
            inv_c, inv_k = explicit_inv_cost(m, t["eff_props"])
            inv_p = inverse_props(t["eff_props"])
            dp_cost[i][i] = inv_c
            dp_dims[i][i] = t["dims"]
            dp_props[i][i] = inv_p
            dp_choice[i][i] = (-1, "base_inv", inv_k, inv_c)

    # Fill DP
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            for k in range(i, j):
                lc = dp_cost[i][k]
                rc = dp_cost[k + 1][j]
                l_dims = dp_dims[i][k]
                r_dims = dp_dims[k + 1][j]
                l_props = dp_props[i][k]
                r_props = dp_props[k + 1][j]

                # Option 1: Standard multiply
                mc, mk = cheapest_multiply(
                    l_dims[0], l_dims[1], r_dims[1], l_props, r_props
                )
                total = lc + rc + mc
                if total < dp_cost[i][j]:
                    dp_cost[i][j] = total
                    dp_dims[i][j] = (l_dims[0], r_dims[1])
                    dp_props[i][j] = multiply_props(l_props, r_props)
                    dp_choice[i][j] = (k, "multiply", mk, mc)

                # Option 2: Left-solve (left side is single inverted term)
                if k == i and terms[i]["inverted"]:
                    a_size = terms[i]["dims"][0]
                    a_props = terms[i]["eff_props"]
                    sc, sk = cheapest_left_solve(a_size, r_dims[1], a_props)
                    total_s = rc + sc  # skip explicit inverse cost
                    inv_p = inverse_props(a_props)
                    res_props = multiply_props(inv_p, r_props)
                    if total_s < dp_cost[i][j]:
                        dp_cost[i][j] = total_s
                        dp_dims[i][j] = (a_size, r_dims[1])
                        dp_props[i][j] = res_props
                        dp_choice[i][j] = (k, "left_solve", sk, sc)

                # Option 3: Right-solve (right side is single inverted term)
                if k + 1 == j and terms[j]["inverted"]:
                    a_size = terms[j]["dims"][0]
                    a_props = terms[j]["eff_props"]
                    sc, sk = cheapest_right_solve(l_dims[0], a_size, a_props)
                    total_s = lc + sc
                    inv_p = inverse_props(a_props)
                    res_props = multiply_props(l_props, inv_p)
                    if total_s < dp_cost[i][j]:
                        dp_cost[i][j] = total_s
                        dp_dims[i][j] = (l_dims[0], a_size)
                        dp_props[i][j] = res_props
                        dp_choice[i][j] = (k, "right_solve", sk, sc)

    # Reconstruct plan
    steps = []
    counter = [0]

    def next_name(i, j, n):
        if i == 0 and j == n - 1:
            return "RESULT"
        name = f"T{counter[0]}"
        counter[0] += 1
        return name

    def reconstruct(i, j):
        """Return the operand name for sub-chain [i..j]."""
        choice = dp_choice[i][j]
        if choice is None:
            raise ValueError(f"No solution for [{i},{j}]")

        split_k, ctype, kernel, cost = choice

        if ctype == "base":
            return terms[i]["name"]

        if ctype == "base_inv":
            out = next_name(i, j, n)
            steps.append({
                "kernel": kernel,
                "operands": [terms[i]["name"]],
                "output": out,
                "dims": list(dp_dims[i][i]),
                "flops": cost,
            })
            return out

        if ctype == "multiply":
            left_name = reconstruct(i, split_k)
            right_name = reconstruct(split_k + 1, j)
            out = next_name(i, j, n)
            steps.append({
                "kernel": kernel,
                "operands": [left_name, right_name],
                "output": out,
                "dims": list(dp_dims[i][j]),
                "flops": cost,
            })
            return out

        if ctype == "left_solve":
            # Left is single inverted term; don't reconstruct it
            right_name = reconstruct(split_k + 1, j)
            out = next_name(i, j, n)
            steps.append({
                "kernel": kernel,
                "operands": [terms[i]["name"], right_name],
                "output": out,
                "dims": list(dp_dims[i][j]),
                "flops": cost,
            })
            return out

        if ctype == "right_solve":
            left_name = reconstruct(i, split_k)
            # Right is single inverted term; don't reconstruct it
            out = next_name(i, j, n)
            steps.append({
                "kernel": kernel,
                "operands": [left_name, terms[j]["name"]],
                "output": out,
                "dims": list(dp_dims[i][j]),
                "flops": cost,
            })
            return out

        raise ValueError(f"Unknown combine type: {ctype}")

    reconstruct(0, n - 1)

    total_flops = sum(s["flops"] for s in steps)
    assert total_flops == dp_cost[0][n - 1], (
        f"Reconstruction mismatch: {total_flops} vs {dp_cost[0][n-1]}"
    )

    return {
        "problem_id": problem["id"],
        "total_flops": total_flops,
        "steps": steps,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for fname in sorted(os.listdir(PROBLEMS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(PROBLEMS_DIR, fname)
        with open(path) as f:
            problem = json.load(f)

        result = solve_problem(problem)
        out_path = os.path.join(OUTPUT_DIR, f"{problem['id']}.json")
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"{problem['id']}: {result['total_flops']} FLOPs "
              f"({len(result['steps'])} steps)")


if __name__ == "__main__":
    main()
