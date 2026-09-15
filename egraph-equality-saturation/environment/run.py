"""Runner: load problems, optimize each expression, write results."""
import json
import sys

sys.path.insert(0, "/app")

from expr import parse, to_sexp, expr_cost
from rules import RULES
from egraph import optimize


def main():
    with open("/app/problems.json") as f:
        problems = json.load(f)

    results = []
    for p in problems:
        try:
            optimized = optimize(p["expr"], RULES, iter_limit=30)
            cost = expr_cost(optimized)
            ok = cost <= p["optimal_cost"]
            results.append({
                "input": p["expr"],
                "output": to_sexp(optimized),
                "cost": cost,
                "expected_cost": p["optimal_cost"],
            })
            tag = "OK" if ok else "FAIL"
            print(f"  [{tag}] #{p['id']}: {p['expr']}  ->  {to_sexp(optimized)}  "
                  f"(cost {cost}, target <={p['optimal_cost']})")
        except Exception as exc:
            results.append({
                "input": p["expr"],
                "output": "ERROR",
                "cost": -1,
                "expected_cost": p["optimal_cost"],
                "error": str(exc),
            })
            print(f"  [ERR] #{p['id']}: {exc}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    passed = sum(1 for r in results
                 if 0 < r.get("cost", -1) <= r["expected_cost"])
    print(f"\n{passed}/{len(results)} problems solved optimally")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
