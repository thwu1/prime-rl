"""
Tests for the black-box global optimizer.

Verifies that /app/optimizer.py exports an `optimize` function that achieves
target error thresholds on at least 10 of 12 GNBG-inspired benchmark problems.
"""


import sys
import importlib
import numpy as np

sys.path.insert(0, "/app")


def test_optimizer_importable():
    """optimizer.py must exist and export an 'optimize' callable."""
    mod = importlib.import_module("optimizer")
    assert hasattr(mod, "optimize"), "optimizer.py must export 'optimize'"
    assert callable(mod.optimize), "'optimize' must be callable"


def test_benchmark_suite_performance():
    """Run the optimizer on all 12 benchmark problems (seed=42).

    At least 10 of the 12 problems must achieve best-found error below
    their individual target thresholds.
    """
    from benchmark import get_suite
    from optimizer import optimize

    suite = get_suite(seed=42)
    results = []

    for problem in suite:
        np.random.seed(problem.fid * 1000 + 42)
        x_best = optimize(problem)

        best_x, best_val = problem.get_best()
        _, opt_val = problem._get_optimum()
        error = abs(best_val - opt_val)
        passed = error < problem.target_error

        results.append({
            "name": problem.name,
            "error": error,
            "target": problem.target_error,
            "evals": problem.evals_used,
            "max_evals": problem.max_evals,
            "passed": passed,
        })

    # Print detailed results for diagnostics
    print("\n" + "=" * 72)
    print(f"{'Problem':<20} {'Error':>12} {'Target':>10} {'Evals':>8} {'Status':>8}")
    print("-" * 72)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['name']:<20} {r['error']:>12.4e} {r['target']:>10.1e} "
              f"{r['evals']:>8d} {status:>8}")
    print("=" * 72)

    num_passed = sum(r["passed"] for r in results)
    print(f"\nTotal passed: {num_passed} / {len(results)}")

    assert num_passed >= 10, (
        f"Only {num_passed}/12 problems passed (need >= 10). "
        f"Failed: {[r['name'] for r in results if not r['passed']]}"
    )


def test_optimizer_not_hardcoded():
    """Verify the optimizer actually runs evaluations on an unseen seed."""
    from benchmark import get_suite
    from optimizer import optimize

    suite = get_suite(seed=99)
    problem = suite[0]  # Sphere — easiest problem

    np.random.seed(12345)
    optimize(problem)

    assert problem.evals_used >= 100, (
        f"Optimizer used only {problem.evals_used} evaluations on an unseen "
        f"problem instance. This suggests a hardcoded solution."
    )

    _, best_val = problem.get_best()
    _, opt_val = problem._get_optimum()
    error = abs(best_val - opt_val)
    assert error < problem.target_error, (
        f"Optimizer failed on Sphere (seed=99): error={error:.4e}, "
        f"target={problem.target_error:.1e}. A correct optimizer should "
        f"trivially solve Sphere."
    )
