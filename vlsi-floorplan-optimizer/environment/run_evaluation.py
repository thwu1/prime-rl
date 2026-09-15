#!/usr/bin/env python3
"""
Run the floorplan optimizer on all instances and evaluate results.

"""

import importlib.util
import json
import os
import sys
import time


def main():
    sys.path.insert(0, "/app")
    from evaluator import evaluate_solution, compute_total_score

    # Import optimizer
    opt_path = "/app/optimizer.py"
    if not os.path.exists(opt_path):
        print(f"ERROR: {opt_path} not found")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("optimizer", opt_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    optimizer = mod.FloorplanOptimizer()

    # Load and evaluate all instances
    instance_dir = "/app/instances"
    instance_files = sorted(f for f in os.listdir(instance_dir) if f.endswith(".json"))
    results = []

    for fname in instance_files:
        with open(os.path.join(instance_dir, fname)) as f:
            instance = json.load(f)

        name = instance["name"]
        n = instance["block_count"]
        print(f"\n{'='*55}")
        print(f"  {name}  (n={n})")
        print(f"{'='*55}")

        start = time.time()
        placement = optimizer.solve(instance)
        elapsed = time.time() - start

        result = evaluate_solution(instance, placement)
        print(f"  Feasible : {result['feasible']}")
        print(f"  Cost     : {result['cost']:.4f}")
        print(f"  Time     : {elapsed:.2f}s")
        if result["feasible"]:
            print(f"  HPWL     : {result['total_hpwl']:.2f}  "
                  f"(gap: {result['hpwl_gap']:.4f})")
            print(f"  Area     : {result['bbox_area']:.2f}  "
                  f"(gap: {result['area_gap']:.4f})")
            print(f"  V_rel    : {result['v_rel']:.4f}  "
                  f"(cluster={result['cluster_violations']}, "
                  f"mib={result['mib_violations']}, "
                  f"boundary={result['boundary_violations']})")
        else:
            print(f"  Error    : {result.get('error', 'unknown')}")

        results.append((n, result["cost"]))

    total_score = compute_total_score(results)
    print(f"\n{'='*55}")
    print(f"  TOTAL WEIGHTED SCORE: {total_score:.4f}")
    print(f"  THRESHOLD           : 3.0")
    print(f"  RESULT              : {'PASS' if total_score <= 3.0 else 'FAIL'}")
    print(f"{'='*55}")

    # Write results JSON
    with open("/app/evaluation_results.json", "w") as f:
        json.dump({
            "total_score": total_score,
            "instances": [{"block_count": n, "cost": c} for n, c in results],
        }, f, indent=2)

    return total_score


if __name__ == "__main__":
    score = main()
    sys.exit(0 if score <= 3.0 else 1)
