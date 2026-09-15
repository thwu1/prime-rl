#!/usr/bin/env python3
"""Evaluation script for the arc length computation engine."""

import json
import sys
import os
import traceback

sys.path.insert(0, '/app')

from bezier import make_quad, make_cubic


def load_reference():
    with open('/app/reference_curves.json') as f:
        return json.load(f)


def run_evaluation():
    try:
        from arclength import arclen
    except ImportError as e:
        print(f"ERROR: Cannot import arclength module: {e}")
        print("Make sure /app/arclength.py exists and is importable.")
        return False
    except Exception as e:
        print(f"ERROR loading arclength module: {e}")
        traceback.print_exc()
        return False

    ref = load_reference()
    all_pass = True
    quad_pass = 0
    quad_total = len(ref["quadratic"])
    cubic_pass = 0
    cubic_total = len(ref["cubic"])

    print("=" * 60)
    print("Quadratic Bézier Curves")
    print("=" * 60)
    for entry in ref["quadratic"]:
        name = entry["name"]
        curve = make_quad(entry["px"], entry["py"])
        expected = entry["arclen"]
        tol = entry["tolerance"]
        try:
            result = arclen(curve)
            if expected == 0:
                err = abs(result)
            else:
                err = abs(result - expected) / abs(expected)
            ok = err < tol
            status = "PASS" if ok else "FAIL"
            if not ok:
                all_pass = False
            else:
                quad_pass += 1
            print(f"  [{status}] {name:20s}  computed={result:.15e}  "
                  f"expected={expected:.15e}  rel_err={err:.2e}")
        except Exception as e:
            all_pass = False
            print(f"  [FAIL] {name:20s}  ERROR: {e}")

    print()
    print("=" * 60)
    print("Cubic Bézier Curves")
    print("=" * 60)
    for entry in ref["cubic"]:
        name = entry["name"]
        curve = make_cubic(entry["px"], entry["py"])
        expected = entry["arclen"]
        tol = entry["tolerance"]
        try:
            result = arclen(curve)
            if expected == 0:
                err = abs(result)
            else:
                err = abs(result - expected) / abs(expected)
            ok = err < tol
            status = "PASS" if ok else "FAIL"
            if not ok:
                all_pass = False
            else:
                cubic_pass += 1
            print(f"  [{status}] {name:20s}  computed={result:.15e}  "
                  f"expected={expected:.15e}  rel_err={err:.2e}")
        except Exception as e:
            all_pass = False
            print(f"  [FAIL] {name:20s}  ERROR: {e}")

    print()
    print("=" * 60)
    print(f"Quadratic: {quad_pass}/{quad_total} passed")
    print(f"Cubic:     {cubic_pass}/{cubic_total} passed")
    print("=" * 60)

    if all_pass:
        print("\nAll tests passed!")
    else:
        print("\nSome tests FAILED.")

    return all_pass


if __name__ == "__main__":
    ok = run_evaluation()
    sys.exit(0 if ok else 1)
