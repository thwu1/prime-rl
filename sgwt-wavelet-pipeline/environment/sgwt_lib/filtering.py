"""Spectral graph filtering — exact (GFT) and Chebyshev polynomial via native C library."""
import ctypes
import os
import numpy as np
from scipy import sparse


_native_lib = None


def _get_native_lib():
    """Load the native SGWT shared library for Chebyshev operations."""
    global _native_lib
    if _native_lib is None:
        lib_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "libsgwt_native.so"
        )
        _native_lib = ctypes.CDLL(lib_path)
        _native_lib.cheby_op_c.argtypes = [
            ctypes.POINTER(ctypes.c_double),   # L_data
            ctypes.POINTER(ctypes.c_int),      # L_indices
            ctypes.POINTER(ctypes.c_int),      # L_indptr
            ctypes.c_int,                       # N
            ctypes.POINTER(ctypes.c_double),   # c_all
            ctypes.c_int,                       # Nscales
            ctypes.c_int,                       # M
            ctypes.POINTER(ctypes.c_double),   # signal
            ctypes.c_double,                    # lmax
            ctypes.POINTER(ctypes.c_double),   # result
        ]
        _native_lib.cheby_op_c.restype = None
    return _native_lib


def exact_analysis(eigenvalues, eigenvectors, signal, kernel_responses):
    """Exact filterbank analysis via the graph Fourier transform.

    Parameters
    ----------
    eigenvalues : ndarray (N,)
        Sorted Laplacian eigenvalues.
    eigenvectors : ndarray (N, N)
        Corresponding eigenvectors (columns).
    signal : ndarray (N,)
        Graph signal to analyse.
    kernel_responses : ndarray (Nf, N)
        ``kernel_responses[i]`` is the i-th filter evaluated at the
        eigenvalues.

    Returns
    -------
    coefficients : ndarray (N, Nf)
        Analysis coefficients for each filter.
    """
    N = len(signal)
    Nf = kernel_responses.shape[0]
    s_hat = eigenvectors.T @ signal
    result = np.zeros((N, Nf))
    for i in range(Nf):
        result[:, i] = eigenvectors @ (s_hat * kernel_responses[i])
    return result


def exact_synthesis(eigenvalues, eigenvectors, coefficients, kernel_responses):
    """Exact filterbank synthesis — reconstruct a signal from analysis
    coefficients by summing each filter applied to its channel.

    Parameters
    ----------
    eigenvalues : ndarray (N,)
    eigenvectors : ndarray (N, N)
    coefficients : ndarray (N, Nf)
        Output of ``exact_analysis``.
    kernel_responses : ndarray (Nf, N)

    Returns
    -------
    reconstructed : ndarray (N,)
    """
    N = coefficients.shape[0]
    Nf = coefficients.shape[1]
    reconstructed = np.zeros(N)
    for i in range(Nf):
        s_hat = eigenvectors.T @ coefficients[:, i]
        reconstructed += eigenvectors @ (s_hat * kernel_responses[i])
    return reconstructed


def compute_cheby_coeff(kernel_func, m, lmax):
    """Compute Chebyshev polynomial expansion coefficients for a kernel.

    Uses DCT-based quadrature on ``m + 1`` Chebyshev nodes to
    approximate ``kernel_func`` over the interval ``[0, lmax]``.

    Parameters
    ----------
    kernel_func : callable
        Kernel to approximate (maps eigenvalues to filter response).
    m : int
        Polynomial order.
    lmax : float
        Upper bound of the eigenvalue spectrum.

    Returns
    -------
    c : ndarray (m + 1,)
        Chebyshev coefficients.
    """
    N = m + 1
    a1 = lmax / 2.0
    a2 = lmax / 2.0

    c = np.zeros(m + 1)
    tmpN = np.arange(N)
    nodes = np.cos(np.pi * (tmpN + 0.5) / N)
    f_vals = kernel_func(a1 * nodes + a2)

    for k in range(m + 1):
        c[k] = (2.0 / N) * np.dot(
            f_vals, np.cos(np.pi * k * (tmpN + 0.5) / N)
        )
    return c


def cheby_op(L_sparse, c_all, signal, lmax):
    """Apply a Chebyshev polynomial filter approximation via the native
    C shared library.

    Parameters
    ----------
    L_sparse : sparse matrix (N, N)
        Graph Laplacian.
    c_all : ndarray (Nscales, M)
        Chebyshev coefficients for each filter.
    signal : ndarray (N,)
        Input graph signal.
    lmax : float
        Maximum eigenvalue.

    Returns
    -------
    result : ndarray (N, Nscales)
    """
    lib = _get_native_lib()

    L_csr = sparse.csr_matrix(L_sparse)
    N = L_csr.shape[0]
    Nscales, M = c_all.shape

    L_data = np.ascontiguousarray(L_csr.data, dtype=np.float64)
    L_indices = np.ascontiguousarray(L_csr.indices, dtype=np.int32)
    L_indptr = np.ascontiguousarray(L_csr.indptr, dtype=np.int32)
    sig = np.ascontiguousarray(signal, dtype=np.float64)
    c_arr = np.ascontiguousarray(c_all, dtype=np.float64)

    result_buf = np.zeros(N * Nscales, dtype=np.float64)

    lib.cheby_op_c(
        L_data.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        L_indices.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        L_indptr.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
        ctypes.c_int(N),
        c_arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int(Nscales),
        ctypes.c_int(M),
        sig.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_double(lmax),
        result_buf.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )

    # Reshape flat buffer — C code writes result[n * Nscales + s]
    return result_buf.reshape(Nscales, N).T
