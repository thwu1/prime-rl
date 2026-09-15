"""Fix the autograd framework: correct Makefile, toposort, wrapper path, and add all missing VJPs."""
import os

# ============================================================
# FIX 1: Fix Makefile — add -shared -fPIC -lm for shared library
# ============================================================

MAKEFILE_PATH = '/app/autograd/csrc/Makefile'

makefile_content = '''\
CC = gcc
CFLAGS = -O2 -Wall -fPIC

all: custom_ops.so

custom_ops.so: custom_ops.c
\t$(CC) $(CFLAGS) -shared -o $@ $< -lm

clean:
\trm -f *.so

.PHONY: all clean
'''

with open(MAKEFILE_PATH, 'w') as f:
    f.write(makefile_content)

print("Fixed Makefile with -shared -fPIC -lm")

# ============================================================
# FIX 2: Fix custom_ops_wrapper.py — correct path + add VJP
# ============================================================

WRAPPER_PATH = '/app/autograd/custom_ops_wrapper.py'

wrapper_content = '''\
"""Python wrapper for C-implemented custom operations."""
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
    lib_path = os.path.join(os.path.dirname(__file__), 'csrc', 'custom_ops.so')
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
# d/dx log(sum(exp(x))) = softmax(x) = exp(x - logsumexp(x))

def _custom_logsumexp_vjp(g, ans, x):
    x_arr = np.asarray(x, dtype=np.float64)
    return g * np.exp(x_arr - ans)

defvjp(custom_logsumexp, _custom_logsumexp_vjp)
'''

with open(WRAPPER_PATH, 'w') as f:
    f.write(wrapper_content)

print("Fixed custom_ops_wrapper.py: path and VJP")

# ============================================================
# FIX 3: Replace broken toposort in util.py
# ============================================================

UTIL_PATH = '/app/autograd/util.py'

util_content = '''\
"""Utility functions."""


def subvals(x, ivs):
    x_ = list(x)
    for i, v in ivs:
        x_[i] = v
    return tuple(x_)

def subval(x, i, v):
    x_ = list(x)
    x_[i] = v
    return tuple(x_)

def toposort(end_node):
    """Topological sort: yields nodes in reverse topological order.

    A node is yielded only after ALL of its children (downstream consumers)
    have been processed. Uses Kahn's algorithm variant: count children for
    each node, yield a node only when its child count drops to zero.
    """
    child_counts = {}
    stack = [end_node]
    while stack:
        node = stack.pop()
        if node in child_counts:
            child_counts[node] += 1
        else:
            child_counts[node] = 1
            stack.extend(node.parents)

    childless_nodes = [end_node]
    while childless_nodes:
        node = childless_nodes.pop()
        yield node
        for parent in node.parents:
            if child_counts[parent] == 1:
                childless_nodes.append(parent)
            else:
                child_counts[parent] -= 1

def wraps(fun, namestr="{fun}", docstr="{doc}", **kwargs):
    def _wraps(f):
        try:
            f.__name__ = namestr.format(fun=get_name(fun), **kwargs)
            f.__doc__ = docstr.format(fun=get_name(fun), doc=get_doc(fun), **kwargs)
        finally:
            return f
    return _wraps

def wrap_nary_f(fun, op, argnum):
    namestr = "{op}_of_{fun}_wrt_argnum_{argnum}"
    docstr = """\\
    {op} of function {fun} with respect to argument number {argnum}. Takes the
    same arguments as {fun} but returns the {op}.
    """
    return wraps(fun, namestr, docstr, op=get_name(op), argnum=argnum)

get_name = lambda f: getattr(f, \'__name__\', \'[unknown name]\')
get_doc  = lambda f: getattr(f, \'__doc__\' , \'\')
'''

with open(UTIL_PATH, 'w') as f:
    f.write(util_content)

print("Fixed toposort in util.py")

# ============================================================
# FIX 4: Replace numpy_vjps.py with ALL VJP definitions
# ============================================================

VJP_PATH = '/app/autograd/numpy/numpy_vjps.py'

