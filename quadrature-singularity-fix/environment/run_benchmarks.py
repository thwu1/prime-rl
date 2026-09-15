#!/usr/bin/env python3
"""
Benchmark driver for the numerical integration pipeline.

Evaluates 6 benchmark integrals using the pure-Python quadrature library
and cross-validates finite-domain results against the GSL C backend
(loaded via gsl_bridge.py -> libquad.so).

For a benchmark to pass:
  - Python library result must have relative error < 1e-10 vs analytical reference.
  - For finite-domain integrals, the GSL C backend result must also match.
  - For finite-domain integrals, Python and GSL results must agree within 1e-10.

Results are written to /app/results.json.
"""

import json
import math
import sys
import traceback

sys.path.insert(0, "/app")
from quadrature import integrate

# Try to load the GSL bridge (requires libquad.so to be built first)
try:
    from gsl_bridge import gsl_integrate
    GSL_AVAILABLE = True
except Exception as e:
    print(f"WARNING: GSL bridge not available: {e}")
    print("Build libquad.so first (run 'make' in /app/).\n")
    GSL_AVAILABLE = False


# ================================================================
# Integrand definitions
# ================================================================

def smooth_arctan(x):
    """4 / (1 + x^2)"""
    return 4.0 / (1.0 + x * x)


def log_log_product(x):
    """log(x) * log(1 - x) on (0, 1)."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return math.log(x) * math.log(1.0 - x)


def log_fourth_power(x):
    """(-log(x))^4 on (0, 1]."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return (-math.log(x)) ** 4


def exp_over_sqrt(t):
    """exp(-t^2) on [0, inf) -- Gaussian integral."""
    return math.exp(-t * t)


def sech_squared(x):
    """1 / cosh^2(x) on (-inf, inf)."""
    if abs(x) > 710.0:
        return 0.0
    c = math.cosh(x)
    return 1.0 / (c * c)


def planck_integrand(x):
    """x^3 / (exp(x) - 1) on (0, inf)."""
    if x <= 0.0:
        return 0.0
    if x > 700.0:
        return (x ** 3) * math.exp(-x)
    return (x ** 3) / (math.exp(x) - 1.0)


# ================================================================
# Benchmark definitions
# ================================================================

def get_benchmarks():
    pi = math.pi
    return [
        {
            "name": "smooth_arctan",
            "description": "int_0^1 4/(1+x^2) dx",
            "f": smooth_arctan,
            "a": 0.0,
            "b": 1.0,
            "reference": pi,
            "finite": True,
        },
        {
            "name": "log_log_product",
            "description": "int_0^1 log(x)*log(1-x) dx",
            "f": log_log_product,
            "a": 0.0,
            "b": 1.0,
            "reference": 2.0 - pi * pi / 6.0,
            "finite": True,
        },
        {
            "name": "log_fourth_power",
            "description": "int_0^1 (-log(x))^4 dx",
            "f": log_fourth_power,
            "a": 0.0,
            "b": 1.0,
            "reference": 24.0,
            "finite": True,
        },
        {
            "name": "gaussian_integral",
            "description": "int_0^inf exp(-t^2) dt",
            "f": exp_over_sqrt,
            "a": 0.0,
            "b": math.inf,
            "reference": math.sqrt(pi) / 2.0,
            "finite": False,
        },
        {
            "name": "sech_squared",
            "description": "int_-inf^inf sech^2(x) dx",
            "f": sech_squared,
            "a": -math.inf,
            "b": math.inf,
            "reference": 2.0,
            "finite": False,
        },
        {
            "name": "planck_integral",
            "description": "int_0^inf x^3/(e^x-1) dx",
            "f": planck_integrand,
            "a": 0.0,
            "b": math.inf,
            "reference": pi ** 4 / 15.0,
            "finite": False,
        },
    ]


# ================================================================
# Main
# ================================================================

def main():
    benchmarks = get_benchmarks()
    results = {}
    tol = 1e-12

    for bm in benchmarks:
        name = bm["name"]
        entry = {}
        try:
            # Python library result
            py_result, py_err = integrate(bm["f"], bm["a"], bm["b"], tol=tol)
            ref = bm["reference"]
            rel_err = abs(py_result - ref) / abs(ref) if ref != 0 else abs(py_result)

            entry["value"] = py_result
            entry["reference"] = ref
            entry["relative_error"] = rel_err

            passed = rel_err <= 1e-10

            # Cross-validate finite-domain integrals against GSL C backend
            if bm["finite"]:
                if not GSL_AVAILABLE:
                    entry["passed"] = False
                    entry["error"] = "GSL cross-validation required but bridge unavailable"
                    print(f"[FAIL] {name}: GSL bridge not available")
                    results[name] = entry
                    continue

                gsl_result, gsl_err = gsl_integrate(
                    bm["f"], bm["a"], bm["b"],
                    epsabs=tol, epsrel=tol, method=0
                )
                gsl_rel_err = (abs(gsl_result - ref) / abs(ref)
                               if ref != 0 else abs(gsl_result))
                cross_diff = (abs(py_result - gsl_result) / abs(ref)
                              if ref != 0 else abs(py_result - gsl_result))

                entry["gsl_value"] = gsl_result
                entry["gsl_relative_error"] = gsl_rel_err
                entry["cross_validation_error"] = cross_diff

                gsl_passed = gsl_rel_err <= 1e-10
                cross_passed = cross_diff <= 1e-10
                passed = passed and gsl_passed and cross_passed

                if not gsl_passed:
                    print(f"  GSL accuracy fail: rel_err={gsl_rel_err:.2e}")
                if not cross_passed:
                    print(f"  Cross-validation fail: diff={cross_diff:.2e}")

            entry["passed"] = passed
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {name}: py={py_result:.15e}, ref={ref:.15e}, "
                  f"rel_err={rel_err:.2e}")

        except Exception as e:
            entry["value"] = None
            entry["reference"] = bm["reference"]
            entry["relative_error"] = None
            entry["passed"] = False
            entry["error"] = str(e)
            print(f"[ERROR] {name}: {e}")
            traceback.print_exc()

        results[name] = entry

    out_path = "/app/results.json"
    with open(out_path, "w") as fp:
        json.dump(results, fp, indent=2)

    n_passed = sum(1 for r in results.values() if r.get("passed", False))
    print(f"\n{n_passed}/{len(benchmarks)} benchmarks passed.")
    print(f"Results written to {out_path}")


if __name__ == "__main__":
    main()
