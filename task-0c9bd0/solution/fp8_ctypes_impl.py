"""Python ctypes wrapper for libfp8.so shared library."""

import ctypes

_lib = ctypes.CDLL('/app/libfp8.so')

# fp8_to_float: uint8_t -> double
_lib.fp8_to_float.argtypes = [ctypes.c_uint8]
_lib.fp8_to_float.restype = ctypes.c_double

# fp8_from_float: (double, int) -> uint8_t
_lib.fp8_from_float.argtypes = [ctypes.c_double, ctypes.c_int]
_lib.fp8_from_float.restype = ctypes.c_uint8

# fp8_add: (uint8_t, uint8_t, int) -> uint8_t
_lib.fp8_add.argtypes = [ctypes.c_uint8, ctypes.c_uint8, ctypes.c_int]
_lib.fp8_add.restype = ctypes.c_uint8

# fp8_mul: (uint8_t, uint8_t, int) -> uint8_t
_lib.fp8_mul.argtypes = [ctypes.c_uint8, ctypes.c_uint8, ctypes.c_int]
_lib.fp8_mul.restype = ctypes.c_uint8

# fp8_fma: (uint8_t, uint8_t, uint8_t, int) -> uint8_t
_lib.fp8_fma.argtypes = [ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_int]
_lib.fp8_fma.restype = ctypes.c_uint8

# fp8_classify: uint8_t -> int
_lib.fp8_classify.argtypes = [ctypes.c_uint8]
_lib.fp8_classify.restype = ctypes.c_int

# fp8_compare: (uint8_t, uint8_t) -> int
_lib.fp8_compare.argtypes = [ctypes.c_uint8, ctypes.c_uint8]
_lib.fp8_compare.restype = ctypes.c_int

# Expose as module-level callables
fp8_to_float = _lib.fp8_to_float
fp8_from_float = _lib.fp8_from_float
fp8_add = _lib.fp8_add
fp8_mul = _lib.fp8_mul
fp8_fma = _lib.fp8_fma
fp8_classify = _lib.fp8_classify
fp8_compare = _lib.fp8_compare

# Constants
RNE = 0
RNA = 1
RU = 2
RD = 3
RZ = 4

CLASS_NORMAL = 0
CLASS_SUBNORMAL = 1
CLASS_ZERO = 2
CLASS_INFINITY = 3
CLASS_NAN = 4

CMP_UNORDERED = 2
