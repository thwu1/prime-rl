#!/usr/bin/env python3
"""
Local validation tool for elliptic filter implementation.
Checks the implementation against reference data in reference_data/.

Usage: python3 tools/validate.py
"""

import json
import os
import sys
import glob
import traceback

import numpy as np


def zpk_freqresp(z, p, k, w):
    """Evaluate |H(jw)| from zpk representation."""
    s = 1j * w
    num = k
    for zi in z:
        num = num * (s - zi)
    den = 1.0
    for pi in p:
        den = den * (s - pi)
    return float(np.abs(num / den))


def validate_filter(ref_file):
    """Validate implementation against one reference data file."""
    with open(ref_file) as f:
        ref = json.load(f)

    N = ref["filter_order"]
    rp = ref["passband_ripple_dB"]
    rs = ref["stopband_attenuation_dB"]
    print(f"\n  Filter order={N}, rp={rp} dB, rs={rs} dB")

    from elliptic_filter import elliptic_filter_design
    z, p, k = elliptic_filter_design(N, rp, rs)
    z = np.array(z, dtype=complex)
    p = np.array(p, dtype=complex)

    errors = []

    # Check counts
    if len(z) != ref["n_zeros_expected"]:
        errors.append(f"    FAIL: expected {ref['n_zeros_expected']} zeros, got {len(z)}")
    if len(p) != ref["n_poles_expected"]:
        errors.append(f"    FAIL: expected {ref['n_poles_expected']} poles, got {len(p)}")

    # Check poles in LHP
    for pi in p:
        if pi.real >= 0:
            errors.append(f"    FAIL: pole {pi} not in left half-plane")

    # Check zeros on imaginary axis
    for zi in z:
        if abs(zi.real) > 1e-6:
            errors.append(f"    FAIL: zero {zi} not on imaginary axis")

    # Compare poles/zeros against reference (sorted by imag part)
    ref_z = np.array([complex(r, i) for r, i in ref["zeros"]])
    ref_p = np.array([complex(r, i) for r, i in ref["poles"]])

    z_sorted = z[np.argsort(np.imag(z))]
    p_sorted = p[np.argsort(np.imag(p))]
    ref_z_sorted = ref_z[np.argsort(np.imag(ref_z))]
    ref_p_sorted = ref_p[np.argsort(np.imag(ref_p))]

    if len(z_sorted) == len(ref_z_sorted):
        for j in range(len(z_sorted)):
            err = abs(z_sorted[j] - ref_z_sorted[j])
            if err > 1e-3:
                errors.append(f"    FAIL: zero[{j}] error {err:.2e} (got {z_sorted[j]}, ref {ref_z_sorted[j]})")
            else:
                print(f"    zero[{j}]: err={err:.2e} OK")

    if len(p_sorted) == len(ref_p_sorted):
        for j in range(len(p_sorted)):
            err = abs(p_sorted[j] - ref_p_sorted[j])
            if err > 1e-3:
                errors.append(f"    FAIL: pole[{j}] error {err:.2e} (got {p_sorted[j]}, ref {ref_p_sorted[j]})")
            else:
                print(f"    pole[{j}]: err={err:.2e} OK")

    # Check gain
    ref_gain = ref["gain"]
    gain_err = abs(k - ref_gain) / max(abs(ref_gain), 1e-15)
    if gain_err > 1e-2:
        errors.append(f"    FAIL: gain error {gain_err:.2e} (got {k}, ref {ref_gain})")
    else:
        print(f"    gain: relerr={gain_err:.2e} OK")

    # Check frequency response at sample points
    freq_errors = 0
    for w, expected_mag in ref["frequency_response_samples"]:
        actual_mag = zpk_freqresp(z, p, k, w)
        if abs(actual_mag - expected_mag) > 0.05:
            freq_errors += 1
    if freq_errors:
        errors.append(f"    FAIL: {freq_errors} frequency response sample(s) outside tolerance")
    else:
        print(f"    frequency response: {len(ref['frequency_response_samples'])} samples OK")

    return errors


def validate_functions():
    """Quick validation of underlying mathematical functions."""
    print("\n  Mathematical functions:")
    errors = []

    try:
        from elliptic_filter import complete_elliptic_K
        # K(0.5) should be approximately 1.8541
        val = complete_elliptic_K(0.5)
        if abs(val - 1.8541) > 0.5:
            errors.append(f"    FAIL: K(0.5) = {val}, expected ~1.854")
        else:
            print(f"    K(0.5) = {val:.10f} (plausible)")
    except Exception as e:
        errors.append(f"    FAIL: complete_elliptic_K error: {e}")

    try:
        from elliptic_filter import cd_jacobi
        val = cd_jacobi(0.0, 0.5)
        if abs(val - 1.0) > 1e-10:
            errors.append(f"    FAIL: cd(0, 0.5) = {val}, expected 1.0")
        else:
            print(f"    cd(0, 0.5) = {val} OK")
    except Exception as e:
        errors.append(f"    FAIL: cd_jacobi error: {e}")

    try:
        from elliptic_filter import sn_jacobi
        val = sn_jacobi(0.0, 0.5)
        if abs(val) > 1e-10:
            errors.append(f"    FAIL: sn(0, 0.5) = {val}, expected 0.0")
        else:
            print(f"    sn(0, 0.5) = {val} OK")
    except Exception as e:
        errors.append(f"    FAIL: sn_jacobi error: {e}")

    return errors


def main():
    print("=" * 60)
    print("Elliptic Filter Validation")
    print("=" * 60)

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    all_errors = []

    # Validate mathematical functions first
    try:
        all_errors.extend(validate_functions())
    except Exception as e:
        all_errors.append(f"  FAIL: function validation crashed: {e}")
        traceback.print_exc()

    # Validate against each reference data file
    ref_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reference_data")
    ref_files = sorted(glob.glob(os.path.join(ref_dir, "*.json")))

    if not ref_files:
        print("\n  WARNING: no reference data files found in reference_data/")
    else:
        print(f"\n  Found {len(ref_files)} reference data file(s)")
        for ref_file in ref_files:
            try:
                errs = validate_filter(ref_file)
                all_errors.extend(errs)
            except Exception as e:
                all_errors.append(f"  FAIL: {os.path.basename(ref_file)}: {e}")
                traceback.print_exc()

    print("\n" + "=" * 60)
    if all_errors:
        print(f"VALIDATION FAILED ({len(all_errors)} error(s)):")
        for e in all_errors:
            print(e)
        sys.exit(1)
    else:
        print("ALL VALIDATIONS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
