"""Python ctypes wrapper for the blocked attention C library."""
import ctypes
import numpy as np
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, "libattention.so"))

_double_ptr = ctypes.POINTER(ctypes.c_double)
_int = ctypes.c_int

_lib.blocked_forward.restype = None
_lib.blocked_forward.argtypes = [
    _double_ptr, _double_ptr, _double_ptr,
    _double_ptr, _double_ptr,
    _int, _int, _int
]

_lib.blocked_causal_forward.restype = None
_lib.blocked_causal_forward.argtypes = [
    _double_ptr, _double_ptr, _double_ptr,
    _double_ptr, _double_ptr,
    _int, _int, _int
]

_lib.blocked_backward.restype = None
_lib.blocked_backward.argtypes = [
    _double_ptr, _double_ptr, _double_ptr,
    _double_ptr, _double_ptr, _double_ptr,
    _double_ptr, _double_ptr, _double_ptr,
    _int, _int, _int
]

_lib.blocked_causal_backward.restype = None
_lib.blocked_causal_backward.argtypes = [
    _double_ptr, _double_ptr, _double_ptr,
    _double_ptr, _double_ptr, _double_ptr,
    _double_ptr, _double_ptr, _double_ptr,
    _int, _int, _int
]


def _as_ptr(arr):
    arr = np.ascontiguousarray(arr, dtype=np.float64)
    return arr.ctypes.data_as(_double_ptr), arr


def forward(Q, K, V, block_size):
    N, d = Q.shape
    q_ptr, _q = _as_ptr(Q)
    k_ptr, _k = _as_ptr(K)
    v_ptr, _v = _as_ptr(V)

    O = np.zeros((N, d), dtype=np.float64)
    L = np.zeros(N, dtype=np.float64)
    o_ptr = O.ctypes.data_as(_double_ptr)
    l_ptr = L.ctypes.data_as(_double_ptr)

    _lib.blocked_forward(q_ptr, k_ptr, v_ptr, o_ptr, l_ptr,
                         _int(N), _int(d), _int(block_size))
    return O, L


def causal_forward(Q, K, V, block_size):
    N, d = Q.shape
    q_ptr, _q = _as_ptr(Q)
    k_ptr, _k = _as_ptr(K)
    v_ptr, _v = _as_ptr(V)

    O = np.zeros((N, d), dtype=np.float64)
    L = np.zeros(N, dtype=np.float64)
    o_ptr = O.ctypes.data_as(_double_ptr)
    l_ptr = L.ctypes.data_as(_double_ptr)

    _lib.blocked_causal_forward(q_ptr, k_ptr, v_ptr, o_ptr, l_ptr,
                                _int(N), _int(d), _int(block_size))
    return O, L


def backward(Q, K, V, O, dO, L, block_size):
    N, d = Q.shape
    q_ptr, _q = _as_ptr(Q)
    k_ptr, _k = _as_ptr(K)
    v_ptr, _v = _as_ptr(V)
    o_ptr, _o = _as_ptr(O)
    do_ptr, _do = _as_ptr(dO)
    l_ptr, _l = _as_ptr(L)

    dQ = np.zeros((N, d), dtype=np.float64)
    dK = np.zeros((N, d), dtype=np.float64)
    dV = np.zeros((N, d), dtype=np.float64)
    dq_ptr = dQ.ctypes.data_as(_double_ptr)
    dk_ptr = dK.ctypes.data_as(_double_ptr)
    dv_ptr = dV.ctypes.data_as(_double_ptr)

    _lib.blocked_backward(q_ptr, k_ptr, v_ptr, o_ptr, do_ptr, l_ptr,
                          dq_ptr, dk_ptr, dv_ptr,
                          _int(N), _int(d), _int(block_size))
    return dQ, dK, dV


def causal_backward(Q, K, V, O, dO, L, block_size):
    N, d = Q.shape
    q_ptr, _q = _as_ptr(Q)
    k_ptr, _k = _as_ptr(K)
    v_ptr, _v = _as_ptr(V)
    o_ptr, _o = _as_ptr(O)
    do_ptr, _do = _as_ptr(dO)
    l_ptr, _l = _as_ptr(L)

    dQ = np.zeros((N, d), dtype=np.float64)
    dK = np.zeros((N, d), dtype=np.float64)
    dV = np.zeros((N, d), dtype=np.float64)
    dq_ptr = dQ.ctypes.data_as(_double_ptr)
    dk_ptr = dK.ctypes.data_as(_double_ptr)
    dv_ptr = dV.ctypes.data_as(_double_ptr)

    _lib.blocked_causal_backward(q_ptr, k_ptr, v_ptr, o_ptr, do_ptr, l_ptr,
                                 dq_ptr, dk_ptr, dv_ptr,
                                 _int(N), _int(d), _int(block_size))
    return dQ, dK, dV
