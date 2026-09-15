import ctypes
import numpy as np
import os

_LIB_PATH = '/app/native/libdistances.so'
_lib = None


def _load_native():
    global _lib
    if _lib is not None:
        return _lib
    if not os.path.exists(_LIB_PATH):
        raise RuntimeError(
            f"Native distance library not found at {_LIB_PATH}. "
            f"Build with: make -C /app/native/"
        )
    _lib = ctypes.CDLL(_LIB_PATH)
    _lib.pairwise_sq_euclidean.restype = None
    _lib.pairwise_sq_euclidean.argtypes = [
        ctypes.c_void_p,  # X
        ctypes.c_int,     # n
        ctypes.c_void_p,  # Y
        ctypes.c_int,     # m
        ctypes.c_int,     # d
        ctypes.c_void_p,  # out
    ]
    return _lib


def compute_cost_matrix(X, Y, metric='sqeuclidean'):
    """Compute pairwise cost matrix using native C library.

    Parameters
    ----------
    X : array (n, d) - source points
    Y : array (m, d) - target points
    metric : str - 'sqeuclidean' for squared Euclidean, 'euclidean' for Euclidean

    Returns
    -------
    M : array (n, m) - cost matrix
    """
    lib = _load_native()

    X = np.ascontiguousarray(X, dtype=np.float64)
    Y = np.ascontiguousarray(Y, dtype=np.float64)
    n, d = X.shape
    m = Y.shape[0]

    out = np.empty((n, m), dtype=np.float64)

    # Native function computes squared Euclidean distances
    lib.pairwise_sq_euclidean(
        X.ctypes.data, ctypes.c_int(n),
        Y.ctypes.data, ctypes.c_int(m),
        ctypes.c_int(d),
        out.ctypes.data
    )

    if metric == 'sqeuclidean':
        return out  # Already squared distances from native library
    elif metric == 'euclidean':
        return np.sqrt(out)
    else:
        raise ValueError(f"Unknown metric: {metric}")
