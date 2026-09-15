#!/usr/bin/env python3

"""
Generate improved floating-point implementations and verify their accuracy.

Each improved function uses a specific numerical stabilization technique:
1. Algebraic rationalization (conjugate multiplication)
2. Half-angle trigonometric identity
3. log1p decomposition
4. Rationalized quadratic formula
5. Taylor series with regime switching
6. expm1 substitution
"""

import os
import sys
import math

IMPROVED_CODE = r'''

"""
Numerically improved floating-point implementations.
Each function computes the same mathematical quantity as the corresponding
naive function in problems.py, but with better accuracy in regions where
the naive version suffers from catastrophic cancellation.
"""
import math


def improved_1(x):
    """sqrt(x+1) - sqrt(x) via conjugate rationalization.

    Multiply by (sqrt(x+1)+sqrt(x))/(sqrt(x+1)+sqrt(x)) to get
    1/(sqrt(x+1)+sqrt(x)), avoiding the cancellation in the subtraction.
    """
    return 1.0 / (math.sqrt(x + 1) + math.sqrt(x))


def improved_2(x):
    """(1-cos(x))/x^2 via half-angle identity.

    Uses 1-cos(x) = 2*sin(x/2)^2 to avoid the cancellation when
    cos(x) is close to 1. The expression 2*sin(x/2)^2/x^2 is
    numerically stable because sin(x/2) ~ x/2 for small x, giving
    a result near 1/2 without cancellation.
    """
    s = math.sin(x / 2.0)
    return 2.0 * s * s / (x * x)


def improved_3(x):
    """log((1-x)/(1+x)) via log1p decomposition.

    Rewrites as log1p(-x) - log1p(x), using the standard library
    function log1p which is designed to compute log(1+y) accurately
    for small y, avoiding the precision loss when (1-x)/(1+x) is
    close to 1.
    """
    return math.log1p(-x) - math.log1p(x)


def improved_4(a, b, c):
    """Quadratic root (-b+sqrt(b^2-4ac))/(2a) via rationalization.

    When b >= 0, the subtraction -b+d can cancel. Multiply numerator
    and denominator by (-b-d) and use d^2 = b^2-4ac to get
    2c/(-b-d), which avoids cancellation since both -b and -d have
    the same sign.
    """
    disc = b * b - 4.0 * a * c
    d = math.sqrt(disc)
    if b >= 0:
        # -b+d has cancellation; use rationalized form
        return (2.0 * c) / (-b - d)
    else:
        # -b is positive, d is positive; sum, no cancellation
        return (-b + d) / (2.0 * a)


def improved_5(x):
    """2*(exp(x)-1-x)/x^2 via Taylor series + expm1 regime.

    For |x| < 0.1: use Taylor expansion of the ratio,
      f(x) = sum_{k>=0} 2*x^k/(k+2)! = 1 + x/3 + x^2/12 + ...
    evaluated in Horner form for numerical stability.

    For |x| >= 0.1: use expm1(x) to get exp(x)-1 accurately, then
    subtract x and divide by x^2/2. At this range, expm1(x)-x
    retains sufficient relative precision.
    """
    if x == 0.0:
        return 1.0
    ax = abs(x)
    if ax < 0.1:
        # Taylor: 2*sum_{k>=0} x^k/(k+2)! = 1 + x/3 + x^2/12 + ...
        # Coefficients: c_k = 2/(k+2)! for k=0,1,2,...
        # Using Horner form with 10 terms (sufficient for |x|<0.1
        # to give error < 4e-18, well below machine epsilon)
        return (1.0 + x * (1.0/3.0 + x * (1.0/12.0 + x * (1.0/60.0
                + x * (1.0/360.0 + x * (1.0/2520.0 + x * (1.0/20160.0
                + x * (1.0/181440.0 + x * (1.0/1814400.0
                + x / 19958400.0)))))))))
    else:
        return 2.0 * (math.expm1(x) - x) / (x * x)


def improved_6(a, b, eps):
    """eps*(exp((a+b)*eps)-1)/((exp(a*eps)-1)*(exp(b*eps)-1)) via expm1.

    Replaces each exp(y)-1 with expm1(y), which is computed accurately
    by the math library even when y is very small (avoiding the
    cancellation in exp(y)-1 when exp(y) is close to 1).

    For very small eps, expm1(a*eps) ~ a*eps, so the expression
    reduces to eps*(a+b)*eps / (a*eps*b*eps) = (a+b)/(a*b) = 1/a+1/b,
    which is the correct limiting value.
    """
    numer = eps * math.expm1((a + b) * eps)
    denom = math.expm1(a * eps) * math.expm1(b * eps)
    return numer / denom
'''


