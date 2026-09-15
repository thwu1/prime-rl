"""
Objective function for Challenge C2.
Evaluate f(x, y) as defined below.
"""
import math


def f(x, y):
    """The objective to be globally minimized over R^2."""
    term1 = math.exp(math.sin(50 * x))
    term2 = math.sin(60 * math.exp(y))
    term3 = math.sin(70 * math.sin(x))
    term4 = math.sin(math.sin(80 * y))
    term5 = -math.sin(10 * (x + y))
    term6 = (x ** 2 + y ** 2) / 4
    return term1 + term2 + term3 + term4 + term5 + term6
