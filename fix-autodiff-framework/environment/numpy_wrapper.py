"""Thin wrapper around numpy that makes functions traceable."""
from __future__ import absolute_import
import numpy as _np
from autograd.tracer import primitive, notrace_primitive

# Wrap numpy functions as primitives so they can be traced.
# Each wrapped function records its invocation in the computation graph.

# --- Unary math ---
negative = primitive(_np.negative)
exp = primitive(_np.exp)
log = primitive(_np.log)
tanh = primitive(_np.tanh)
sinh = primitive(_np.sinh)
cosh = primitive(_np.cosh)
sqrt = primitive(_np.sqrt)
abs = primitive(_np.abs)
sign = notrace_primitive(_np.sign)
sin = primitive(_np.sin)
cos = primitive(_np.cos)

# --- Binary math ---
add = primitive(_np.add)
subtract = primitive(_np.subtract)
multiply = primitive(_np.multiply)
divide = primitive(_np.divide)
true_divide = primitive(_np.true_divide)
power = primitive(_np.power)
mod = notrace_primitive(_np.mod)

# --- Reductions ---
sum = primitive(_np.sum)
max = primitive(_np.max)
min = primitive(_np.min)
mean = primitive(_np.mean)
prod = primitive(_np.prod)
cumsum = primitive(_np.cumsum)
cumprod = primitive(_np.cumprod)

# --- Linear algebra ---
dot = primitive(_np.dot)
matmul = primitive(_np.matmul)
transpose = primitive(_np.transpose)

# --- Linear algebra: advanced ---
def _logabsdet(A):
    """Compute log(abs(det(A)))."""
    sign, logdet = _np.linalg.slogdet(A)
    return logdet

logabsdet = primitive(_logabsdet)
solve = primitive(_np.linalg.solve)

# --- Shape manipulation ---
reshape = primitive(_np.reshape)
ravel = primitive(_np.ravel)
squeeze = primitive(_np.squeeze)
repeat = primitive(_np.repeat)
expand_dims = primitive(_np.expand_dims)
concatenate = primitive(_np.concatenate)
stack = primitive(_np.stack)

# --- Comparison (non-differentiable) ---
equal = notrace_primitive(_np.equal)
not_equal = notrace_primitive(_np.not_equal)
greater = notrace_primitive(_np.greater)
greater_equal = notrace_primitive(_np.greater_equal)
less = notrace_primitive(_np.less)
less_equal = notrace_primitive(_np.less_equal)
where = primitive(_np.where)

# --- Array creation ---
zeros = _np.zeros
zeros_like = _np.zeros_like
ones = _np.ones
ones_like = _np.ones_like
array = _np.array
arange = _np.arange
linspace = _np.linspace
eye = _np.eye

# --- Queries ---
shape = _np.shape
ndim = _np.ndim
size = _np.size
iscomplexobj = _np.iscomplexobj
iscomplex = _np.iscomplex

# --- Other ---
_astype = primitive(lambda A, *args, **kwargs: A.astype(*args, **kwargs))

clip = primitive(_np.clip)
swapaxes = primitive(_np.swapaxes)
take = primitive(_np.take)
diagonal = primitive(_np.diagonal)
trace_fn = primitive(_np.trace)
var = primitive(_np.var)
std = primitive(_np.std)

# Method aliases
argmax = _np.argmax
argmin = _np.argmin
argsort = _np.argsort
nonzero = _np.nonzero
searchsorted = _np.searchsorted
round = _np.round
all = _np.all
any = _np.any
argpartition = _np.argpartition
