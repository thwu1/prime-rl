#!/usr/bin/env python3
"""Precision audit of libfpmath.so — discovers numerical bugs via
arbitrary-precision comparison, classifies them, and writes audit_report.json."""


import ctypes
import json
import math
import struct
import subprocess

import mpmath

mpmath.mp.dps = 50


# ---------------------------------------------------------------------------
# ULP helpers
# ---------------------------------------------------------------------------

def compute_ulp_error(computed, reference_mpf):
    """Compute ULP error of a float32 result against an mpmath reference."""
    # Safety: if reference is complex (out-of-domain), treat as infinite error
    if isinstance(reference_mpf, mpmath.mpc):
        if reference_mpf.imag != 0:
            return float('inf')
        reference_mpf = reference_mpf.real

    if not math.isfinite(computed):
        ref_f64 = float(reference_mpf)
        if math.isnan(computed) and math.isnan(ref_f64):
            return 0.0
        if (math.isinf(computed) and math.isinf(ref_f64)
                and math.copysign(1.0, computed) == math.copysign(1.0, ref_f64)):
            return 0.0
        return float('inf')

    ref_f64 = float(reference_mpf)
    try:
        ref_f32 = struct.unpack('>f', struct.pack('>f', ref_f64))[0]
    except (OverflowError, struct.error):
        return float('inf')

    if computed == ref_f32:
        return 0.0
    if ref_f32 == 0.0:
        return abs(computed) / (2 ** -149)

    bits = struct.unpack('>I', struct.pack('>f', ref_f32))[0]
    exponent = (bits >> 23) & 0xFF
    if exponent == 0:
        ulp = 2 ** -149
    else:
        ulp = 2.0 ** (exponent - 127 - 23)

    return abs(computed - ref_f32) / ulp


# ---------------------------------------------------------------------------
# Reference computations using mpmath
# ---------------------------------------------------------------------------

def reference_value(name, inputs):
    mp_args = [mpmath.mpf(str(x)) for x in inputs]
    if name == 'fp_expm1':
        return mpmath.expm1(mp_args[0])
    elif name == 'fp_log1p':
        return mpmath.log1p(mp_args[0])
    elif name == 'fp_hypot':
        return mpmath.sqrt(mp_args[0] ** 2 + mp_args[1] ** 2)
    elif name == 'fp_sigmoid':
        return 1 / (1 + mpmath.exp(-mp_args[0]))
    elif name == 'fp_sinc':
        if mp_args[0] == 0:
            return mpmath.mpf(1)
        return mpmath.sin(mp_args[0]) / mp_args[0]
    elif name == 'fp_mean':
        return (mp_args[0] + mp_args[1]) / 2
    raise ValueError(name)


# ---------------------------------------------------------------------------
# C function calling via ctypes
# ---------------------------------------------------------------------------

def call_func(lib, name, inputs):
    func = getattr(lib, name)
    if len(inputs) == 1:
        func.argtypes = [ctypes.c_float]
        func.restype = ctypes.c_float
        return func(ctypes.c_float(inputs[0]))
    else:
        func.argtypes = [ctypes.c_float, ctypes.c_float]
        func.restype = ctypes.c_float
        return func(ctypes.c_float(inputs[0]), ctypes.c_float(inputs[1]))


# ---------------------------------------------------------------------------
# Targeted test input generation
# ---------------------------------------------------------------------------

FLT_MAX = struct.unpack('>f', b'\x7f\x7f\xff\xff')[0]


def generate_test_inputs(name):
    inputs = []
    if name == 'fp_expm1':
        # Near zero: catastrophic cancellation region
        for e in range(-40, 0):
            inputs.append([10.0 ** e])
            inputs.append([-10.0 ** e])
        for x in [0.1, 0.5, 1.0, 2.0, 10.0, 50.0, 80.0]:
            inputs.append([x])
            inputs.append([-x])
    elif name == 'fp_log1p':
        # Near zero: catastrophic cancellation region
        for e in range(-40, 0):
            inputs.append([10.0 ** e])
            inputs.append([-10.0 ** e])
        # Positive values (always in domain)
        for x in [0.1, 0.5, 1.0, 2.0, 10.0, 50.0, 80.0]:
            inputs.append([x])
        # Negative values: must satisfy x > -1 for log1p domain
        for x in [0.1, 0.5, 0.9, 0.99, 0.999]:
            inputs.append([-x])
    elif name == 'fp_hypot':
        for x in [1e19, 2e19, 1e20, 1e30, 1e38, FLT_MAX]:
            inputs.append([x, x])
            inputs.append([x, 0.0])
        inputs.append([3.0, 4.0])
        inputs.append([1.0, 1.0])
        inputs.append([0.0, 0.0])
    elif name == 'fp_sigmoid':
        for x in [0.0, 0.5, 1.0, -1.0, 10.0, -10.0, 50.0, -50.0, 80.0, -80.0]:
            inputs.append([x])
    elif name == 'fp_sinc':
        inputs.append([0.0])
        for x in [1e-10, 1e-7, 1e-5, 0.001, 0.1, 1.0, 2.0, 5.0, 10.0]:
            inputs.append([x])
            inputs.append([-x])
    elif name == 'fp_mean':
        inputs.append([FLT_MAX, FLT_MAX])
        inputs.append([-FLT_MAX, -FLT_MAX])
        inputs.append([FLT_MAX, FLT_MAX * 0.9])
        inputs.append([2e38, 2e38])
        inputs.append([1.0, 2.0])
        inputs.append([-1.0, 1.0])
    return inputs


# ---------------------------------------------------------------------------
# Main audit
# ---------------------------------------------------------------------------

def main():
    # Step 1: inspect exports
    result = subprocess.run(['nm', '-D', '/app/libfpmath.so'],
                            capture_output=True, text=True)
    print("=== Library exports ===")
    print(result.stdout)

    # Step 2: load library
    lib = ctypes.CDLL('/app/libfpmath.so')

    # Step 3: audit each function
    functions = ['fp_expm1', 'fp_log1p', 'fp_hypot', 'fp_sigmoid',
                 'fp_sinc', 'fp_mean']
    report = {"functions": {}}

    for name in functions:
        test_inputs = generate_test_inputs(name)
        max_ulp = 0.0
        worst_input = test_inputs[0] if test_inputs else [0.0]
        bug_type = None

        for args in test_inputs:
            c_result = call_func(lib, name, args)
            ref = reference_value(name, args)
            ulp_err = compute_ulp_error(c_result, ref)

            if ulp_err > max_ulp:
                max_ulp = ulp_err
                worst_input = args

                # Classify bug type
                if math.isnan(c_result) and not math.isnan(float(mpmath.re(ref))):
                    bug_type = 'special_value'
                elif math.isinf(c_result) and math.isfinite(float(mpmath.re(ref))):
                    bug_type = 'overflow'
                elif ulp_err > 100 and math.isfinite(c_result):
                    bug_type = 'catastrophic_cancellation'
                elif ulp_err > 4:
                    bug_type = 'precision_loss'

        classification = 'stable' if max_ulp <= 4 else 'unstable'

        entry = {
            "classification": classification,
            "max_ulp_error": max_ulp if math.isfinite(max_ulp) else 1e18,
            "worst_case_input": worst_input,
        }
        if classification == 'unstable':
            entry["bug_type"] = bug_type

        report["functions"][name] = entry
        print(f"{name}: {classification}, max_ulp={max_ulp}, "
              f"worst={worst_input}, bug_type={bug_type}")

    # Step 4: write report
    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("\nWrote /app/audit_report.json")


if __name__ == '__main__':
    main()
