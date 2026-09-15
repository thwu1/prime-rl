"""Python ctypes wrapper for the C NTT shared library.

"""
import ctypes
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, 'libntt.so'))

_lib.poly_multiply.argtypes = [
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
]
_lib.poly_multiply.restype = ctypes.POINTER(ctypes.c_longlong)

_lib.free_poly.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
_lib.free_poly.restype = None


def multiply(a, b):
    """Multiply two polynomials using the C NTT library.

    Returns coefficient list of the product.
    """
    na, nb = len(a), len(b)
    arr_a = (ctypes.c_int * na)(*a)
    arr_b = (ctypes.c_int * nb)(*b)
    result_len = ctypes.c_int(0)
    result_ptr = _lib.poly_multiply(arr_a, na, arr_b, nb, ctypes.byref(result_len))
    rlen = result_len.value
    out = [int(result_ptr[i]) for i in range(rlen)]
    _lib.free_poly(result_ptr)
    return out
