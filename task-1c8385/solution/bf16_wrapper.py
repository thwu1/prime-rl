"""
BFloat16 floating-point arithmetic library.
Complete Python ctypes wrapper around libbf16.so.
"""


import ctypes
import math

_lib = ctypes.CDLL('/app/libbf16.so')

# --- Function signatures ---

# void bf16_unpack(uint16_t raw, int *sign, int *exp, int *man)
_lib.bf16_unpack.argtypes = [ctypes.c_uint16,
                              ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_int)]
_lib.bf16_unpack.restype = None

# uint16_t bf16_pack(int sign, int exp, int man)
_lib.bf16_pack.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
_lib.bf16_pack.restype = ctypes.c_uint16

# int bf16_classify(uint16_t raw)
_lib.bf16_classify.argtypes = [ctypes.c_uint16]
_lib.bf16_classify.restype = ctypes.c_int

# double bf16_to_float(uint16_t raw)
_lib.bf16_to_float.argtypes = [ctypes.c_uint16]
_lib.bf16_to_float.restype = ctypes.c_double

# uint16_t bf16_from_float(double value, int rm)
_lib.bf16_from_float.argtypes = [ctypes.c_double, ctypes.c_int]
_lib.bf16_from_float.restype = ctypes.c_uint16

# uint16_t bf16_add(uint16_t a, uint16_t b, int rm)
_lib.bf16_add.argtypes = [ctypes.c_uint16, ctypes.c_uint16, ctypes.c_int]
_lib.bf16_add.restype = ctypes.c_uint16

# uint16_t bf16_mul(uint16_t a, uint16_t b, int rm)
_lib.bf16_mul.argtypes = [ctypes.c_uint16, ctypes.c_uint16, ctypes.c_int]
_lib.bf16_mul.restype = ctypes.c_uint16

# --- Mappings ---

_RM = {"RNE": 0, "RNA": 1, "RZ": 2, "RU": 3, "RD": 4}
_CLS = {0: "zero", 1: "subnormal", 2: "normal", 3: "infinity", 4: "nan"}


# --- Public API ---

def bf16_unpack(raw):
    s = ctypes.c_int()
    e = ctypes.c_int()
    m = ctypes.c_int()
    _lib.bf16_unpack(ctypes.c_uint16(raw),
                     ctypes.byref(s), ctypes.byref(e), ctypes.byref(m))
    return (s.value, e.value, m.value)


def bf16_pack(sign, exp, man):
    return _lib.bf16_pack(sign, exp, man)


def bf16_classify(raw):
    return _CLS[_lib.bf16_classify(ctypes.c_uint16(raw))]


def bf16_to_float(raw):
    return _lib.bf16_to_float(ctypes.c_uint16(raw))


def bf16_from_float(value, rm="RNE"):
    return _lib.bf16_from_float(ctypes.c_double(value), _RM[rm])


def bf16_add(a, b, rm="RNE"):
    return _lib.bf16_add(ctypes.c_uint16(a), ctypes.c_uint16(b), _RM[rm])


def bf16_mul(a, b, rm="RNE"):
    return _lib.bf16_mul(ctypes.c_uint16(a), ctypes.c_uint16(b), _RM[rm])
