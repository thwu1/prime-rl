#!/usr/bin/env python3

"""HLS Evaluation Pipeline -- reference solution."""
import json
import os
import subprocess
import tempfile
from itertools import product
from math import comb


# ------------------------------------------------------------------
# 1. Compilation + Simulation
# ------------------------------------------------------------------
def compile_and_simulate(candidate_path, testbench_path):
    """Return (compiled: bool, passed: bool)."""
    with tempfile.NamedTemporaryFile(suffix="_test", delete=False) as tmp:
        binary = tmp.name

    try:
        comp = subprocess.run(
            ["g++", "-o", binary, candidate_path, testbench_path],
            capture_output=True, timeout=30,
        )
        if comp.returncode != 0:
            return False, False
    except Exception:
        return False, False

    try:
        sim = subprocess.run([binary], capture_output=True, timeout=30)
        return True, sim.returncode == 0
    except Exception:
        return True, False
    finally:
        if os.path.exists(binary):
            os.unlink(binary)


def evaluate_benchmarks(benchmarks_dir):
    """Run compilation + simulation for every benchmark/candidate."""
    compilation = {}
    simulation = {}
    pass_counts = {}

    for bench in sorted(os.listdir(benchmarks_dir)):
        bench_dir = os.path.join(benchmarks_dir, bench)
        if not os.path.isdir(bench_dir):
            continue
        tb = os.path.join(bench_dir, "testbench.cpp")
        cands_dir = os.path.join(bench_dir, "candidates")
        if not os.path.isdir(cands_dir):
            continue

        compilation[bench] = {}
        simulation[bench] = {}
        n_pass = 0

        for cfile in sorted(os.listdir(cands_dir)):
            if not cfile.endswith(".cpp"):
                continue
            cname = cfile[:-4]  # strip .cpp
            cpath = os.path.join(cands_dir, cfile)

            compiled, passed = compile_and_simulate(cpath, tb)
            compilation[bench][cname] = compiled
            simulation[bench][cname] = passed
            if passed:
                n_pass += 1

        pass_counts[bench] = n_pass

    return compilation, simulation, pass_counts


# ------------------------------------------------------------------
# 2. DSE expansion with constraints
# ------------------------------------------------------------------
def expand_dse(config):
    """Expand DSE config, return (constrained_total, unconstrained_total)."""
    params = config["parameters"]
    constraints = config.get("constraints", [])

    param_names = list(params.keys())
    param_values = [params[name] for name in param_names]

    # Build constraint map: dependent -> {condition_param: required_value(s)}
    constraint_map = {}
    for c in constraints:
        dep = c["dependent"]
        constraint_map[dep] = c["requires"]

    unconstrained = 1
    for v in param_values:
        unconstrained *= len(v)

    constrained = 0
    for combo in product(*param_values):
        cfg = dict(zip(param_names, combo))
        valid = True
        for dep_param, requirements in constraint_map.items():
            for req_param, req_val in requirements.items():
                condition_met = False
                if isinstance(req_val, list):
                    condition_met = cfg[req_param] in req_val
                else:
                    condition_met = cfg[req_param] == req_val

                if not condition_met:
                    # dependent must be at its default (first value)
                    default = params[dep_param][0]
                    if cfg[dep_param] != default:
                        valid = False
                        break
            if not valid:
                break
        if valid:
            constrained += 1

    return constrained, unconstrained


# ------------------------------------------------------------------
# 3. Pass@K
# ------------------------------------------------------------------
def pass_at_k(n, c, k):
    """Unbiased Pass@k estimator."""
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def compute_pass_at_k(pass_counts, n=10):
    per_bench = {}
    for bench, c in pass_counts.items():
        per_bench[bench] = {
            "pass_at_1": pass_at_k(n, c, 1),
            "pass_at_5": pass_at_k(n, c, 5),
            "pass_at_10": pass_at_k(n, c, 10),
        }

    agg = {}
    for k_name in ["pass_at_1", "pass_at_5", "pass_at_10"]:
        vals = [v[k_name] for v in per_bench.values()]
        agg[k_name] = sum(vals) / len(vals)

    return {"per_benchmark": per_bench, "aggregate": agg}


# ------------------------------------------------------------------
# 4. Pareto frontier
# ------------------------------------------------------------------
def find_pareto(design_points, objectives):
    """Return sorted list of Pareto-optimal IDs (minimise all objectives)."""
    n = len(design_points)
    is_dominated = [False] * n

    for i in range(n):
        if is_dominated[i]:
            continue
        for j in range(n):
            if i == j or is_dominated[j]:
                continue
            # Check if j dominates i
            all_leq = all(
                design_points[j][o] <= design_points[i][o] for o in objectives
            )
            any_lt = any(
                design_points[j][o] < design_points[i][o] for o in objectives
            )
            if all_leq and any_lt:
                is_dominated[i] = True
                break

    optimal = sorted(
        design_points[i]["id"]
        for i in range(n)
        if not is_dominated[i]
    )
    dominated_count = sum(is_dominated)
    return optimal, dominated_count


# ------------------------------------------------------------------
# 5. PPA normalization
# ------------------------------------------------------------------
def compute_ppa_normalization(ppa_data):
    result = {}
    for bench, vals in ppa_data.items():
        ref = vals["reference"]
        gen = vals["generated"]
        result[bench] = {
            "lut_pct": (gen["lut"] - ref["lut"]) / ref["lut"] * 100,
            "ff_pct": (gen["ff"] - ref["ff"]) / ref["ff"] * 100,
            "latency_pct": (
                (gen["latency_ns"] - ref["latency_ns"])
                / ref["latency_ns"]
                * 100
            ),
            "power_pct": (
                (gen["power_mw"] - ref["power_mw"]) / ref["power_mw"] * 100
            ),
        }
    return result


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main():
    # 1. Evaluate benchmarks
    compilation, simulation, pass_counts = evaluate_benchmarks(
        "/app/benchmarks"
    )

    # 2. DSE expansion
    with open("/app/dse_config.json") as f:
        dse_config = json.load(f)
    total_configs, unconstrained = expand_dse(dse_config)

    # 3. Pass@K
    pak = compute_pass_at_k(pass_counts)

    # 4. Pareto frontier
    with open("/app/ppa_analysis/design_points.json") as f:
        design_points = json.load(f)
    objectives = ["lut", "ff", "latency_ns", "power_mw"]
    pareto_set, num_dominated = find_pareto(design_points, objectives)

    # 5. PPA normalization
    with open("/app/ppa_analysis/ppa_comparison.json") as f:
        ppa_data = json.load(f)
    ppa_norm = compute_ppa_normalization(ppa_data)

    # Assemble report
    report = {
        "compilation": compilation,
        "simulation": simulation,
        "dse": {
            "total_configurations": total_configs,
            "unconstrained_total": unconstrained,
        },
        "pass_at_k": pak,
        "pareto_frontier": {
            "optimal_set": pareto_set,
            "num_dominated": num_dominated,
        },
        "ppa_normalization": ppa_norm,
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/output/report.json")


if __name__ == "__main__":
    main()
