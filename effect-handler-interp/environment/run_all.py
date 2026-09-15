#!/usr/bin/env python3

"""Run all example programs and check outputs against .expected files."""

import sys
import os
import glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import parse
from eval import Interpreter


def run_all():
    examples_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")
    eff_files = sorted(glob.glob(os.path.join(examples_dir, "*.eff")))
    passed = 0
    failed = 0
    errors = 0

    for eff_file in eff_files:
        name = os.path.basename(eff_file)
        expected_file = eff_file.replace(".eff", ".expected")
        if not os.path.exists(expected_file):
            print(f"  SKIP  {name} (no .expected file)")
            continue

        with open(expected_file) as f:
            expected = f.read().strip()

        try:
            with open(eff_file) as f:
                source = f.read()
            prog = parse(source)
            interp = Interpreter()
            result, output = interp.run(prog)
            output = output.strip()

            if output == expected:
                print(f"  PASS  {name}")
                passed += 1
            else:
                print(f"  FAIL  {name}")
                print(f"    expected: {expected!r}")
                print(f"    got:      {output!r}")
                failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            errors += 1

    total = passed + failed + errors
    print(f"\n{passed} passed, {failed} failed, {errors} errors out of {total}")
    return failed == 0 and errors == 0


if __name__ == '__main__':
    success = run_all()
    sys.exit(0 if success else 1)
