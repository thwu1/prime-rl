"""Complete GMPB ctypes wrapper for the C shared library."""

import ctypes
import os

import numpy as np

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'gmpb_native', 'libgmpb.so')
_lib = ctypes.CDLL(_LIB_PATH)

# --- Function signatures ---
_lib.gmpb_new.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_double, ctypes.c_int, ctypes.c_uint]
_lib.gmpb_new.restype = ctypes.c_void_p

_lib.gmpb_free.argtypes = [ctypes.c_void_p]
_lib.gmpb_free.restype = None

_lib.gmpb_evaluate.argtypes = [ctypes.c_void_p,
                                ctypes.POINTER(ctypes.c_double)]
_lib.gmpb_evaluate.restype = ctypes.c_double

_lib.gmpb_is_finished.argtypes = [ctypes.c_void_p]
_lib.gmpb_is_finished.restype = ctypes.c_int

_lib.gmpb_get_environment.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_environment.restype = ctypes.c_int

_lib.gmpb_get_offline_error.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_offline_error.restype = ctypes.c_double

_lib.gmpb_get_eval_count.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_eval_count.restype = ctypes.c_int

_lib.gmpb_get_remaining_evals.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_remaining_evals.restype = ctypes.c_int

_lib.gmpb_get_dimension.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_dimension.restype = ctypes.c_int

_lib.gmpb_get_num_peaks.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_num_peaks.restype = ctypes.c_int

_lib.gmpb_get_change_frequency.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_change_frequency.restype = ctypes.c_int

_lib.gmpb_get_min_coord.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_min_coord.restype = ctypes.c_double

_lib.gmpb_get_max_coord.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_max_coord.restype = ctypes.c_double

_lib.gmpb_get_optimum.argtypes = [ctypes.c_void_p]
_lib.gmpb_get_optimum.restype = ctypes.c_double

_lib.gmpb_get_optimum_position.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_double)]
_lib.gmpb_get_optimum_position.restype = ctypes.c_int


class GMPB:
    """Python wrapper around the GMPB C shared library."""

    def __init__(self, num_peaks=10, dimension=5, change_frequency=5000,
                 shift_severity=1.0, num_environments=30, seed=42):
        self._handle = _lib.gmpb_new(
            num_peaks, dimension, change_frequency,
            shift_severity, num_environments, seed)
        if not self._handle:
            raise RuntimeError("Failed to create GMPB instance (C malloc)")
        self._dim = dimension

    def __del__(self):
        if hasattr(self, '_handle') and self._handle:
            _lib.gmpb_free(self._handle)
            self._handle = None

    def evaluate(self, x):
        x = np.asarray(x, dtype=np.float64).ravel()
        if x.shape[0] != self._dim:
            raise ValueError(
                f"Expected {self._dim}-d vector, got {x.shape[0]}-d")
        arr = x.ctypes.data_as(ctypes.POINTER(ctypes.c_double))
        result = _lib.gmpb_evaluate(self._handle, arr)
        if np.isnan(result):
            raise RuntimeError("Evaluation budget exhausted")
        return float(result)

    def is_finished(self):
        return bool(_lib.gmpb_is_finished(self._handle))

    def get_environment(self):
        return _lib.gmpb_get_environment(self._handle)

    def get_offline_error(self):
        return float(_lib.gmpb_get_offline_error(self._handle))

    def get_eval_count(self):
        return _lib.gmpb_get_eval_count(self._handle)

    def get_remaining_evals(self):
        return _lib.gmpb_get_remaining_evals(self._handle)

    @property
    def dimension(self):
        return _lib.gmpb_get_dimension(self._handle)

    @property
    def num_peaks(self):
        return _lib.gmpb_get_num_peaks(self._handle)

    @property
    def change_frequency(self):
        return _lib.gmpb_get_change_frequency(self._handle)

    @property
    def min_coord(self):
        return float(_lib.gmpb_get_min_coord(self._handle))

    @property
    def max_coord(self):
        return float(_lib.gmpb_get_max_coord(self._handle))

    @property
    def optimum(self):
        return float(_lib.gmpb_get_optimum(self._handle))

    @property
    def optimum_position(self):
        buf = (ctypes.c_double * self._dim)()
        rc = _lib.gmpb_get_optimum_position(self._handle, buf)
        if rc != 0:
            raise RuntimeError("Failed to get optimum position")
        return np.array([buf[i] for i in range(self._dim)])
