#!/usr/bin/env python3
"""
Compile all mini-Effekt test programs to Guile Scheme and validate
that the compiled output matches the Python interpreter.

"""

import importlib.util
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "/app")

from effekt import UNIT
from effekt_to_scheme import compile_program

PROGRAMS_DIR = "/app/programs"


def load_module(name, filepath):
    """Dynamically load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_result_str(result_str, expected):
    """Compare a Scheme output result string against an expected Python value."""
    if result_str is None:
        return False
    if expected is UNIT or (hasattr(expected, "__class__")
                            and expected.__class__.__name__ == "Unit"):
        return result_str == "()"
    if isinstance(expected, bool):
        return result_str == str(expected)
    if isinstance(expected, int):
        try:
            return int(result_str) == expected
        except (ValueError, TypeError):
            return False
    if isinstance(expected, str):
        return result_str == expected
    return str(expected) == result_str


def main():
    files = sorted(f for f in os.listdir(PROGRAMS_DIR)
                   if f.endswith(".py") and not f.startswith("_"))

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

        # Compile AST to Scheme
        try:
            scheme_code = compile_program(prog)
        except Exception as e:
            print(f"  FAIL  {name}: compilation error ({e})")
            failed += 1
            continue

        # Write to temp file and run through Guile
        fd, tmp = tempfile.mkstemp(suffix=".scm")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(scheme_code)
            result = subprocess.run(
                ["guile", "--no-auto-compile", "-s", tmp],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            print(f"  FAIL  {name}: Guile timeout")
            failed += 1
            continue
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

        if result.returncode != 0:
            print(f"  FAIL  {name}: Guile error: {result.stderr.strip()}")
            failed += 1
            continue

        # Parse output
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []

        marker_idx = None
        for i, line in enumerate(lines):
            if line.strip() == "---RESULT---":
                marker_idx = i
                break

        if marker_idx is None:
            print(f"  FAIL  {name}: no ---RESULT--- marker in output")
            failed += 1
            continue

        scheme_output = lines[:marker_idx]
        scheme_result = (lines[marker_idx + 1].strip()
                         if marker_idx + 1 < len(lines) else "")

        output_ok = scheme_output == expected_output
        result_ok = parse_result_str(scheme_result, expected_result)

        if result_ok and output_ok:
            print(f"  PASS  {name}")
            passed += 1
        else:
            parts = []
            if not result_ok:
                parts.append(
                    f"result='{scheme_result}', expected={expected_result!r}")
            if not output_ok:
                parts.append(
                    f"output={scheme_output!r}, expected={expected_output!r}")
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