vjp_content = '''\
"""Vector-Jacobian products for NumPy functions."""
from __future__ import absolute_import
import numpy as onp
from . import numpy_wrapper as anp
from .numpy_boxes import ArrayBox
from autograd.tracer import primitive
from autograd.core import defvjp

# ----- Binary ufuncs -----

defvjp(anp.add,         lambda g, ans, x, y : unbroadcast(x, g),
                        lambda g, ans, x, y : unbroadcast(y, g))
defvjp(anp.multiply,    lambda g, ans, x, y : unbroadcast(x, y * g),
                        lambda g, ans, x, y : unbroadcast(y, x * g))
defvjp(anp.subtract,    lambda g, ans, x, y : unbroadcast(x, g),
                        lambda g, ans, x, y : unbroadcast(y, -g))
defvjp(anp.divide,      lambda g, ans, x, y : unbroadcast(x,   g / y),
                        lambda g, ans, x, y : unbroadcast(y, - g * x / y**2))
defvjp(anp.true_divide, lambda g, ans, x, y : unbroadcast(x,   g / y),
                        lambda g, ans, x, y : unbroadcast(y, - g * x / y**2))
defvjp(anp.power,
    lambda g, ans, x, y: unbroadcast(x, g * y * x ** anp.where(y, y - 1, 1.)),
    lambda g, ans, x, y: unbroadcast(y, g * anp.log(replace_zero(x, 1.)) * x ** y))

def replace_zero(x, val):
    return anp.where(x, x, val)

def unbroadcast(target, g, broadcast_idx=0):
    while anp.ndim(g) > anp.ndim(target):
        g = anp.sum(g, axis=broadcast_idx)
    for axis, size in enumerate(anp.shape(target)):
        if size == 1:
            g = anp.sum(g, axis=axis, keepdims=True)
    if anp.iscomplexobj(g) and not anp.iscomplex(target):
        g = anp.real(g)
    return g

# ----- Simple unary grads -----

defvjp(anp.negative, lambda g, ans, x: -g)
defvjp(anp.exp,    lambda g, ans, x: ans * g)
defvjp(anp.log,    lambda g, ans, x: g / x)
defvjp(anp.tanh,   lambda g, ans, x: g / anp.cosh(x) **2)
defvjp(anp.sinh,   lambda g, ans, x: g * anp.cosh(x))
defvjp(anp.cosh,   lambda g, ans, x: g * anp.sinh(x))

# --- abs ---
defvjp(anp.abs, lambda g, ans, x: g * anp.sign(x))

# --- sqrt ---
defvjp(anp.sqrt, lambda g, ans, x: g * 0.5 / ans)

# --- sin, cos ---
defvjp(anp.sin, lambda g, ans, x: g * anp.cos(x))
defvjp(anp.cos, lambda g, ans, x: -g * anp.sin(x))

# ----- where -----
defvjp(anp.where, None,
       lambda g, ans, c, x=None, y=None: anp.where(c, g, anp.zeros(g.shape)),
       lambda g, ans, c, x=None, y=None: anp.where(c, anp.zeros(g.shape), g))

# ----- reshape -----
defvjp(anp.reshape, lambda g, ans, x, shape, order=None:
       anp.reshape(g, anp.shape(x), order=order))

# ----- Dot grads -----

def _dot_vjp_0(g, ans, lhs, rhs):
  if max(anp.ndim(lhs), anp.ndim(rhs)) > 2:
    raise NotImplementedError("Current dot vjps only support ndim <= 2.")
  if anp.ndim(lhs) == 0:
    return anp.sum(rhs * g)
  if anp.ndim(lhs) == 1 and anp.ndim(rhs) == 1:
    return g * rhs
  if anp.ndim(lhs) == 2 and anp.ndim(rhs) == 1:
    return g[:, None] * rhs
  if anp.ndim(lhs) == 1 and anp.ndim(rhs) == 2:
    return anp.dot(rhs, g)
  return anp.dot(g, rhs.T)

def _dot_vjp_1(g, ans, lhs, rhs):
  if max(anp.ndim(lhs), anp.ndim(rhs)) > 2:
    raise NotImplementedError("Current dot vjps only support ndim <= 2.")
  if anp.ndim(rhs) == 0:
    return anp.sum(lhs * g)
  if anp.ndim(lhs) == 1 and anp.ndim(rhs) == 1:
    return g * lhs
  if anp.ndim(lhs) == 2 and anp.ndim(rhs) == 1:
    return anp.dot(g, lhs)
  if anp.ndim(lhs) == 1 and anp.ndim(rhs) == 2:
    return lhs[:, None] * g
  return anp.dot(lhs.T, g)

defvjp(anp.dot, _dot_vjp_0, _dot_vjp_1)

# ----- sum -----

def _sum_vjp(g, ans, x, axis=None, keepdims=False):
    """VJP for np.sum: broadcast g back to the shape of x."""
    shape = onp.shape(x)
    if axis is None:
        return g * onp.ones(shape)
    if not keepdims:
        if isinstance(axis, int):
            g = onp.expand_dims(g, axis)
        else:
            for ax in sorted(axis):
                g = onp.expand_dims(g, ax)
    return g * onp.ones(shape)

defvjp(anp.sum, _sum_vjp)

# ----- mean -----

def _mean_vjp(g, ans, x, axis=None, keepdims=False):
    shape = onp.shape(x)
    if axis is None:
        n = onp.size(x)
    elif isinstance(axis, int):
        n = shape[axis]
    else:
        n = 1
        for ax in axis:
            n *= shape[ax]
    return _sum_vjp(g, ans, x, axis=axis, keepdims=keepdims) / n

defvjp(anp.mean, _mean_vjp)

# ----- max -----

def _max_vjp(g, ans, x, axis=None, keepdims=False):
    if axis is None:
        idx = onp.argmax(x)
        out = onp.zeros_like(x).ravel()
        g_scalar = g if onp.ndim(g) == 0 else g.ravel()[0]
        out[idx] = g_scalar
        return out.reshape(onp.shape(x))
    else:
        if not keepdims:
            g = onp.expand_dims(g, axis)
            ans_expanded = onp.expand_dims(ans, axis)
        else:
            ans_expanded = ans
        mask = (x == ans_expanded)
        num_max = onp.sum(mask, axis=axis, keepdims=True)
        return g * mask / num_max

defvjp(anp.max, _max_vjp)

# ----- min -----

def _min_vjp(g, ans, x, axis=None, keepdims=False):
    if axis is None:
        idx = onp.argmin(x)
        out = onp.zeros_like(x).ravel()
        g_scalar = g if onp.ndim(g) == 0 else g.ravel()[0]
        out[idx] = g_scalar
        return out.reshape(onp.shape(x))
    else:
        if not keepdims:
            g = onp.expand_dims(g, axis)
            ans_expanded = onp.expand_dims(ans, axis)
        else:
            ans_expanded = ans
        mask = (x == ans_expanded)
        num_min = onp.sum(mask, axis=axis, keepdims=True)
        return g * mask / num_min

defvjp(anp.min, _min_vjp)

# ----- matmul -----

def _matmul_vjp_0(g, ans, lhs, rhs):
    """d(lhs @ rhs)/d(lhs) = g @ rhs.T"""
    return anp.dot(g, anp.transpose(rhs))

def _matmul_vjp_1(g, ans, lhs, rhs):
    """d(lhs @ rhs)/d(rhs) = lhs.T @ g"""
    return anp.dot(anp.transpose(lhs), g)

defvjp(anp.matmul, _matmul_vjp_0, _matmul_vjp_1)

# ----- transpose -----

defvjp(anp.transpose, lambda g, ans, x: anp.transpose(g))

# ----- __getitem__ (indexing/slicing) -----

def _getitem_vjp(g, ans, A, idx):
    """VJP for A[idx]: place gradient into correct positions of a zeros array."""
    out = onp.zeros_like(A)
    onp.add.at(out, idx, g)
    return out

defvjp(ArrayBox.__getitem__, _getitem_vjp)

# ----- logabsdet -----

def _logabsdet_vjp(g, ans, A):
    """d/dA log|det(A)| = (A^{-1})^T = A^{-T}"""
    return g * onp.linalg.inv(A).T

defvjp(anp.logabsdet, _logabsdet_vjp)

# ----- solve -----

def _solve_vjp_0(g, ans, A, b):
    """VJP of solve(A, b) w.r.t. A.
    x = solve(A, b) = A^{-1} b, so Ax = b.
    d/dA: VJP = -outer(solve(A^T, g), x)
    """
    x = ans
    v = onp.linalg.solve(A.T, g)
    return -onp.outer(v, x)

def _solve_vjp_1(g, ans, A, b):
    """VJP of solve(A, b) w.r.t. b.
    dx/db = A^{-1}, so VJP = A^{-T} g = solve(A^T, g)
    """
    return onp.linalg.solve(A.T, g)

defvjp(anp.solve, _solve_vjp_0, _solve_vjp_1)
'''

with open(VJP_PATH, 'w') as f:
    f.write(vjp_content)

print("Fixed numpy_vjps.py with all VJPs including logabsdet and solve")
print("Done — all fixes applied.")
