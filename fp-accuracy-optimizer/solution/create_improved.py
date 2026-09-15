"""
Generate improved floating-point functions using regime-based rewrites
verified against arbitrary-precision computation.

Each expression requires domain splitting because no single algebraic identity
resolves the instability across the full input range.
"""

from mpmath import mp, mpf
import math

mp.dps = 200  # 200-digit precision for verification


def verify_rewrite(name, original_mp, improved_py, test_points, multivar=False):
    """Verify that a float64 rewrite matches the high-precision original."""
    for pt in test_points:
        if multivar:
            orig_val = original_mp(*[mpf(p) for p in pt])
            impr_val = improved_py(*pt)
        else:
            orig_val = original_mp(mpf(pt))
            impr_val = improved_py(pt)

        exact = float(orig_val)
        if exact == 0:
            continue
        rel_err = abs(impr_val - exact) / abs(exact)
        assert rel_err < 1e-10, (
            f"{name}: mismatch at {pt}: exact={exact}, improved={impr_val}, rel_err={rel_err}"
        )
    print(f"  [OK] {name}: verified at {len(test_points)} points")


print("Verifying regime-based rewrites...")

# --- Expression 1: (exp(x) - 1 - x) / x^2 ---
# Second-order cancellation: exp(x) ~ 1+x near zero, so numerator
# exp(x)-1-x ~ x^2/2 loses all significance in float64.
# Even expm1(x)-x suffers cancellation for very small x.
# Solution: Taylor series for |x|<0.002, expm1-based for larger |x|.
# Taylor: (exp(x)-1-x)/x^2 = sum_{k=0}^inf x^k/(k+2)! = 1/2 + x/6 + x^2/24 + ...

def improved_1_py(x):
    ax = abs(x)
    if ax < 0.002:
        return 0.5 + x * (1/6 + x * (1/24 + x * (1/120 + x * (1/720 + x * (1/5040 + x * (1/40320 + x / 362880))))))
    else:
        return (math.expm1(x) - x) / (x * x)

verify_rewrite(
    "second-order exp",
    lambda x: (mp.exp(x) - 1 - x) / (x * x),
    improved_1_py,
    [1e-12, 1e-8, 1e-4, 0.001, 0.01, 0.1, 1.0, 5.0, -1e-4, -0.001, -0.1, -5.0],
)


# --- Expression 2: coth(x) - 1/x (Langevin function) ---
# Both coth(x) and 1/x diverge as x->0, but their difference L(x)->x/3.
# Naive float64 subtraction of two large quantities destroys all significance.
# Solution: for small x, Bernoulli-number Laurent series
#   L(x) = x/3 - x^3/45 + 2x^5/945 - x^7/4725 + 2x^9/93555
#           - 1382x^11/638512875 + 4x^13/18243225
# For larger x: rewrite as 1 + 2/expm1(2x) - 1/x (stable when x >= 0.3).

def improved_2_py(x):
    if x < 0.3:
        x2 = x * x
        return x * (1/3 + x2 * (-1/45 + x2 * (2/945 + x2 * (-1/4725 + x2 * (2/93555 + x2 * (-1382/638512875 + x2 * (4/18243225)))))))
    else:
        return 1.0 + 2.0 / math.expm1(2.0 * x) - 1.0 / x

verify_rewrite(
    "Langevin function",
    lambda x: (mp.exp(x) + mp.exp(-x)) / (mp.exp(x) - mp.exp(-x)) - 1 / x,
    improved_2_py,
    [1e-6, 1e-4, 0.01, 0.1, 0.29, 0.3, 0.5, 1.0, 5.0, 10.0],
)


# --- Expression 3: (sin(x) - x*cos(x)) / (x - sin(x)) ---
# Both numerator and denominator vanish cubically as x->0, creating a 0/0
# indeterminate form with limiting value 2. No single identity resolves this.
# Solution: independently expand numerator and denominator as power series,
# cancel x^3, and compute the ratio of the remaining polynomials.
# Numerator/x^3 = 1/3 - x^2/30 + x^4/840 - x^6/45360 + x^8/3991680
# Denominator/x^3 = 1/6 - x^2/120 + x^4/5040 - x^6/362880 + x^8/39916800

def improved_3_py(x):
    if x < 0.3:
        x2 = x * x
        num = 1/3 + x2 * (-1/30 + x2 * (1/840 + x2 * (-1/45360 + x2 * (1/3991680))))
        den = 1/6 + x2 * (-1/120 + x2 * (1/5040 + x2 * (-1/362880 + x2 * (1/39916800))))
        return num / den
    else:
        return (math.sin(x) - x * math.cos(x)) / (x - math.sin(x))

