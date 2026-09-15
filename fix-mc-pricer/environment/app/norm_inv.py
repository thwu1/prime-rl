"""Inverse of the standard normal CDF.
Uses Acklam's rational approximation algorithm.
Reference: Peter Acklam, "An algorithm for computing the inverse
normal cumulative distribution function" (2010).
"""
import math

# Rational approximation coefficients
_A = [
    -3.969683028665376e+01, 2.209460984245205e+02,
    -2.759285104469687e+02, 1.383577518672690e+02,
    -3.066479806614716e+01, 2.506628277459239e+00,
]
_B = [
    -5.447609879822406e+01, 1.615858368580409e+02,
    -1.556989798598866e+02, 6.680131188771972e+01,
    -1.328068155288572e+01,
]
_C = [
    -7.784894002430293e-03, -3.223964580411365e-01,
    -2.400758277161838e+00, -2.549732539343734e+00,
     4.374664141464968e+00,  2.938163982698783e+00,
]
_D = [
    7.784695709041462e-03, 3.224671290700398e-01,
    2.445134137142996e+00, 3.754408661907416e+00,
]

_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def norm_inv(u):
    """Compute the inverse standard normal CDF at probability u in (0,1)."""
    if u <= 0.0 or u >= 1.0:
        raise ValueError(f"u must be in (0, 1), got {u}")

    if u < _P_LOW:
        # Lower tail region
        q = math.sqrt(-math.log(u))
        x = (((((_C[0]*q + _C[1])*q + _C[2])*q + _C[3])*q + _C[4])*q + _C[5]) / \
            ((((_D[0]*q + _D[1])*q + _D[2])*q + _D[3])*q + 1.0)
    elif u <= _P_HIGH:
        # Central region
        q = u - 0.5
        r = q * q
        x = (((((_A[0]*r + _A[1])*r + _A[2])*r + _A[3])*r + _A[4])*r + _A[5]) * q / \
            (((((_B[0]*r + _B[1])*r + _B[2])*r + _B[3])*r + _B[4])*r + 1.0)
    else:
        # Upper tail region
        q = math.sqrt(-math.log(1.0 - u))
        x = -(((((_C[0]*q + _C[1])*q + _C[2])*q + _C[3])*q + _C[4])*q + _C[5]) / \
             ((((_D[0]*q + _D[1])*q + _D[2])*q + _D[3])*q + 1.0)

    return x
