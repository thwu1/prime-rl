"""SDF combination operations: smooth minimum and CSG."""
import math


def smin_poly(d1, d2, k):
    """Polynomial smooth minimum of two distance values.
    k controls the blending radius.
    """
    h = max(k - abs(d1 - d2), 0.0)
    return min(d1, d2) - h * h / (4.0 * k)
