#!/usr/bin/env python3
"""
COCO BBOB Experiment Runner.

Loads an optimizer module and evaluates it on the configured BBOB function suite.
Results are logged via COCO's observer system for post-processing.

Usage:
    python3 /app/experiment/run_benchmark.py /path/to/optimizer.py [output_dir]

The optimizer module must define:
    optimize(func, dim, lb, ub, budget, x0=None) -> (best_x, best_f)
"""
import sys
import os
import importlib.util
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import SUITE_NAME, INSTANCE_SPEC, FUNCTION_IDS, DIMENSIONS, BUDGET_FACTOR


def load_module(path):
    """Load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location("opt_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    optimizer_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/app/exdata"

    if not os.path.exists(optimizer_path):
        print(f"Error: {optimizer_path} not found")
        sys.exit(1)

    mod = load_module(optimizer_path)
    if not hasattr(mod, "optimize"):
        print(f"Error: {optimizer_path} must define an 'optimize' function")
        sys.exit(1)

    optimize = mod.optimize
    algo_name = os.path.splitext(os.path.basename(optimizer_path))[0]

    import cocoex

    func_str = ",".join(str(f) for f in FUNCTION_IDS)
    dim_str = ",".join(str(d) for d in DIMENSIONS)
    suite_opts = f"function_indices: {func_str} dimensions: {dim_str}"

    suite = cocoex.Suite(SUITE_NAME, INSTANCE_SPEC, suite_opts)
    observer = cocoex.Observer(SUITE_NAME, f"result_folder: {output_dir}")

    print(f"Algorithm: {algo_name}")
    print(f"Suite: {SUITE_NAME} — {len(suite)} problems")
    print(f"Functions: {FUNCTION_IDS}")
    print(f"Dimensions: {DIMENSIONS}")
    print(f"Budget factor: {BUDGET_FACTOR}")
    print("-" * 60)

    results = {}
    for problem in suite:
        problem.observe_with(observer)
        budget = BUDGET_FACTOR * problem.dimension

        seed = problem.id_function * 1000 + problem.id_instance * 10 + problem.dimension
        np.random.seed(seed)

        try:
            best_x, best_f = optimize(
                problem,
                problem.dimension,
                problem.lower_bounds,
                problem.upper_bounds,
                budget,
                x0=problem.initial_solution,
            )
            hit = problem.final_target_hit
            status = "TARGET HIT" if hit else "target missed"
            print(
                f"  f{problem.id_function:>2d} {problem.dimension:>2d}D "
                f"inst {problem.id_instance}: best_f={best_f:>12.6e}  "
                f"[{status}] ({problem.evaluations} evals)"
            )

            key = (problem.id_function, problem.dimension)
            if key not in results:
                results[key] = {"hits": 0, "total": 0}
            results[key]["total"] += 1
            if hit:
                results[key]["hits"] += 1

        except Exception as e:
            print(
                f"  f{problem.id_function} {problem.dimension}D "
                f"inst {problem.id_instance}: ERROR — {e}"
            )

        problem.free()

    print("\n" + "=" * 60)
    print("Summary (final target hits / instances):")
    print("=" * 60)
    for (fid, dim), data in sorted(results.items()):
        bar = "#" * data["hits"] + "." * (data["total"] - data["hits"])
        print(f"  f{fid:>2d} {dim:>2d}D: {data['hits']}/{data['total']}  [{bar}]")

    print(f"\nExperiment data saved to: {output_dir}/")
    print("For post-processing: python3 /app/experiment/analyze.py " + output_dir)


if __name__ == "__main__":
    main()
