"""
GMPB ctypes bridge — INCOMPLETE STUB.

The GMPB benchmark is implemented as a C shared library. The source code
is at /app/gmpb_native/ and must be compiled into libgmpb.so before use.
See /app/gmpb_native/gmpb.h for the full API specification.

Steps:
  1. Compile the library:  cd /app/gmpb_native && make
  2. Complete the TODOs below to create a working Python wrapper.
  3. Save this as /app/gmpb.py

"""

import ctypes
import os
import numpy as np

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'gmpb_native', 'libgmpb.so')

# TODO: Load the shared library using ctypes.CDLL(_LIB_PATH)
# Example:
#   _lib = ctypes.CDLL(_LIB_PATH)

# TODO: Define argtypes and restype for each function in gmpb.h.
# The handle returned by gmpb_new is an opaque pointer (use ctypes.c_void_p).
# gmpb_evaluate takes (c_void_p, POINTER(c_double)) and returns c_double.
#
# Minimal example for one function:
#   _lib.gmpb_new.argtypes = [c_int, c_int, c_int, c_double, c_int, c_uint]
#   _lib.gmpb_new.restype  = c_void_p


class GMPB:
    """Python wrapper around the GMPB C shared library.

    Must expose these methods and properties for the optimizer and tests:

        evaluate(x)            -> float   (fitness at point x)
        is_finished()          -> bool    (budget exhausted?)
        get_environment()      -> int     (current env index, 0-based)
        get_offline_error()    -> float   (mean current error)
        get_eval_count()       -> int
        get_remaining_evals()  -> int
        dimension              -> int     (property)
        num_peaks              -> int     (property)
        change_frequency       -> int     (property)
        min_coord              -> float   (property)
        max_coord              -> float   (property)
        optimum                -> float   (property, current best peak height)
        optimum_position       -> ndarray (property, position of best peak)
    """

    def __init__(self, num_peaks=10, dimension=5, change_frequency=5000,
                 shift_severity=1.0, num_environments=30, seed=42):
        # TODO: Call gmpb_new via ctypes to create the C instance.
        # Store the returned handle and remember to free it in __del__.
        raise NotImplementedError("Complete the ctypes bindings")

    def __del__(self):
        # TODO: Call gmpb_free to release the C instance.
        pass

    def evaluate(self, x):
        # TODO: Convert x to a ctypes double array, call gmpb_evaluate.
        # Raise RuntimeError if NAN is returned (budget exhausted).
        raise NotImplementedError

    def is_finished(self):
        raise NotImplementedError

    def get_environment(self):
        raise NotImplementedError

    def get_offline_error(self):
        raise NotImplementedError

    def get_eval_count(self):
        raise NotImplementedError

    def get_remaining_evals(self):
        raise NotImplementedError

    @property
    def dimension(self):
        raise NotImplementedError

    @property
    def num_peaks(self):
        raise NotImplementedError

    @property
    def change_frequency(self):
        raise NotImplementedError

    @property
    def min_coord(self):
        raise NotImplementedError

    @property
    def max_coord(self):
        raise NotImplementedError

    @property
    def optimum(self):
        """Current global optimum fitness value."""
        raise NotImplementedError

    @property
    def optimum_position(self):
        """Position of the current global optimum peak (numpy array)."""
        raise NotImplementedError
