"""Python wrapper for C-implemented custom operations.

Loads the compiled shared library via ctypes and exposes operations
as autograd primitives that can be traced and differentiated.
"""
import ctypes
import numpy as np
import os

from .tracer import primitive
from .core import defvjp

_LIB_LOADED = False
_lib = None


def _ensure_lib():
    """Lazily load the C shared library on first use."""
    global _lib, _LIB_LOADED
    if _LIB_LOADED:
        return
    lib_path = os.path.join(os.path.dirname(__file__), 'custom_ops.so')
    try:
        _lib = ctypes.CDLL(lib_path)
    except OSError as e:
        raise RuntimeError(
            "Cannot load custom_ops shared library from {}. "
            "Build it with 'make' in the csrc/ directory. "
            "Error: {}".format(lib_path, e)
        ) from e
    _lib.logsumexp_forward.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
    ]
    _lib.logsumexp_forward.restype = None
    _LIB_LOADED = True


def _raw_logsumexp(x):
    """Compute log(sum(exp(x))) using the C implementation."""
    _ensure_lib()
    x_flat = np.ascontiguousarray(np.asarray(x, dtype=np.float64).ravel())
    result = ctypes.c_double()
    _lib.logsumexp_forward(
        x_flat.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int(len(x_flat)),
        ctypes.byref(result),
    )
    return np.float64(result.value)


custom_logsumexp = primitive(_raw_logsumexp)


# ----- VJP for custom_logsumexp -----
# MISSING: No VJP is registered for custom_logsumexp. Any attempt to
# differentiate through it will raise a KeyError in the backward pass.
# The derivative of log(sum(exp(x))) w.r.t. x is softmax(x).