def main():
    # Write the improved implementations to /app/improved.py
    output_path = '/app/improved.py'
    with open(output_path, 'w') as f:
        f.write(IMPROVED_CODE.strip() + '\n')
    print(f"Wrote improved implementations to {output_path}")

    # Verify the implementations against mpmath references
    import mpmath
    mpmath.mp.dps = 50

    sys.path.insert(0, '/app')
    from improved import (improved_1, improved_2, improved_3,
                          improved_4, improved_5, improved_6)

    def relerr(computed, ref_mp):
        ref = float(ref_mp)
        if ref == 0.0:
            return abs(computed)
        return abs((computed - ref) / ref)

    errors = []

    # Verify improved_1
    for x in [1e4, 1e8, 1e12, 1e15]:
        xmp = mpmath.mpf(x)
        ref = mpmath.sqrt(xmp + 1) - mpmath.sqrt(xmp)
        err = relerr(improved_1(x), ref)
        if err >= 1e-12:
            errors.append(f"improved_1({x}): relerr={err}")

    # Verify improved_2
    for x in [1e-4, 1e-8, 1e-10, 1e-12]:
        xmp = mpmath.mpf(x)
        ref = (1 - mpmath.cos(xmp)) / (xmp * xmp)
        err = relerr(improved_2(x), ref)
        if err >= 1e-12:
            errors.append(f"improved_2({x}): relerr={err}")

    # Verify improved_3
    for x in [1e-8, 1e-12, 1e-16, 5e-17]:
        xmp = mpmath.mpf(x)
        ref = mpmath.log((1 - xmp) / (1 + xmp))
        err = relerr(improved_3(x), ref)
        if err >= 1e-12:
            errors.append(f"improved_3({x}): relerr={err}")

    # Verify improved_4
    for a, b, c in [(1, 1e8, 1), (1, 1e12, 0.5), (1, -3, 2)]:
        amp, bmp, cmp = mpmath.mpf(a), mpmath.mpf(b), mpmath.mpf(c)
        d = mpmath.sqrt(bmp * bmp - 4 * amp * cmp)
        ref = (-bmp + d) / (2 * amp)
        err = relerr(improved_4(a, b, c), ref)
        if err >= 1e-12:
            errors.append(f"improved_4({a},{b},{c}): relerr={err}")

    # Verify improved_5
    for x in [1e-6, 1e-10, 1e-14, 0.5]:
        xmp = mpmath.mpf(x)
        ref = 2 * (mpmath.exp(xmp) - 1 - xmp) / (xmp * xmp)
        err = relerr(improved_5(x), ref)
        if err >= 1e-12:
            errors.append(f"improved_5({x}): relerr={err}")

    # Verify improved_6
    for a, b, eps in [(3, 5, 1e-8), (3, 5, 1e-15), (1, 1, 1e-10)]:
        amp, bmp, epsmp = mpmath.mpf(a), mpmath.mpf(b), mpmath.mpf(eps)
        numer = epsmp * (mpmath.exp((amp + bmp) * epsmp) - 1)
        denom = (mpmath.exp(amp * epsmp) - 1) * (mpmath.exp(bmp * epsmp) - 1)
        ref = numer / denom
        err = relerr(improved_6(a, b, eps), ref)
        if err >= 1e-12:
            errors.append(f"improved_6({a},{b},{eps}): relerr={err}")

    if errors:
        print("VERIFICATION FAILED:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print("All improved implementations verified successfully.")
        sys.exit(0)


if __name__ == '__main__':
    main()
