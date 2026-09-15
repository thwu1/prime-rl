"""Python wrapper for the C dual-number library via ctypes."""

import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cdual', 'libdual.so')


class _DualNum(ctypes.Structure):
    _fields_ = [("real", ctypes.c_double), ("dual", ctypes.c_double)]


def _load_library():
    lib = ctypes.CDLL(_lib_path)

    lib.dual_new.argtypes = [ctypes.c_double, ctypes.c_double]
    lib.dual_new.restype = _DualNum

    lib.dual_const.argtypes = [ctypes.c_double]
    lib.dual_const.restype = _DualNum

    for fname in ('dual_add', 'dual_sub', 'dual_mul', 'dual_div'):
        getattr(lib, fname).argtypes = [_DualNum, _DualNum]
        getattr(lib, fname).restype = _DualNum

    lib.dual_sqrt.argtypes = [_DualNum]
    lib.dual_sqrt.restype = _DualNum

    lib.dual_neg.argtypes = [_DualNum]
    lib.dual_neg.restype = _DualNum

    lib.dual_add_scalar.argtypes = [_DualNum, ctypes.c_double]
    lib.dual_add_scalar.restype = _DualNum

    lib.dual_mul_scalar.argtypes = [_DualNum, ctypes.c_double]
    lib.dual_mul_scalar.restype = _DualNum

    lib.dual_div_scalar.argtypes = [_DualNum, ctypes.c_double]
    lib.dual_div_scalar.restype = _DualNum

    lib.dual_lt.argtypes = [_DualNum, _DualNum]
    lib.dual_lt.restype = ctypes.c_int

    return lib


_lib = _load_library()


class CDual:
    __slots__ = ('_d',)

    def __init__(self, real, dual=0.0):
        if isinstance(real, _DualNum):
            self._d = real
        else:
            self._d = _lib.dual_new(float(real), float(dual))

    @property
    def real(self):
        return self._d.real

    @property
    def dual(self):
        return self._d.dual

    def __repr__(self):
        return f"CDual({self.real}, {self.dual})"

    def __add__(self, other):
        if isinstance(other, CDual):
            return CDual(_lib.dual_add(self._d, other._d))
        return CDual(_lib.dual_add_scalar(self._d, float(other)))

    def __radd__(self, other):
        return CDual(_lib.dual_add_scalar(self._d, float(other)))

    def __sub__(self, other):
        if isinstance(other, CDual):
            return CDual(_lib.dual_sub(self._d, other._d))
        return CDual(_lib.dual_add_scalar(self._d, -float(other)))

    def __rsub__(self, other):
        return CDual(_lib.dual_sub(_lib.dual_const(float(other)), self._d))

    def __mul__(self, other):
        if isinstance(other, CDual):
            return CDual(_lib.dual_mul(self._d, other._d))
        return CDual(_lib.dual_mul_scalar(self._d, float(other)))

    def __rmul__(self, other):
        return CDual(_lib.dual_mul_scalar(self._d, float(other)))

    def __truediv__(self, other):
        if isinstance(other, CDual):
            return CDual(_lib.dual_div(self._d, other._d))
        return CDual(_lib.dual_div_scalar(self._d, float(other)))

    def __rtruediv__(self, other):
        return CDual(_lib.dual_div(_lib.dual_const(float(other)), self._d))

    def __neg__(self):
        return CDual(_lib.dual_neg(self._d))

    def __lt__(self, other):
        if isinstance(other, CDual):
            return self.real < other.real
        return self.real < float(other)

    def __gt__(self, other):
        if isinstance(other, CDual):
            return self.real > other.real
        return self.real > float(other)

    def __le__(self, other):
        if isinstance(other, CDual):
            return self.real <= other.real
        return self.real <= float(other)

    def __ge__(self, other):
        if isinstance(other, CDual):
            return self.real >= other.real
        return self.real >= float(other)

    def sqrt(self):
        return CDual(_lib.dual_sqrt(self._d))
