#!/usr/bin/env python3
"""Validate cross-decomposition analysis results.

"""
import sys
import numpy as np


def main():
    if len(sys.argv) < 2:
        print("Usage: validate_results.py <results.npz>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        data = np.load(path)
    except Exception as e:
        print(f"ERROR: Cannot load results from {path}: {e}", file=sys.stderr)
        sys.exit(1)

    sv = data['singular_values']
    scf = data['scf']

    errors = []

    if not np.all(sv > 0):
        errors.append("Singular values must be positive")

    if not np.all(np.diff(sv) <= 1e-10):
        errors.append("Singular values must be in descending order")

    if not np.all(scf >= -1e-15):
        errors.append("SCF values must be non-negative")

    if scf.sum() > 1.0 + 1e-10:
        errors.append(f"SCF sum {scf.sum():.6f} exceeds 1.0")

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("VALIDATION PASSED")
    for i, (s, f_val) in enumerate(zip(sv, scf)):
        print(f"  Mode {i+1}: sv={s:.6f}, scf={f_val:.4f}")


if __name__ == '__main__':
    main()
