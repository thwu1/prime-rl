#!/usr/bin/env python3

"""
Generate all solution artifacts for the FPCore-to-C accuracy optimization pipeline.

Produces: improved.c, improved.h, Makefile, libimproved.so, bindings.py, report.json
"""

import os
import sys
import json
import subprocess
import ctypes
import math

import mpmath
mpmath.mp.dps = 50

# ---------------------------------------------------------------------------
# File contents
# ---------------------------------------------------------------------------

IMPROVED_H = """\
#ifndef IMPROVED_H
#define IMPROVED_H

double improved_sqrt_diff(double x);
double improved_cos_cancellation(double x);
double improved_log_ratio(double x);
double improved_quadratic_root(double a, double b, double c);
double improved_exp_cancel(double x);
double improved_hamming_expq3(double a, double b, double eps);

#endif
"""

IMPROVED_C = """\
#include <math.h>
#include "improved.h"

/* sqrt(x+1) - sqrt(x) via conjugate rationalization:
   Multiply by (sqrt(x+1)+sqrt(x))/(sqrt(x+1)+sqrt(x)) to get
   1/(sqrt(x+1)+sqrt(x)), avoiding subtraction cancellation. */
double improved_sqrt_diff(double x) {
    return 1.0 / (sqrt(x + 1.0) + sqrt(x));
}

/* (1-cos(x))/x^2 via half-angle identity:
   1-cos(x) = 2*sin^2(x/2), so the expression becomes
   2*sin^2(x/2)/x^2, which is stable because sin(x/2) ~ x/2. */
double improved_cos_cancellation(double x) {
    double s = sin(x / 2.0);
    return 2.0 * s * s / (x * x);
}

/* log((1-x)/(1+x)) via log1p decomposition:
   log((1-x)/(1+x)) = log(1+(-x)) - log(1+x) = log1p(-x) - log1p(x).
   log1p is designed to be accurate when its argument is near zero. */
double improved_log_ratio(double x) {
    return log1p(-x) - log1p(x);
}

/* (-b+sqrt(b^2-4ac))/(2a) via rationalization:
   When b >= 0, -b+d cancels. Multiply num/den by (-b-d)/(-b-d):
   (-b+d)(-b-d) / (2a(-b-d)) = (b^2-d^2)/(2a(-b-d)) = -4ac/(2a(-b-d))
   = 2c/(-b-d), which avoids the cancellation. */
double improved_quadratic_root(double a, double b, double c) {
    double disc = b * b - 4.0 * a * c;
    double d = sqrt(disc);
    if (b >= 0.0) {
        return (2.0 * c) / (-b - d);
    } else {
        return (-b + d) / (2.0 * a);
    }
}

/* 2*(exp(x)-1-x)/x^2 via Taylor series + expm1 regime:
   For |x| < 0.1: Taylor expansion 1 + x/3 + x^2/12 + ... in Horner form.
   For |x| >= 0.1: use expm1(x) to get exp(x)-1 accurately. */
double improved_exp_cancel(double x) {
    if (x == 0.0) return 1.0;
    if (fabs(x) < 0.1) {
        return 1.0 + x * (1.0/3.0 + x * (1.0/12.0 + x * (1.0/60.0
                + x * (1.0/360.0 + x * (1.0/2520.0 + x * (1.0/20160.0
                + x * (1.0/181440.0 + x * (1.0/1814400.0
                + x / 19958400.0))))))));
    } else {
        return 2.0 * (expm1(x) - x) / (x * x);
    }
}

/* eps*(exp((a+b)*eps)-1) / ((exp(a*eps)-1)*(exp(b*eps)-1)) via expm1:
   Replace each exp(y)-1 with expm1(y) for accurate evaluation when
   y is small. As eps->0, this correctly approaches 1/a + 1/b. */
double improved_hamming_expq3(double a, double b, double eps) {
    double numer = eps * expm1((a + b) * eps);
    double denom = expm1(a * eps) * expm1(b * eps);
    return numer / denom;
}
"""

# Makefile with actual tab characters in recipes
MAKEFILE = "CC = gcc\nCFLAGS = -O2 -Wall -fPIC\nLDFLAGS = -shared -lm\n\nall: libimproved.so\n\nlibimproved.so: improved.c improved.h\n\t$(CC) $(CFLAGS) $(LDFLAGS) -o $@ improved.c\n\nlibnaive.so: naive.c naive.h\n\t$(CC) $(CFLAGS) $(LDFLAGS) -o $@ naive.c\n\nclean:\n\trm -f libimproved.so libnaive.so\n\n.PHONY: all clean\n"

