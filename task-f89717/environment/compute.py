#!/usr/bin/env python3
"""Compute benchmark integrals and write results to results.json."""

import json
import math
import sys

sys.path.insert(0, '/app')
from quadrature import integrate

TOLERANCE = 1e-8


def main():
    benchmarks = [
        {
            "id": "smooth_pi",
            "desc": "int_0^1 4/(1+x^2) dx = pi",
            "func": lambda x: 4.0 / (1.0 + x * x),
            "a": 0.0,
            "b": 1.0,
            "exact": math.pi,
            "limit": 500,
        },
        {
            "id": "oscillatory",
            "desc": "int_0^1 2/(2+sin(10*pi*x)) dx = 2/sqrt(3)",
            "func": lambda x: 2.0 / (2.0 + math.sin(10.0 * math.pi * x)),
            "a": 0.0,
            "b": 1.0,
            "exact": 2.0 / math.sqrt(3.0),
            "limit": 1000,
        },
        {
            "id": "singular_algebraic",
            "desc": "int_0^1 x^(-1/4) dx = 4/3",
            "func": lambda x: x ** (-0.25) if x > 0 else 0.0,
            "a": 0.0,
            "b": 1.0,
            "exact": 4.0 / 3.0,
            "limit": 1000,
        },
        {
            "id": "gaussian_inf",
            "desc": "int_0^inf exp(-x^2) dx = sqrt(pi)/2",
            "func": lambda x: math.exp(-x * x),
            "a": 0.0,
            "b": math.inf,
            "exact": math.sqrt(math.pi) / 2.0,
            "limit": 500,
        },
        {
            "id": "gamma3_inf",
            "desc": "int_0^inf x^2*exp(-x) dx = Gamma(3) = 2",
            "func": lambda x: x * x * math.exp(-x),
            "a": 0.0,
            "b": math.inf,
            "exact": 2.0,
            "limit": 500,
        },
        {
            "id": "lorentzian_inf",
            "desc": "int_0^inf 1/(1+x^2) dx = pi/2",
            "func": lambda x: 1.0 / (1.0 + x * x),
            "a": 0.0,
            "b": math.inf,
            "exact": math.pi / 2.0,
            "limit": 500,
        },
    ]

    results = {}
    all_ok = True

    print("Benchmark results:")
    for bm in benchmarks:
        r, e, n, c = integrate(
            bm["func"], bm["a"], bm["b"],
            epsabs=TOLERANCE, epsrel=TOLERANCE, limit=bm["limit"],
        )
        actual_err = abs(r - bm["exact"])
        ok = actual_err < TOLERANCE
        if not ok:
            all_ok = False

        results[bm["id"]] = {
            "computed": r,
            "exact": bm["exact"],
            "absolute_error": actual_err,
            "estimated_error": e,
            "evaluations": n,
            "converged": c,
            "passed": ok,
        }
        status = "PASS" if ok else "FAIL"
        print(
            f'  {bm["id"]:25s}  computed={r:+.14e}  '
            f'exact={bm["exact"]:+.14e}  err={actual_err:.3e}  [{status}]'
        )

    with open('/app/results.json', 'w') as fh:
        json.dump(results, fh, indent=2)

    print(f'\n{"ALL PASSED" if all_ok else "SOME FAILED"}')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
