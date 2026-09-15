#!/usr/bin/env python3
"""
IEEE 754 Float32 ULP Conformance Auditor.

Reads test_data.json containing precomputed (input, output) pairs for math
functions encoded as hex float32. Computes ULP errors against infinitely-precise
reference values and determines pass/fail per OpenCL ULP tolerances.

Key implementation details:
- Uses mpmath at 200-bit precision for reference computation
- Correct ULP calculation at power-of-two boundaries (floor(log2) determines exponent)
- Subnormal numbers use fixed ULP of 2^(-149)
- FTZ mode: subnormal reference with ±0 output accepted as 0 ULP
- NaN/Inf propagation per IEEE 754
"""


import json
import math
import numpy as np
import mpmath

mpmath.mp.prec = 200

# Math function references using mpmath for arbitrary precision
MATH_REFS = {
    "sin": lambda x: mpmath.sin(x),
    "cos": lambda x: mpmath.cos(x),
    "tan": lambda x: mpmath.tan(x),
    "exp": lambda x: mpmath.exp(x),
    "exp2": lambda x: mpmath.power(2, x),
    "log": lambda x: mpmath.log(x),
    "log2": lambda x: mpmath.log(x) / mpmath.log(2),
    "sqrt": lambda x: mpmath.sqrt(x),
    "rsqrt": lambda x: 1 / mpmath.sqrt(x),
    "cbrt": lambda x: mpmath.cbrt(x) if x >= 0 else -mpmath.cbrt(-x),
    "asin": lambda x: mpmath.asin(x),
    "erfc": lambda x: mpmath.erfc(x),
}

FLOAT32_MIN_NORMAL = 2.0 ** (-126)  # ~1.175494e-38


def hex_to_f32(hex_str):
    """Convert 8-char hex string to numpy float32."""
    return np.uint32(int(hex_str, 16)).view(np.float32)


def compute_ulp_error(test_f32, ref_mpf, ftz_mode=False):
    """
    Compute ULP error of test_f32 relative to the infinitely precise ref_mpf.

    Returns the ULP error as a float. Handles:
    - NaN: NaN vs NaN = 0 ULP; NaN vs non-NaN = inf
    - Inf: matching infinities = 0 ULP; mismatch = inf
    - Zero: ±0 vs ±0 = 0 ULP
    - FTZ: if ref is subnormal and test is ±0, return 0 ULP
    - Power-of-two boundary: uses floor(log2(|ref|)) for exponent
    - Subnormals: fixed ULP of 2^(-149)
    """
    test_val = float(test_f32)

    # Handle NaN reference
    if mpmath.isnan(ref_mpf):
        return 0.0 if np.isnan(test_f32) else float('inf')

    # Handle infinite reference
    if mpmath.isinf(ref_mpf):
        if np.isinf(test_f32) and np.sign(test_val) == int(mpmath.sign(ref_mpf)):
            return 0.0
        return float('inf')

    # Handle NaN test value (non-NaN reference)
    if np.isnan(test_f32):
        return float('inf')

    # Handle infinite test value (finite reference)
    if np.isinf(test_f32):
        return float('inf')

    ref_float = float(ref_mpf)

    # Both zero
    if ref_float == 0.0 and test_val == 0.0:
        return 0.0

    # FTZ mode: if reference is subnormal and test is ±0, accept
    if ftz_mode and ref_float != 0.0:
        ref_abs = abs(ref_float)
        if 0 < ref_abs < FLOAT32_MIN_NORMAL and test_val == 0.0:
            return 0.0

    # Compute absolute difference at high precision
    test_mp = mpmath.mpf(test_val)
    diff = abs(test_mp - ref_mpf)

    if diff == 0:
        return 0.0

    # Compute ULP of the reference value
    ref_abs = abs(ref_float)
    if ref_abs == 0:
        # Reference is zero, use smallest representable ULP
        ulp = mpmath.mpf(2) ** (-149)
    elif ref_abs < FLOAT32_MIN_NORMAL:
        # Subnormal: fixed ULP
        ulp = mpmath.mpf(2) ** (-149)
    else:
        # Normal: ULP = 2^(exponent - 23) where exponent = floor(log2(|ref|))
        exponent = math.floor(math.log2(ref_abs))
        ulp = mpmath.mpf(2) ** (exponent - 23)

    return float(diff / ulp)


def audit_function(func_name, tolerance, test_cases, ftz_mode):
    """Audit a single math function against its test cases."""
    ref_func = MATH_REFS.get(func_name)
    if ref_func is None:
        return {
            "pass": False,
            "max_ulp_error": float('inf'),
            "num_test_cases": len(test_cases),
            "num_exceeding_tolerance": len(test_cases),
        }

    max_ulp = 0.0
    num_exceeding = 0

    for tc in test_cases:
        inp_f32 = hex_to_f32(tc["input_hex"])
        out_f32 = hex_to_f32(tc["output_hex"])
        inp_val = float(inp_f32)

        # Compute reference at high precision
        inp_mp = mpmath.mpf(inp_val)

        try:
            ref_mp = ref_func(inp_mp)
        except (ValueError, ZeroDivisionError):
            # Domain error - skip or handle
            continue

        # Handle complex results (e.g., log of negative)
        if isinstance(ref_mp, mpmath.mpc):
            # Expect NaN output
            if np.isnan(out_f32):
                continue
            else:
                num_exceeding += 1
                max_ulp = float('inf')
                continue

        ulp_err = compute_ulp_error(out_f32, ref_mp, ftz_mode=ftz_mode)

        if ulp_err > max_ulp:
            max_ulp = ulp_err

        if ulp_err > tolerance:
            num_exceeding += 1

    passes = max_ulp <= tolerance

    return {
        "pass": passes,
        "max_ulp_error": round(max_ulp, 2),
        "num_test_cases": len(test_cases),
        "num_exceeding_tolerance": num_exceeding,
    }


def main():
    with open("/app/test_data.json") as f:
        data = json.load(f)

    ftz_mode = data.get("ftz_mode", False)
    functions_data = data["functions"]

    results = {}
    failing = []

    for func_name, func_info in functions_data.items():
        tolerance = func_info["tolerance_ulp"]
        test_cases = func_info["test_cases"]

        result = audit_function(func_name, tolerance, test_cases, ftz_mode)
        results[func_name] = result

        if not result["pass"]:
            failing.append(func_name)

    report = {
        "functions": results,
        "overall_pass": len(failing) == 0,
        "functions_failing": sorted(failing),
    }

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete. {len(failing)} functions failing: {sorted(failing)}")
    for fn, r in sorted(results.items()):
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  {fn:8s}: max_ulp={r['max_ulp_error']:7.2f}, {status}")


if __name__ == "__main__":
    main()