BINDINGS_PY = """\
import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libimproved.so')
_lib = ctypes.CDLL(_lib_path)

_lib.improved_sqrt_diff.argtypes = [ctypes.c_double]
_lib.improved_sqrt_diff.restype = ctypes.c_double

_lib.improved_cos_cancellation.argtypes = [ctypes.c_double]
_lib.improved_cos_cancellation.restype = ctypes.c_double

_lib.improved_log_ratio.argtypes = [ctypes.c_double]
_lib.improved_log_ratio.restype = ctypes.c_double

_lib.improved_quadratic_root.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.improved_quadratic_root.restype = ctypes.c_double

_lib.improved_exp_cancel.argtypes = [ctypes.c_double]
_lib.improved_exp_cancel.restype = ctypes.c_double

_lib.improved_hamming_expq3.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double]
_lib.improved_hamming_expq3.restype = ctypes.c_double


def improved_sqrt_diff(x):
    return _lib.improved_sqrt_diff(x)

def improved_cos_cancellation(x):
    return _lib.improved_cos_cancellation(x)

def improved_log_ratio(x):
    return _lib.improved_log_ratio(x)

def improved_quadratic_root(a, b, c):
    return _lib.improved_quadratic_root(a, b, c)

def improved_exp_cancel(x):
    return _lib.improved_exp_cancel(x)

def improved_hamming_expq3(a, b, eps):
    return _lib.improved_hamming_expq3(a, b, eps)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def relative_error(computed, reference_mp):
    ref_float = float(reference_mp)
    if ref_float == 0.0:
        return abs(computed)
    return abs((computed - ref_float) / ref_float)


# Naive Python implementations (matching naive.c)
def naive_sqrt_diff(x):
    return math.sqrt(x + 1) - math.sqrt(x)

def naive_cos_cancellation(x):
    return (1 - math.cos(x)) / (x * x)

def naive_log_ratio(x):
    return math.log((1 - x) / (1 + x))

def naive_quadratic_root(a, b, c):
    d = math.sqrt(b * b - 4 * a * c)
    return (-b + d) / (2 * a)

def naive_exp_cancel(x):
    return 2 * (math.exp(x) - 1 - x) / (x * x)

def naive_hamming_expq3(a, b, eps):
    numer = eps * (math.exp((a + b) * eps) - 1)
    denom = (math.exp(a * eps) - 1) * (math.exp(b * eps) - 1)
    return numer / denom


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # 1. Write source files
    with open('/app/improved.h', 'w') as f:
        f.write(IMPROVED_H)
    with open('/app/improved.c', 'w') as f:
        f.write(IMPROVED_C)
    with open('/app/Makefile', 'w') as f:
        f.write(MAKEFILE)
    with open('/app/bindings.py', 'w') as f:
        f.write(BINDINGS_PY)
    print("Wrote improved.c, improved.h, Makefile, bindings.py")

    # 2. Build shared library
    result = subprocess.run(
        ['make', '-C', '/app', 'libimproved.so'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Build failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Built libimproved.so")

    # 3. Load improved library via ctypes
    lib = ctypes.CDLL('/app/libimproved.so')
    lib.improved_sqrt_diff.argtypes = [ctypes.c_double]
    lib.improved_sqrt_diff.restype = ctypes.c_double
    lib.improved_cos_cancellation.argtypes = [ctypes.c_double]
    lib.improved_cos_cancellation.restype = ctypes.c_double
    lib.improved_log_ratio.argtypes = [ctypes.c_double]
    lib.improved_log_ratio.restype = ctypes.c_double
    lib.improved_quadratic_root.argtypes = [ctypes.c_double] * 3
    lib.improved_quadratic_root.restype = ctypes.c_double
    lib.improved_exp_cancel.argtypes = [ctypes.c_double]
    lib.improved_exp_cancel.restype = ctypes.c_double
    lib.improved_hamming_expq3.argtypes = [ctypes.c_double] * 3
    lib.improved_hamming_expq3.restype = ctypes.c_double

    # 4. Generate accuracy report
    report = []

    # sqrt_diff
    test_x = [0.01, 0.5, 1.0, 100.0, 1e4, 1e6, 1e8, 1e10, 1e12, 1e15]
    naive_errs, improved_errs = [], []
    for x in test_x:
        xmp = mpmath.mpf(x)
        ref = mpmath.sqrt(xmp + 1) - mpmath.sqrt(xmp)
        naive_errs.append(relative_error(naive_sqrt_diff(x), ref))
        improved_errs.append(relative_error(lib.improved_sqrt_diff(x), ref))
    report.append({
        'name': 'sqrt_diff',
        'naive_max_relerr': max(naive_errs),
        'improved_max_relerr': max(improved_errs),
        'improvement_ratio': max(naive_errs) / max(max(improved_errs), 1e-300),
        'test_points_count': len(test_x)
    })

    # cos_cancellation
    test_x = [1.0, 0.5, 0.1, 0.01, 1e-4, 1e-6, 1e-8, 1e-10, 1e-12]
    naive_errs, improved_errs = [], []
    for x in test_x:
        xmp = mpmath.mpf(x)
        ref = (1 - mpmath.cos(xmp)) / (xmp * xmp)
        naive_errs.append(relative_error(naive_cos_cancellation(x), ref))
        improved_errs.append(relative_error(lib.improved_cos_cancellation(x), ref))
    report.append({
        'name': 'cos_cancellation',
        'naive_max_relerr': max(naive_errs),
        'improved_max_relerr': max(improved_errs),
        'improvement_ratio': max(naive_errs) / max(max(improved_errs), 1e-300),
        'test_points_count': len(test_x)
    })

    # log_ratio
    test_x = [0.5, 0.1, 0.01, 1e-4, 1e-8, 1e-12, 1e-15, 1e-16]
    naive_errs, improved_errs = [], []
    for x in test_x:
        xmp = mpmath.mpf(x)
        ref = mpmath.log((1 - xmp) / (1 + xmp))
        naive_errs.append(relative_error(naive_log_ratio(x), ref))
        improved_errs.append(relative_error(lib.improved_log_ratio(x), ref))
    report.append({
        'name': 'log_ratio',
        'naive_max_relerr': max(naive_errs),
        'improved_max_relerr': max(improved_errs),
        'improvement_ratio': max(naive_errs) / max(max(improved_errs), 1e-300),
        'test_points_count': len(test_x)
    })

    # quadratic_root
    test_cases = [
        (1, 1e8, 1), (1, 1e10, 0.5), (1, 1e12, 0.5),
        (2, 1e6, 3), (1, 1e14, 0.25), (1, -3, 2), (1, -10, 24),
    ]
    naive_errs, improved_errs = [], []
    for a, b, c in test_cases:
        amp, bmp, cmp = mpmath.mpf(a), mpmath.mpf(b), mpmath.mpf(c)
        d = mpmath.sqrt(bmp * bmp - 4 * amp * cmp)
        ref = (-bmp + d) / (2 * amp)
        naive_errs.append(relative_error(naive_quadratic_root(a, b, c), ref))
        improved_errs.append(relative_error(
            lib.improved_quadratic_root(float(a), float(b), float(c)), ref))
    report.append({
        'name': 'quadratic_root',
        'naive_max_relerr': max(naive_errs),
        'improved_max_relerr': max(improved_errs),
        'improvement_ratio': max(naive_errs) / max(max(improved_errs), 1e-300),
        'test_points_count': len(test_cases)
    })

    # exp_cancel
    test_x = [2.0, 1.0, 0.5, 0.1, 0.01, 1e-4, 1e-6, 1e-8, 1e-10, 1e-14]
    naive_errs, improved_errs = [], []
    for x in test_x:
        xmp = mpmath.mpf(x)
        ref = 2 * (mpmath.exp(xmp) - 1 - xmp) / (xmp * xmp)
        naive_errs.append(relative_error(naive_exp_cancel(x), ref))
        improved_errs.append(relative_error(lib.improved_exp_cancel(x), ref))
    report.append({
        'name': 'exp_cancel',
        'naive_max_relerr': max(naive_errs),
        'improved_max_relerr': max(improved_errs),
        'improvement_ratio': max(naive_errs) / max(max(improved_errs), 1e-300),
        'test_points_count': len(test_x)
    })

    # hamming_expq3
    test_cases = [
        (3, 5, 1.0), (3, 5, 0.01), (3, 5, 1e-4),
        (3, 5, 1e-8), (3, 5, 1e-12), (3, 5, 1e-15),
        (1, 1, 1e-10), (2, 7, 1e-14), (10, 3, 1e-6),
    ]
    naive_errs, improved_errs = [], []
    for a, b, eps in test_cases:
        amp, bmp, epsmp = mpmath.mpf(a), mpmath.mpf(b), mpmath.mpf(eps)
        numer = epsmp * (mpmath.exp((amp + bmp) * epsmp) - 1)
        denom = (mpmath.exp(amp * epsmp) - 1) * (mpmath.exp(bmp * epsmp) - 1)
        ref = numer / denom
        naive_errs.append(relative_error(
            naive_hamming_expq3(a, b, eps), ref))
        improved_errs.append(relative_error(
            lib.improved_hamming_expq3(float(a), float(b), float(eps)), ref))
    report.append({
        'name': 'hamming_expq3',
        'naive_max_relerr': max(naive_errs),
        'improved_max_relerr': max(improved_errs),
        'improvement_ratio': max(naive_errs) / max(max(improved_errs), 1e-300),
        'test_points_count': len(test_cases)
    })

    # 5. Write report
    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Generated report.json")

    # Summary
    print("\nAccuracy Report Summary:")
    for entry in report:
        print(f"  {entry['name']}: naive={entry['naive_max_relerr']:.2e}, "
              f"improved={entry['improved_max_relerr']:.2e}, "
              f"ratio={entry['improvement_ratio']:.1f}x")

    print("\nAll artifacts created successfully.")


if __name__ == '__main__':
    main()
