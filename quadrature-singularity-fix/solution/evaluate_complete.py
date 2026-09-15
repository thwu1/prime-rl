#!/usr/bin/env python3
"""
Complete Quadrature Method Evaluation Framework.

Loads the compiled C quadrature library via ctypes, benchmarks all 7
integration methods on 6 test integrands, ranks methods by accuracy,
and writes /app/evaluation.json.
"""

import ctypes
import json
import math
import sys
import time

sys.path.insert(0, "/app")
from integrands import INTEGRANDS, FUNCTIONS

# ------------------------------------------------------------------
# Load the shared library and configure ctypes prototypes
# ------------------------------------------------------------------

lib = ctypes.CDLL("/app/libquad.so")

INTEGRAND_FUNC = ctypes.CFUNCTYPE(ctypes.c_double, ctypes.c_double)

lib.quad_integrate.restype = ctypes.c_double
lib.quad_integrate.argtypes = [
    INTEGRAND_FUNC,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_double,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
]

METHOD_NAMES = {
    0: "QAG_GK15", 1: "QAG_GK21", 2: "QAG_GK31",
    3: "QAG_GK41", 4: "QAG_GK51", 5: "QAG_GK61",
    6: "QAGS",
}


# ------------------------------------------------------------------
# Benchmark helpers
# ------------------------------------------------------------------

def run_method(func, a, b, method, epsabs=1e-12, epsrel=1e-12):
    """Run a single quadrature method on an integrand via the C library."""
    c_func = INTEGRAND_FUNC(func)

    abserr = ctypes.c_double(0.0)
    neval = ctypes.c_int(0)
    status = ctypes.c_int(0)

    t0 = time.monotonic()
    result = lib.quad_integrate(
        c_func, a, b, epsabs, epsrel, method,
        ctypes.byref(abserr),
        ctypes.byref(neval),
        ctypes.byref(status),
    )
    elapsed = time.monotonic() - t0

    return {
        "value": result,
        "abserr": abserr.value,
        "neval": neval.value,
        "status": status.value,
        "time_s": elapsed,
    }


def rank_methods(methods_data):
    """Rank methods: successful first (sorted by abserr), failures last."""
    successful = [
        (int(m), d) for m, d in methods_data.items() if d["status"] == 0
    ]
    successful.sort(key=lambda x: (x[1]["abserr"], x[1]["neval"]))
    return [m for m, _ in successful]


# ------------------------------------------------------------------
# Main evaluation
# ------------------------------------------------------------------

def main():
    evaluation = {
        "benchmarks": {},
        "method_names": {str(k): v for k, v in METHOD_NAMES.items()},
    }

    for name, info in INTEGRANDS.items():
        func = FUNCTIONS[name]
        a = info["a"]
        b = info["b"]

        print(f"\n--- {name}: {info['description']} ---")

        methods_data = {}
        for method_id in range(7):
            try:
                res = run_method(func, a, b, method_id)
                methods_data[str(method_id)] = res
                tag = "OK" if res["status"] == 0 else f"ERR({res['status']})"
                print(
                    f"  [{tag}] {METHOD_NAMES[method_id]:10s}  "
                    f"val={res['value']:+.14e}  "
                    f"err={res['abserr']:.2e}  "
                    f"neval={res['neval']}"
                )
            except Exception as exc:
                methods_data[str(method_id)] = {
                    "value": 0.0,
                    "abserr": float("inf"),
                    "neval": 0,
                    "status": -99,
                    "error": str(exc),
                }
                print(f"  [EXC] {METHOD_NAMES[method_id]:10s}  {exc}")

        ranking = rank_methods(methods_data)
        if ranking:
            best_id = ranking[0]
            best_val = methods_data[str(best_id)]["value"]
        else:
            best_id = -1
            best_val = 0.0

        evaluation["benchmarks"][name] = {
            "methods": methods_data,
            "best_method": best_id,
            "best_value": best_val,
            "ranking": ranking,
        }
        print(f"  => best: method {best_id} ({METHOD_NAMES.get(best_id, '?')})")

    # Overall ranking: weighted sum of per-integrand ranks
    scores = {m: 0 for m in range(7)}
    for bm in evaluation["benchmarks"].values():
        for pos, mid in enumerate(bm["ranking"]):
            scores[mid] += (7 - pos)
    overall = sorted(scores, key=lambda m: -scores[m])
    evaluation["overall_ranking"] = overall

    with open("/app/evaluation.json", "w") as fp:
        json.dump(evaluation, fp, indent=2)

    print(f"\nResults written to /app/evaluation.json")
    print(f"Overall ranking: {[f'{m}({METHOD_NAMES[m]})' for m in overall]}")


if __name__ == "__main__":
    main()