verify_rewrite(
    "trig indeterminate",
    lambda x: (mp.sin(x) - x * mp.cos(x)) / (x - mp.sin(x)),
    improved_3_py,
    [1e-8, 1e-6, 1e-4, 0.001, 0.01, 0.1, 0.29, 0.3, 0.5, 1.0, 2.0, 3.0],
)


# --- Expression 4: (exp(x) - exp(y)) / (x - y) ---
# When x ~ y, both numerator and denominator are tiny, magnifying rounding error.
# Solution: let m = (x+y)/2, d = (x-y)/2. Then:
#   exp(x)-exp(y) = 2*exp(m)*sinh(d), and x-y = 2d.
#   Result = exp(m) * sinh(d)/d.
# For small d, use Taylor: sinh(d)/d = 1 + d^2/6 + d^4/120 + d^6/5040 + d^8/362880

def improved_4_py(x, y):
    d = x - y
    if abs(d) < 1e-4:
        m = (x + y) / 2.0
        hd = d / 2.0
        hd2 = hd * hd
        sinhc = 1.0 + hd2 * (1/6 + hd2 * (1/120 + hd2 * (1/5040 + hd2 / 362880)))
        return math.exp(m) * sinhc
    else:
        return (math.exp(x) - math.exp(y)) / (x - y)

verify_rewrite(
    "exp difference quotient",
    lambda x, y: (mp.exp(x) - mp.exp(y)) / (x - y),
    improved_4_py,
    [(1.0, 1.0 + 1e-10), (0.0, 1e-12), (5.0, 5.0 + 1e-8), (-3.0, -3.0 + 1e-6),
     (1.0, 2.0), (0.0, 10.0), (-5.0, 5.0)],
    multivar=True,
)

print("\nAll rewrites verified. Writing /app/improved.py ...")

improved_code = '''"""
Regime-based numerically stabilized floating-point expressions.
Each function uses domain splitting to avoid catastrophic cancellation.
"""
import math


def improved_1(x):
    """
    (exp(x) - 1 - x) / x^2: second-order cancellation near x=0.
    Small |x|: Taylor series 1/2 + x/6 + x^2/24 + ...
    Larger |x|: (expm1(x) - x) / x^2
    """
    ax = abs(x)
    if ax < 0.002:
        return 0.5 + x * (1/6 + x * (1/24 + x * (1/120 + x * (1/720 + x * (1/5040 + x * (1/40320 + x / 362880))))))
    else:
        return (math.expm1(x) - x) / (x * x)


def improved_2(x):
    """
    coth(x) - 1/x (Langevin function): divergent terms cancel near x=0.
    Small x: Bernoulli-number series x/3 - x^3/45 + 2x^5/945 - ...
    Larger x: 1 + 2/expm1(2x) - 1/x
    """
    if x < 0.3:
        x2 = x * x
        return x * (1/3 + x2 * (-1/45 + x2 * (2/945 + x2 * (-1/4725 + x2 * (2/93555 + x2 * (-1382/638512875 + x2 * (4/18243225)))))))
    else:
        return 1.0 + 2.0 / math.expm1(2.0 * x) - 1.0 / x


def improved_3(x):
    """
    (sin(x) - x*cos(x)) / (x - sin(x)): 0/0 indeterminate form near x=0.
    Small x: ratio of independent power series for numerator and denominator.
    Larger x: direct computation.
    """
    if x < 0.3:
        x2 = x * x
        num = 1/3 + x2 * (-1/30 + x2 * (1/840 + x2 * (-1/45360 + x2 * (1/3991680))))
        den = 1/6 + x2 * (-1/120 + x2 * (1/5040 + x2 * (-1/362880 + x2 * (1/39916800))))
        return num / den
    else:
        return (math.sin(x) - x * math.cos(x)) / (x - math.sin(x))


def improved_4(x, y):
    """
    (exp(x) - exp(y)) / (x - y): cancellation when x close to y.
    Use midpoint decomposition: exp((x+y)/2) * sinh((x-y)/2) / ((x-y)/2).
    Small d = x-y: Taylor series for sinh(d/2)/(d/2).
    Larger d: direct computation.
    """
    d = x - y
    if abs(d) < 1e-4:
        m = (x + y) / 2.0
        hd = d / 2.0
        hd2 = hd * hd
        sinhc = 1.0 + hd2 * (1/6 + hd2 * (1/120 + hd2 * (1/5040 + hd2 / 362880)))
        return math.exp(m) * sinhc
    else:
        return (math.exp(x) - math.exp(y)) / (x - y)
'''

with open('/app/improved.py', 'w') as f:
    f.write(improved_code)

print("Done. /app/improved.py written successfully.")
