#!/usr/bin/env python3
"""Validate design_matrix against reference golden outputs."""

import json
import sys
import os


def main():
    ref_dir = sys.argv[1] if len(sys.argv) > 1 else "/app/reference"

    try:
        import numpy as np
    except ImportError:
        print("ERROR: numpy required. Run: pip3 install numpy", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, "/app")
    try:
        from design_matrix import dmatrix
    except ImportError as e:
        print(f"ERROR: cannot import design_matrix: {e}", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0

    for fname in sorted(os.listdir(ref_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(ref_dir, fname)) as f:
            suite = json.load(f)
        for tc in suite["test_cases"]:
            name = f"{fname}::{tc['name']}"
            try:
                cols, mat = dmatrix(tc["formula"], tc["data"])
                if cols != tc["expected_columns"]:
                    print(
                        f"FAIL {name}: columns\n"
                        f"  got:      {cols}\n"
                        f"  expected: {tc['expected_columns']}"
                    )
                    failed += 1
                elif not np.allclose(mat, tc["expected_matrix"], atol=1e-6):
                    print(f"FAIL {name}: matrix values mismatch")
                    failed += 1
                else:
                    print(f"  ok {name}")
                    passed += 1
            except Exception as e:
                print(f"ERROR {name}: {type(e).__name__}: {e}")
                failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} reference cases passed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
