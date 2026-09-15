#!/usr/bin/env python3
"""Cross-validate Python solver against Octave reference data."""

import numpy as np
import sys
import os

sys.path.insert(0, '/app')
from solver import phi, solve_ks


def main():
    ref_dir = '/app/reference'
    errors = []

    # 1. Check phi-function values
    phi_path = os.path.join(ref_dir, 'phi_coeffs.csv')
    if not os.path.isfile(phi_path):
        print(f"ERROR: {phi_path} not found")
        sys.exit(1)

    phi_data = np.loadtxt(phi_path, delimiter=',')
    z_vals = phi_data[:, 0]
    max_phi_err = 0.0

    for k in range(4):
        for i, z in enumerate(z_vals):
            py_val = float(np.real(phi(z, k)))
            oct_val = phi_data[i, k + 1]
            denom = max(abs(oct_val), 1e-15)
            err = abs(py_val - oct_val) / denom
            max_phi_err = max(max_phi_err, err)

    print(f"Max phi-function relative error: {max_phi_err:.2e}")
    if max_phi_err > 1e-8:
        errors.append(f"Phi-function error too large: {max_phi_err:.2e}")

    # 2. Check ETD4RK coefficients
    coeff_path = os.path.join(ref_dir, 'etd4rk_coeffs.csv')
    if not os.path.isfile(coeff_path):
        print(f"ERROR: {coeff_path} not found")
        sys.exit(1)

    coeff_data = np.loadtxt(coeff_path, delimiter=',')
    max_coeff_err = 0.0

    for i in range(coeff_data.shape[0]):
        hL = coeff_data[i, 0]
        p1 = float(np.real(phi(hL, 1)))
        p2 = float(np.real(phi(hL, 2)))
        p3 = float(np.real(phi(hL, 3)))

        py_a1 = p1 - 3 * p2 + 4 * p3
        py_a2 = 2 * (p2 - 2 * p3)
        py_a3 = -p2 + 4 * p3

        for py_val, oct_val in [
            (py_a1, coeff_data[i, 1]),
            (py_a2, coeff_data[i, 2]),
            (py_a3, coeff_data[i, 3]),
        ]:
            denom = max(abs(oct_val), 1e-15)
            err = abs(py_val - oct_val) / denom
            max_coeff_err = max(max_coeff_err, err)

    print(f"Max coefficient relative error: {max_coeff_err:.2e}")
    if max_coeff_err > 1e-8:
        errors.append(f"Coefficient error too large: {max_coeff_err:.2e}")

    # 3. Check KS solution
    ks_path = os.path.join(ref_dir, 'ks_ref.csv')
    if not os.path.isfile(ks_path):
        print(f"ERROR: {ks_path} not found")
        sys.exit(1)

    ks_ref = np.loadtxt(ks_path, delimiter=',')
    u_python = solve_ks(L=32 * np.pi, N=64, T=1.0, dt=0.0625)
    ks_err = np.max(np.abs(u_python - ks_ref))

    print(f"Max KS solution error vs Octave: {ks_err:.2e}")
    if ks_err > 0.01:
        errors.append(f"KS solution error too large: {ks_err:.2e}")

    if errors:
        print("\nVALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nVALIDATION PASSED")
        sys.exit(0)


if __name__ == '__main__':
    main()
