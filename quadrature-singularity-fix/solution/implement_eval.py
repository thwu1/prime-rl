#!/usr/bin/env python3
"""
Implement the quadrature method evaluation framework.

Loads libquad.so via ctypes, benchmarks all 7 GSL quadrature methods on each
test integrand, designs an accuracy assessment methodology using cross-method
convergence analysis (median consensus), and produces /app/evaluation.json.
"""

import ctypes
import json
import statistics
import sys
import os

sys.path.insert(0, "/app")
from integrands import INTEGRANDS, FUNCTIONS

LIBQUAD_PATH = "/app/libquad.so"

METHOD_NAMES = {
    0: "QAG_GK15", 1: "QAG_GK21", 2: "QAG_GK31",
    3: "QAG_GK41", 4: "QAG_GK51", 5: "QAG_GK61",
    6: "QAGS",
}

# ctypes callback type matching: typedef double (*py_integrand)(double x);
IFUNC = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double)


def load_library():
    """Load libquad.so and configure ctypes prototype for quad_integrate."""
    lib = ctypes.CDLL(LIBQUAD_PATH)
    lib.quad_integrate.restype = ctypes.c_double
    lib.quad_integrate.argtypes = [
        IFUNC,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_double,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    return lib


def call_method(lib, f_py, a, b, method):
    """Call quad_integrate for a single (integrand, method) pair."""
    abserr = ctypes.c_double(0.0)
    neval = ctypes.c_int(0)
    status = ctypes.c_int(0)
    cb = IFUNC(f_py)
    result = lib.quad_integrate(
        cb, a, b, 1e-12, 1e-12, method,
        ctypes.byref(abserr),
        ctypes.byref(neval),
        ctypes.byref(status),
    )
    return {
        "value": float(result),
        "abserr": float(abserr.value),
        "neval": int(neval.value),
        "status": int(status.value),
    }


def assess_and_rank(method_results):
    """Rank methods for a single integrand using convergence analysis.

    Accuracy assessment without reference values:
    1. Partition methods into successful (status==0) and failed.
    2. Among successful methods, compute a consensus reference value
       using the median — this is robust to outliers from methods
       that converged to subtly wrong values.
    3. Rank successful methods by deviation from consensus, using
       GSL's reported abserr as tiebreaker.
    4. Failed methods are ranked last, ordered by method index.
    """
    successful = []
    failed = []
    for mid in range(7):
        entry = method_results[str(mid)]
        if entry["status"] == 0:
            successful.append(mid)
        else:
            failed.append(mid)

    if not successful:
        # All failed — rank higher-order methods first
        ranking = sorted(failed, reverse=True)
        best = ranking[0]
        best_val = method_results[str(best)]["value"]
        return ranking, best, best_val

    # Consensus reference from median of successful values
    values = [method_results[str(m)]["value"] for m in successful]
    consensus = statistics.median(values)

    # Rank successful methods by deviation from consensus,
    # then by reported abserr for ties
    successful_ranked = sorted(
        successful,
        key=lambda m: (
            abs(method_results[str(m)]["value"] - consensus),
            method_results[str(m)]["abserr"],
        ),
    )
    # Failed methods last, ordered by method index
    failed_ranked = sorted(failed)

    ranking = successful_ranked + failed_ranked
    best = ranking[0]
    best_val = method_results[str(best)]["value"]
    return ranking, best, best_val


def compute_overall_ranking(benchmarks):
    """Aggregate per-integrand rankings into overall ranking by rank-sum.

    For each method, sum its rank position (0-indexed) across all
    integrands. Lower total rank-sum indicates better performance.
    Ties broken by method index.
    """
    rank_sums = {m: 0 for m in range(7)}
    for name, bm in benchmarks.items():
        for pos, mid in enumerate(bm["ranking"]):
            rank_sums[mid] += pos
    return sorted(range(7), key=lambda m: (rank_sums[m], m))


def main():
    lib = load_library()

    benchmarks = {}
    for name, info in INTEGRANDS.items():
        f_py = FUNCTIONS[name]
        a, b = info["a"], info["b"]

        print(f"Evaluating: {name} ({info['description']})")
        method_results = {}
        for method_id in range(7):
            result = call_method(lib, f_py, a, b, method_id)
            method_results[str(method_id)] = result
            status_str = (
                "OK" if result["status"] == 0
                else f"FAIL({result['status']})"
            )
            print(
                f"  method {method_id} ({METHOD_NAMES[method_id]}): "
                f"value={result['value']:.15e} "
                f"abserr={result['abserr']:.2e} "
                f"neval={result['neval']} [{status_str}]"
            )

        ranking, best_method, best_value = assess_and_rank(method_results)

        benchmarks[name] = {
            "methods": method_results,
            "best_method": best_method,
            "best_value": best_value,
            "ranking": ranking,
        }
        print(
            f"  -> best: method {best_method} "
            f"({METHOD_NAMES[best_method]}), "
            f"ranking: {[METHOD_NAMES[m] for m in ranking]}"
        )
        print()

    overall_ranking = compute_overall_ranking(benchmarks)

    output = {
        "benchmarks": benchmarks,
        "overall_ranking": overall_ranking,
        "method_names": {str(k): v for k, v in METHOD_NAMES.items()},
    }

    out_path = "/app/evaluation.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Evaluation written to {out_path}")
    print(
        f"Overall ranking: "
        f"{[METHOD_NAMES[m] for m in overall_ranking]}"
    )


if __name__ == "__main__":
    main()
