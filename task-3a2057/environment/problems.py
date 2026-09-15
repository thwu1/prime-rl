
"""
Naive floating-point implementations that suffer from accuracy loss.
Each function computes a well-defined mathematical expression but may lose
significant precision due to catastrophic cancellation or other numerical
issues in certain input regions.
"""
import math


def naive_1(x):
    """Compute sqrt(x+1) - sqrt(x) for x > 0.

    Suffers from catastrophic cancellation when x is large, because
    sqrt(x+1) and sqrt(x) become nearly equal.
    """
    return math.sqrt(x + 1) - math.sqrt(x)


def naive_2(x):
    """Compute (1 - cos(x)) / x^2 for x != 0.

    The mathematical limit as x -> 0 is 1/2. Suffers from cancellation
    when x is small because cos(x) approaches 1, causing 1-cos(x) to
    lose most of its significant digits.
    """
    return (1 - math.cos(x)) / (x * x)


def naive_3(x):
    """Compute log((1 - x) / (1 + x)) for |x| < 1.

    Suffers from precision loss when x is very small, because
    (1-x)/(1+x) approaches 1 and log(1) = 0, causing cancellation
    in both the division and the logarithm.
    """
    return math.log((1 - x) / (1 + x))


def naive_4(a, b, c):
    """Compute the quadratic root (-b + sqrt(b^2 - 4ac)) / (2a).

    Precondition: a != 0, b^2 - 4ac > 0.
    Suffers from catastrophic cancellation when b > 0 and |4ac| << b^2,
    because sqrt(b^2 - 4ac) is very close to |b|.
    """
    d = math.sqrt(b * b - 4 * a * c)
    return (-b + d) / (2 * a)


def naive_5(x):
    """Compute 2*(exp(x) - 1 - x) / x^2 for x != 0.

    The mathematical limit as x -> 0 is 1.
    Suffers from catastrophic cancellation near x=0 because exp(x)-1
    is very close to x, making exp(x)-1-x lose nearly all significant
    digits. The cancellation worsens as x approaches 0.
    """
    return 2 * (math.exp(x) - 1 - x) / (x * x)


def naive_6(a, b, eps):
    """Compute eps * (exp((a+b)*eps) - 1) / ((exp(a*eps) - 1) * (exp(b*eps) - 1)).

    Precondition: a > 0, b > 0, eps > 0.
    The mathematical limit as eps -> 0 is 1/a + 1/b.
    From Hamming's "Numerical Methods for Scientists and Engineers",
    problem 3.4.2. Suffers from cancellation because all three
    exp(...)-1 terms approach 0 simultaneously as eps -> 0.
    """
    numer = eps * (math.exp((a + b) * eps) - 1)
    denom = (math.exp(a * eps) - 1) * (math.exp(b * eps) - 1)
    return numer / denom
