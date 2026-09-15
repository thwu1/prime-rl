#!/usr/bin/env python3
"""Quick smoke tests for the TVM library.

NOTE: This is a basic validation, not a comprehensive test suite.
Functions may have additional edge-case defects not covered here.
"""
import os
import sys
sys.path.insert(0, '/app')

import numpy as np

passed = 0
failed = 0
errors = []

# Check native backend status
lib_path = '/app/native/libdiscount.so'
if os.path.exists(lib_path):
    print(f"Native C accelerator: found at {lib_path}")
else:
    print(f"WARNING: Native C accelerator not found at {lib_path}")
    print("  The native backend must be built for full functionality.")
    print()


def check(name, actual, expected, rtol=1e-3, atol=1e-10):
    global passed, failed
    try:
        if isinstance(expected, float) and np.isnan(expected):
            if np.isnan(actual):
                passed += 1
            else:
                failed += 1
                errors.append(f"FAIL {name}: expected NaN, got {actual}")
            return
        if isinstance(expected, float) and np.isinf(expected):
            if np.isinf(actual) and np.sign(actual) == np.sign(expected):
                passed += 1
            else:
                failed += 1
                errors.append(f"FAIL {name}: expected {expected}, got {actual}")
            return
        if abs(actual - expected) <= rtol * abs(expected) + atol:
            passed += 1
        else:
            failed += 1
            errors.append(f"FAIL {name}: expected {expected}, got {actual}")
    except Exception as e:
        failed += 1
        errors.append(f"ERROR {name}: {type(e).__name__}: {e}")


import tvm

# --- Core function smoke tests ---
check("fv_basic", tvm.fv(0.075, 20, -2000, 0, 0), 86609.362673)
check("pv_basic", tvm.pv(0.07, 20, 12000, 0), -127128.17, rtol=1e-2)
check("pmt_basic", tvm.pmt(0.08 / 12, 5 * 12, 15000), -304.145914, rtol=1e-4)
check("nper_basic", tvm.nper(0.075, -2000, 0, 100000), 21.544944, rtol=1e-4)
check("rate_basic", tvm.rate(10, 0, -3500, 10000), 0.1107, rtol=1e-3)
check("ipmt_basic", tvm.ipmt(0.1 / 12, 1, 24, 2000), -16.666667, rtol=1e-4)
check("ppmt_basic", tvm.ppmt(0.1 / 12, 1, 60, 55000), -710.25, rtol=1e-3)

# --- IRR tests ---
check("irr_simple", tvm.irr([-100, 39, 59, 55, 20]), 0.28095, rtol=1e-2)
check("irr_multiroot", tvm.irr([-5, 10.5, 1, -8, 1]), 0.0886, rtol=1e-2)

# --- NPV edge case ---
check("npv_basic", tvm.npv(0.05, [-15000, 1500, 2500, 3500, 4500, 6000]),
      122.89, rtol=1e-2)
check("npv_rate_neg1", tvm.npv(-1, [0, 1, 2, 3, 4]), float('nan'))

# --- MIRR ---
check("mirr_basic",
      tvm.mirr([-120000, 39000, 30000, 21000, 37000, 46000], 0.10, 0.12),
      0.126094, rtol=1e-3)

# --- NaN for infeasible ---
check("irr_no_sol", tvm.irr([1, 2, 3]), float('nan'))
check("mirr_no_sol", tvm.mirr([39000, 30000, 21000], 0.10, 0.12), float('nan'))

# --- xnpv / xirr ---
try:
    from datetime import date
    result = tvm.xnpv(0.1, [-1000, 1100],
                      [date(2019, 1, 1), date(2020, 1, 1)])
    check("xnpv_basic", result, 0.0, atol=0.01)
except NotImplementedError:
    failed += 1
    errors.append("FAIL xnpv: NotImplementedError — function not implemented")
except Exception as e:
    failed += 1
    errors.append(f"ERROR xnpv: {type(e).__name__}: {e}")

try:
    from datetime import date
    result = tvm.xirr([-1000, 1100],
                      [date(2019, 1, 1), date(2020, 1, 1)])
    check("xirr_basic", result, 0.1, rtol=1e-3)
except NotImplementedError:
    failed += 1
    errors.append("FAIL xirr: NotImplementedError — function not implemented")
except Exception as e:
    failed += 1
    errors.append(f"ERROR xirr: {type(e).__name__}: {e}")

# --- Summary ---
print(f"\n{'=' * 50}")
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
print(f"{'=' * 50}")
if errors:
    print("\nFailures:")
    for e in errors:
        print(f"  {e}")
sys.exit(1 if failed > 0 else 0)
