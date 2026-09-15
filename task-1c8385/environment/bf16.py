"""
BFloat16 floating-point arithmetic library.
Python ctypes wrapper around the C shared library libbf16.so.

Build libbf16.so from bf16.c using the provided Makefile before importing.
See /app/spec.md for the full bfloat16 specification.
"""


import ctypes
import math

# TODO: Load the shared library /app/libbf16.so using ctypes.CDLL
# TODO: For each C function, set argtypes and restype on the loaded library
# NOTE: bf16_unpack uses output pointers (int*) for sign, exp, man

# Rounding mode enum values (must match RM_* defines in bf16.h)
_RM_MAP = {"RNE": 0, "RNA": 1, "RZ": 2, "RU": 3, "RD": 4}

# Classification enum values (must match CLASS_* defines in bf16.h)
_CLASS_MAP = {0: "zero", 1: "subnormal", 2: "normal", 3: "infinity", 4: "nan"}


def bf16_unpack(raw):
    """Unpack a 16-bit bfloat16 value into (sign, biased_exponent, mantissa).
    The C function writes through output pointers; use ctypes.byref.
    """
    raise NotImplementedError


def bf16_pack(sign, exp, man):
    """Pack (sign, biased_exponent, mantissa) into a 16-bit bfloat16 value."""
    raise NotImplementedError


def bf16_classify(raw):
    """Classify a bfloat16 value.
    Returns one of: "zero", "subnormal", "normal", "infinity", "nan".
    """
    raise NotImplementedError


def bf16_to_float(raw):
    """Convert a bfloat16 value to a Python float.
    Must preserve signed zero.
    """
    raise NotImplementedError


def bf16_from_float(value, rm="RNE"):
    """Convert a Python float to bfloat16 with the specified rounding mode."""
    raise NotImplementedError


def bf16_add(a, b, rm="RNE"):
    """Add two bfloat16 values with the specified rounding mode."""
    raise NotImplementedError


def bf16_mul(a, b, rm="RNE"):
    """Multiply two bfloat16 values with the specified rounding mode."""
    raise NotImplementedError
