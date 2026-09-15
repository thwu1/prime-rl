#!/usr/bin/env python3
"""
Test runner for Mini Effekt programs.

Loads program files from /app/programs/, executes each through the
interpreter, and compares actual results against expected values
defined in each program's build() function.

Usage: python3 /app/run_all.py
"""

import importlib.util
import os
import sys

sys.path.insert(0, "/app")

from effekt import Interpreter

PROGRAMS_DIR = "/app/programs"


def load_module(name, filepath):
    """Dynamically load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def safe_execute(interp, prog):
    """Execute a program, returning (result, output).

    Catches runtime errors to prevent a single broken program from
    stopping the entire test suite.  Returns (None, []) on failure.
    """
    try:
        return interp.run(prog)
    except Exception as e:
        print(f"    ERROR: {type(e).__name__}: {e}")
        return None, []


def main():
    files = sorted(f for f in os.listdir(PROGRAMS_DIR)
                   if f.endswith('.py') and not f.startswith('_'))

    passed = 0
    failed = 0

    for fname in files:
        name = fname[:-3]
        filepath = os.path.join(PROGRAMS_DIR, fname)

        try:
            mod = load_module(name, filepath)
            prog, expected_result, expected_output = mod.build()
        except Exception as e:
            print(f"  SKIP  {name}: load error ({e})")
            failed += 1
            continue

        interp = Interpreter()
        result, output = safe_execute(interp, prog)

        result_ok = (result == expected_result)
        output_ok = (output == expected_output)

        if result_ok and output_ok:
            print(f"  PASS  {name}")
            passed += 1
        else:
            parts = []
            if not result_ok:
                parts.append(f"result={result!r}, expected={expected_result!r}")
            if not output_ok:
                parts.append(f"output={output!r}, expected={expected_output!r}")
            print(f"  FAIL  {name}: {'; '.join(parts)}")
            failed += 1

    total = passed + failed
    print(f"\n{'=' * 40}")
    print(f"Results: {passed}/{total} tests passed")
    if failed > 0:
        print(f"         {failed} test(s) FAILED")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
