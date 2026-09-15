"""
Baseline accuracy profiler for floating-point expressions.

Demonstrates how to measure accuracy in bits by comparing float64
results against arbitrary-precision (mpmath) reference values.

This is a framework — you need to:
1. Parse expressions from /app/benchmarks.fpcore
2. Implement each as a Python function (float64)
3. Create matching reference functions using mpmath
4. Call profile_expression() to measure accuracy

Usage: pip3 install mpmath && python3 /app/tools/profiler.py
"""

import math
import random
import sys


def bits_of_accuracy(approx_f64, exact_f64):
    """
    Compute bits of accuracy between a float64 approximation
    and a reference value (already cast to float from mpmath).

    Returns a value in [0, 53] where 53 = full float64 precision.
    """
    if math.isnan(approx_f64) or math.isinf(approx_f64):
        return 0.0
    if exact_f64 == 0.0:
        return 53.0 if approx_f64 == 0.0 else 0.0
    rel_err = abs(approx_f64 - exact_f64) / abs(exact_f64)
    if rel_err == 0.0:
        return 53.0
    return max(0.0, min(53.0, -math.log2(rel_err)))


def log_uniform_sample(lo, hi, rng):
    """Sample from log-uniform distribution (useful for wide ranges)."""
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def profile_expression(name, func_f64, ref_func_mp, sample_points,
                       mp_module, multivar=False):
    """
    Profile a single expression's accuracy.

    Args:
        name: Display name
        func_f64: float64 implementation (e.g., lambda x: math.sqrt(x+1) - math.sqrt(x))
        ref_func_mp: mpmath reference (e.g., lambda x, mp: mp.sqrt(x+1) - mp.sqrt(x))
        sample_points: list of input values (or tuples for multivar)
        mp_module: the mpmath mp object (with dps already set)
        multivar: True if expression takes multiple arguments
    """
    total_bits = 0.0
    count = 0
    for pt in sample_points:
        try:
            if multivar:
                mp_args = [mp_module.mpf(p) for p in pt]
                exact = float(ref_func_mp(*mp_args, mp_module))
                approx = func_f64(*pt)
            else:
                exact = float(ref_func_mp(mp_module.mpf(pt), mp_module))
                approx = func_f64(pt)
            total_bits += bits_of_accuracy(approx, exact)
            count += 1
        except (OverflowError, ValueError, ZeroDivisionError):
            count += 1
    avg = total_bits / count if count > 0 else 0.0
    print(f"  {name}: {avg:.1f} / 53.0 avg bits of accuracy ({count} samples)")
    return avg


if __name__ == "__main__":
    try:
        from mpmath import mp
        mp.dps = 60
    except ImportError:
        print("ERROR: mpmath is required.")
        print("Install with: pip3 install mpmath")
        sys.exit(1)

    rng = random.Random(42)
    N = 500

    print("=" * 55)
    print("Baseline Accuracy Profiler")
    print("=" * 55)
    print()
    print("This tool provides the measurement framework.")
    print("To profile expressions, parse them from the FPCore")
    print("benchmark file and add them to this script, or")
    print("build your own measurement pipeline.")
    print()
    print("Example usage (for a hypothetical expression):")
    print()
    print("  # float64 version")
    print("  def naive(x): return math.sqrt(x + 1) - 1")
    print()
    print("  # mpmath reference")
    print("  def ref(x, mp): return mp.sqrt(x + 1) - 1")
    print()
    print("  points = [log_uniform_sample(0.001, 1.0, rng)")
    print("            for _ in range(500)]")
    print("  profile_expression('example', naive, ref, points, mp)")
    print()
