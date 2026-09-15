"""Python wrapper for the C dual-number library via ctypes.

This module provides a CDual class that wraps the compiled C dual-number
library (libdual.so) for fast forward-mode automatic differentiation.

Before using this module, the C library must be compiled:
    cd /app/cdual && make

The CDual class must support:
    - Construction: CDual(real, dual=0.0)
    - Properties: .real, .dual
    - Arithmetic: +, -, *, / (with CDual and float/int operands on both sides)
    - Unary: -x
    - Comparisons: <, >, <=, >=
    - Method: .sqrt()
"""

import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cdual', 'libdual.so')


class _DualNum(ctypes.Structure):
    """ctypes mirror of the C DualNum struct: {double real; double dual;}"""
    _fields_ = [("real", ctypes.c_double), ("dual", ctypes.c_double)]


# TODO: Load the shared library using ctypes.CDLL(_lib_path)
# TODO: Configure function signatures for all C functions:
#
#   Function Name          Arguments                    Return Type
#   ─────────────────────  ───────────────────────────  ──────────
#   dual_new               (c_double, c_double)         _DualNum
#   dual_const             (c_double,)                  _DualNum
#   dual_add               (_DualNum, _DualNum)         _DualNum
#   dual_sub               (_DualNum, _DualNum)         _DualNum
#   dual_mul               (_DualNum, _DualNum)         _DualNum
#   dual_div               (_DualNum, _DualNum)         _DualNum
#   dual_sqrt              (_DualNum,)                  _DualNum
#   dual_neg               (_DualNum,)                  _DualNum
#   dual_add_scalar        (_DualNum, c_double)         _DualNum
#   dual_mul_scalar        (_DualNum, c_double)         _DualNum
#   dual_div_scalar        (_DualNum, c_double)         _DualNum
#   dual_lt                (_DualNum, _DualNum)         c_int


class CDual:
    """Dual number backed by the C library for fast forward-mode AD."""
    __slots__ = ('_d',)

    def __init__(self, real, dual=0.0):
        # TODO: Create a _DualNum via the C library's dual_new function
        pass

    @property
    def real(self):
        # TODO: Return real component from self._d
        pass

    @property
    def dual(self):
        # TODO: Return dual component from self._d
        pass

    # TODO: Implement all arithmetic operators:
    #   __add__, __radd__    (CDual + CDual, CDual + float, float + CDual)
    #   __sub__, __rsub__    (CDual - CDual, CDual - float, float - CDual)
    #   __mul__, __rmul__    (CDual * CDual, CDual * float, float * CDual)
    #   __truediv__, __rtruediv__  (CDual / CDual, CDual / float, float / CDual)
    #   __neg__              (-CDual)

    # TODO: Implement comparison operators:
    #   __lt__, __gt__, __le__, __ge__  (compare on .real values only)

    # TODO: Implement sqrt() method
