#!/usr/bin/env python3
"""
Parallel Cost Model Solver.

Reads algorithm definitions and query specs from extracted JSON files
(produced by sqlite3), computes exact answers, outputs JSON array for
jq assembly.

"""

import json
import math
import sys


def eval_expr(expr, val):
    ns = {"n": val, "m": val, "log2": math.log2, "__builtins__": {}}
    return int(eval(expr, ns))


def evaluate_algorithm(algo, n):
    k = int(round(math.log2(n)))
    assert 2 ** k == n
    w = algo["base_work"]
    s = algo["base_span"]
    for i in range(1, k + 1):
        size = 2 ** i
        w = algo["work_bf"] * w + eval_expr(algo["work_combine"], size)
        s = algo["span_cpb"] * s + eval_expr(algo["span_combine"], size)
    return w, s


def ceil_div(a, b):
    return -(-a // b)


def evaluate_hybrid(algo, n, threshold, seq_formula):
    k = int(round(math.log2(n)))
    t = int(round(math.log2(threshold))) if threshold > 1 else 0
    if threshold <= 1:
        sw, ss = algo["base_work"], algo["base_span"]
    else:
        sw = eval_expr(seq_formula, threshold)
        ss = sw
    w, s = sw, ss
    for i in range(t + 1, k + 1):
        size = 2 ** i
        w = algo["work_bf"] * w + eval_expr(algo["work_combine"], size)
        s = algo["span_cpb"] * s + eval_expr(algo["span_combine"], size)
    return w, s


def solve_evaluate(algos, params):
    algo = algos[params["algorithm"]]
    w, s = evaluate_algorithm(algo, params["n"])
    return {"work": w, "span": s}


def solve_brent(algos, params):
    algo = algos[params["algorithm"]]
    w, s = evaluate_algorithm(algo, params["n"])
    return {"T_P": ceil_div(w, params["processors"]) + s}


def solve_composition(algos, params):
    tw, ts = 0, 0
    for name in params["pipeline"]:
        w, s = evaluate_algorithm(algos[name], params["n"])
        tw += w
        ts += s
    return {"work": tw, "span": ts}


def solve_crossover(algos, params):
    a1, a2 = params["algorithms"]
    for k in range(1, 64):
        n = 2 ** k
        w1, _ = evaluate_algorithm(algos[a1], n)
        w2, _ = evaluate_algorithm(algos[a2], n)
        if w2 < w1:
            return {"n": n}
    raise ValueError("No crossover found")


def solve_optimal_processors(algos, params):
    algo = algos[params["algorithm"]]
    w, s = evaluate_algorithm(algo, params["n"])
    target = params["overhead_factor"] * s
    p = math.ceil(w / (target - s))
    return {"processors": p}


def solve_min_parallelism_n(algos, params):
    algo = algos[params["algorithm"]]
    target = params["min_parallelism"]
    for k in range(1, 64):
        n = 2 ** k
        w, s = evaluate_algorithm(algo, n)
        if s > 0 and w / s > target:
            return {"n": n}
    raise ValueError("No n found")


def solve_granularity(algos, params):
    algo = algos[params["algorithm"]]
    n = params["n"]
    P = params["processors"]
    seq_formula = params["sequential_base"]["work_formula"]
    k = int(math.log2(n))
    best_tp, best_t = float("inf"), 1
    for t in range(0, k + 1):
        threshold = 2 ** t
        w, s = evaluate_hybrid(algo, n, threshold, seq_formula)
        tp = ceil_div(w, P) + s
        if tp < best_tp:
            best_tp = tp
            best_t = threshold
    return {"threshold": best_t, "T_P": best_tp}


def solve_composition_brent(algos, params):
    tw, ts = 0, 0
    for name in params["pipeline"]:
        w, s = evaluate_algorithm(algos[name], params["n"])
        tw += w
        ts += s
    return {"T_P": ceil_div(tw, params["processors"]) + ts}


def solve_pipeline_granularity(algos, params):
    n = params["n"]
    P = params["processors"]
    opt_stage = params["optimize_stage"]
    seq_formula = params["sequential_base"]["work_formula"]

    fixed_w, fixed_s = 0, 0
    for name in params["pipeline"]:
        if name != opt_stage:
            w, s = evaluate_algorithm(algos[name], n)
            fixed_w += w
            fixed_s += s

    algo = algos[opt_stage]
    k = int(math.log2(n))
    best_tp, best_t = float("inf"), 1
    for t in range(0, k + 1):
        threshold = 2 ** t
        wm, sm = evaluate_hybrid(algo, n, threshold, seq_formula)
        tw = fixed_w + wm
        ts = fixed_s + sm
        tp = ceil_div(tw, P) + ts
        if tp < best_tp:
            best_tp = tp
            best_t = threshold
    return {"threshold": best_t, "T_P": best_tp}


def solve_efficiency_threshold(algos, params):
    algo = algos[params["algorithm"]]
    w, s = evaluate_algorithm(algo, params["n"])
    min_eff = params["min_efficiency"]
    best_p = 1
    for pk in range(0, 40):
        p = 2 ** pk
        tp = ceil_div(w, p) + s
        eff = w / (p * tp)
        if eff >= min_eff:
            best_p = p
        else:
            break
    return {"processors": best_p}


def solve_strassen_granularity(algos, params):
    return solve_granularity(algos, params)


def main():
    algos_file = sys.argv[1]
    queries_file = sys.argv[2]

    with open(algos_file) as f:
        algos_raw = json.load(f)

    algos = {}
    for row in algos_raw:
        algos[row["name"]] = {
            "work_bf": row["branching_factor"],
            "work_combine": row["combine_cost_expr"],
            "span_cpb": row["critical_path_branches"],
            "span_combine": row["span_combine"],
            "base_work": row["base_work"],
            "base_span": row["base_span"],
            "div": row["subproblem_divisor"],
        }

    with open(queries_file) as f:
        queries_raw = json.load(f)

    solvers = {
        "evaluate": solve_evaluate,
        "brent": solve_brent,
        "composition": solve_composition,
        "crossover": solve_crossover,
        "optimal_processors": solve_optimal_processors,
        "min_parallelism_n": solve_min_parallelism_n,
        "granularity": solve_granularity,
        "composition_brent": solve_composition_brent,
        "pipeline_granularity": solve_pipeline_granularity,
        "efficiency_threshold": solve_efficiency_threshold,
        "strassen_granularity": solve_strassen_granularity,
    }

    output = []
    for row in queries_raw:
        qid = row["id"]
        qtype = row["type"]
        params = json.loads(row["params_json"])
        result = solvers[qtype](algos, params)
        output.append({"id": qid, "result": result})

    json.dump(output, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
