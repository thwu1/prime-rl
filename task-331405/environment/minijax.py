"""
Mini-JAX: A minimal tracing-based automatic differentiation system.

Implements forward-mode AD (JVP) and jaxpr intermediate representation.
Reverse-mode AD (vjp/grad) is NOT implemented.

Based on concepts from the JAX autodidax tutorial.
"""

from __future__ import annotations
import numpy as np
import operator as op
import itertools as it
import string
import builtins
from typing import Any, NamedTuple, Union
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from functools import lru_cache, partial

# ============================================================
# Primitives
# ============================================================

class Primitive(NamedTuple):
    name: str

add_p = Primitive('add')
mul_p = Primitive('mul')
neg_p = Primitive('neg')
sin_p = Primitive('sin')
cos_p = Primitive('cos')
exp_p = Primitive('exp')
log_p = Primitive('log')
div_p = Primitive('div')
reduce_sum_p = Primitive('reduce_sum')
greater_p = Primitive('greater')
less_p = Primitive('less')
transpose_p = Primitive('transpose')
broadcast_p = Primitive('broadcast')

def add(x, y): return bind1(add_p, x, y)
def mul(x, y): return bind1(mul_p, x, y)
def neg(x): return bind1(neg_p, x)
def sin(x): return bind1(sin_p, x)
def cos(x): return bind1(cos_p, x)
def exp(x): return bind1(exp_p, x)
def log(x): return bind1(log_p, x)
def div(x, y): return bind1(div_p, x, y)
def greater(x, y): return bind1(greater_p, x, y)
def less(x, y): return bind1(less_p, x, y)
def transpose_op(x, perm): return bind1(transpose_p, x, perm=perm)
def broadcast(x, shape, axes): return bind1(broadcast_p, x, shape=shape, axes=axes)
def reduce_sum(x, axis=None):
    if axis is None:
        axis = tuple(range(np.ndim(x)))
    if type(axis) is int:
        axis = (axis,)
    return bind1(reduce_sum_p, x, axis=axis)

def bind1(prim, *args, **params):
    out, = bind(prim, *args, **params)
    return out

# ============================================================
# Core Tracing Infrastructure
# ============================================================

class MainTrace(NamedTuple):
    level: int
    trace_type: type
    global_data: Any | None

trace_stack: list[MainTrace] = []
dynamic_trace: MainTrace | None = None

@contextmanager
def new_main(trace_type: type, global_data=None):
    level = len(trace_stack)
    main = MainTrace(level, trace_type, global_data)
    trace_stack.append(main)
    try:
        yield main
    finally:
        trace_stack.pop()

@contextmanager
def new_dynamic(main: MainTrace):
    global dynamic_trace
    prev_dynamic_trace, dynamic_trace = dynamic_trace, main
    try:
        yield
    finally:
        dynamic_trace = prev_dynamic_trace

class Trace:
    main: MainTrace
    def __init__(self, main: MainTrace) -> None:
        self.main = main
    def pure(self, val): assert False
    def lift(self, val): assert False
    def process_primitive(self, primitive, tracers, params): assert False

class Tracer:
    _trace: Trace
    __array_priority__ = 1000

    @property
    def aval(self): assert False

    def full_lower(self): return self

    def __neg__(self): return self.aval._neg(self)
    def __add__(self, other): return self.aval._add(self, other)
    def __radd__(self, other): return self.aval._radd(self, other)
    def __sub__(self, other): return self.aval._sub(self, other)
    def __rsub__(self, other): return self.aval._rsub(self, other)
    def __mul__(self, other): return self.aval._mul(self, other)
    def __rmul__(self, other): return self.aval._rmul(self, other)
    def __truediv__(self, other): return self.aval._truediv(self, other)
    def __rtruediv__(self, other): return self.aval._rtruediv(self, other)
    def __gt__(self, other): return self.aval._gt(self, other)
    def __lt__(self, other): return self.aval._lt(self, other)
    def __bool__(self): return self.aval._bool(self)
    def __nonzero__(self): return self.aval._nonzero(self)

    def __getattr__(self, name):
        try:
            return getattr(self.aval, name)
        except AttributeError:
            raise AttributeError(f"{self.__class__.__name__} has no attribute {name}")

def _swap(f): return lambda x, y: f(y, x)

def _sub(x, y): return add(x, neg(y))

class ShapedArray:
    array_abstraction_level = 1
    def __init__(self, shape, dtype):
        self.shape = shape
        self.dtype = dtype
    @property
    def ndim(self): return len(self.shape)
    _neg = staticmethod(neg)
    _add = staticmethod(add)
    _radd = staticmethod(_swap(add))
    _sub = staticmethod(_sub)
    _rsub = staticmethod(_swap(_sub))
    _mul = staticmethod(mul)
    _rmul = staticmethod(_swap(mul))
    _truediv = staticmethod(div)
    _rtruediv = staticmethod(_swap(div))
    _gt = staticmethod(greater)
    _lt = staticmethod(less)
    @staticmethod
    def _bool(tracer): raise Exception("ShapedArray can't be converted to bool")
    @staticmethod
    def _nonzero(tracer): raise Exception("ShapedArray can't be converted to bool")
    def str_short(self):
        return f'{self.dtype.name}[{",".join(builtins.str(d) for d in self.shape)}]'
    def __hash__(self): return hash((self.shape, self.dtype))
    def __eq__(self, other):
        return (type(self) is type(other) and
                self.shape == other.shape and self.dtype == other.dtype)
    def __repr__(self): return f"ShapedArray(shape={self.shape}, dtype={self.dtype})"

class ConcreteArray(ShapedArray):
    array_abstraction_level = 2
    def __init__(self, val):
        self.val = val
        self.shape = val.shape
        self.dtype = val.dtype
    @staticmethod
    def _bool(tracer): return bool(tracer.aval.val)
    @staticmethod
    def _nonzero(tracer): return bool(tracer.aval.val)

def get_aval(x):
    if isinstance(x, Tracer):
        return x.aval
    elif type(x) in jax_types:
        return ConcreteArray(np.asarray(x))
    else:
        raise TypeError(x)

jax_types = {bool, int, float,
             np.bool_, np.int32, np.int64, np.float32, np.float64, np.ndarray}

def raise_to_shaped(aval):
    return ShapedArray(aval.shape, aval.dtype)

def vspace(aval):
    return raise_to_shaped(aval)

# --- bind and trace dispatch ---

def bind(prim, *args, **params):
    top_trace = find_top_trace(args)
    tracers = [full_raise(top_trace, arg) for arg in args]
    outs = top_trace.process_primitive(prim, tracers, params)
    return [full_lower(out) for out in outs]

def find_top_trace(xs) -> Trace:
    top_main = max((x._trace.main for x in xs if isinstance(x, Tracer)),
                   default=trace_stack[0], key=op.attrgetter('level'))
    if dynamic_trace and dynamic_trace.level > top_main.level:
        top_main = dynamic_trace
    return top_main.trace_type(top_main)

def full_lower(val):
    if isinstance(val, Tracer): return val.full_lower()
    return val

def full_raise(trace, val):
    if not isinstance(val, Tracer):
        assert type(val) in jax_types
        return trace.pure(val)
    level = trace.main.level
    if val._trace.main is trace.main: return val
    elif val._trace.main.level < level: return trace.lift(val)
    elif val._trace.main.level > level:
        raise Exception(f"Can't lift level {val._trace.main.level} to {level}.")
    else:
        raise Exception(f"Different traces at same level: {val._trace}, {trace}.")

# ============================================================
# Evaluation Interpreter
# ============================================================

class EvalTrace(Trace):
    pure = lift = lambda self, x: x
    def process_primitive(self, primitive, tracers, params):
        return impl_rules[primitive](*tracers, **params)

trace_stack.append(MainTrace(0, EvalTrace, None))

impl_rules = {}
impl_rules[add_p] = lambda x, y: [np.add(x, y)]
impl_rules[mul_p] = lambda x, y: [np.multiply(x, y)]
impl_rules[neg_p] = lambda x: [np.negative(x)]
impl_rules[sin_p] = lambda x: [np.sin(x)]
impl_rules[cos_p] = lambda x: [np.cos(x)]
impl_rules[exp_p] = lambda x: [np.exp(x)]
impl_rules[log_p] = lambda x: [np.log(x)]
impl_rules[div_p] = lambda x, y: [np.divide(x, y)]
impl_rules[reduce_sum_p] = lambda x, *, axis: [np.sum(x, axis)]
impl_rules[greater_p] = lambda x, y: [np.greater(x, y)]
impl_rules[less_p] = lambda x, y: [np.less(x, y)]
impl_rules[transpose_p] = lambda x, *, perm: [np.transpose(x, perm)]

def broadcast_impl(x, *, shape, axes):
    for axis in sorted(axes):
        x = np.expand_dims(x, axis)
    return [np.broadcast_to(x, shape)]
impl_rules[broadcast_p] = broadcast_impl

# ============================================================
# Forward-Mode Autodiff (JVP)
# ============================================================

def zeros_like(val):
    aval = get_aval(val)
    return np.zeros(aval.shape, aval.dtype)

def unzip2(pairs):
    lst1, lst2 = [], []
    for x1, x2 in pairs:
        lst1.append(x1)
        lst2.append(x2)
    return lst1, lst2

map = lambda f, *xs: list(builtins.map(f, *xs))
zip = lambda *args: list(builtins.zip(*args))

class JVPTracer(Tracer):
    def __init__(self, trace, primal, tangent):
        self._trace = trace
        self.primal = primal
        self.tangent = tangent
    @property
    def aval(self): return get_aval(self.primal)

class JVPTrace(Trace):
    pure = lift = lambda self, val: JVPTracer(self, val, zeros_like(val))
    def process_primitive(self, primitive, tracers, params):
        primals_in, tangents_in = unzip2((t.primal, t.tangent) for t in tracers)
        jvp_rule = jvp_rules[primitive]
        primal_outs, tangent_outs = jvp_rule(primals_in, tangents_in, **params)
        return [JVPTracer(self, x, t) for x, t in zip(primal_outs, tangent_outs)]

jvp_rules = {}

def add_jvp(primals, tangents):
    (x, y), (x_dot, y_dot) = primals, tangents
    return [x + y], [x_dot + y_dot]
jvp_rules[add_p] = add_jvp

def mul_jvp(primals, tangents):
    (x, y), (x_dot, y_dot) = primals, tangents
    return [x * y], [x_dot * y + x * y_dot]
jvp_rules[mul_p] = mul_jvp

def sin_jvp(primals, tangents):
    (x,), (x_dot,) = primals, tangents
    return [sin(x)], [cos(x) * x_dot]
jvp_rules[sin_p] = sin_jvp

def cos_jvp(primals, tangents):
    (x,), (x_dot,) = primals, tangents
    return [cos(x)], [neg(sin(x)) * x_dot]
jvp_rules[cos_p] = cos_jvp

def neg_jvp(primals, tangents):
    (x,), (x_dot,) = primals, tangents
    return [neg(x)], [neg(x_dot)]
jvp_rules[neg_p] = neg_jvp

def exp_jvp(primals, tangents):
    (x,), (x_dot,) = primals, tangents
    e = exp(x)
    return [e], [e * x_dot]
jvp_rules[exp_p] = exp_jvp

def log_jvp(primals, tangents):
    (x,), (x_dot,) = primals, tangents
    return [log(x)], [x_dot / x]
jvp_rules[log_p] = log_jvp

def div_jvp(primals, tangents):
    (x, y), (x_dot, y_dot) = primals, tangents
    primal_out = x / y
    tangent_out = (x_dot - primal_out * y_dot) / y
    return [primal_out], [tangent_out]
jvp_rules[div_p] = div_jvp

def reduce_sum_jvp(primals, tangents, *, axis):
    (x,), (x_dot,) = primals, tangents
    return [reduce_sum(x, axis)], [reduce_sum(x_dot, axis)]
jvp_rules[reduce_sum_p] = reduce_sum_jvp

def greater_jvp(primals, tangents):
    (x, y), _ = primals, tangents
    out_primal = greater(x, y)
    return [out_primal], [zeros_like(out_primal)]
jvp_rules[greater_p] = greater_jvp

def less_jvp(primals, tangents):
    (x, y), _ = primals, tangents
    out_primal = less(x, y)
    return [out_primal], [zeros_like(out_primal)]
jvp_rules[less_p] = less_jvp

def broadcast_jvp(primals, tangents, *, shape, axes):
    (x,), (x_dot,) = primals, tangents
    return [broadcast(x, shape, axes)], [broadcast(x_dot, shape, axes)]
jvp_rules[broadcast_p] = broadcast_jvp

def transpose_jvp(primals, tangents, *, perm):
    (x,), (x_dot,) = primals, tangents
    return [transpose_op(x, perm)], [transpose_op(x_dot, perm)]
jvp_rules[transpose_p] = transpose_jvp

# --- JVP user API ---

def jvp_flat(f, primals, tangents):
    with new_main(JVPTrace) as main:
        trace = JVPTrace(main)
        tracers_in = [JVPTracer(trace, x, t) for x, t in zip(primals, tangents)]
        outs = f(*tracers_in)
        tracers_out = [full_raise(trace, out) for out in outs]
        primals_out, tangents_out = unzip2((t.primal, t.tangent) for t in tracers_out)
    return primals_out, tangents_out

def jvp(f, primals, tangents):
    primals_flat, in_tree = tree_flatten(primals)
    tangents_flat, in_tree2 = tree_flatten(tangents)
    if in_tree != in_tree2: raise TypeError
    f, out_tree = flatten_fun(f, in_tree)
    primals_out_flat, tangents_out_flat = jvp_flat(f, primals_flat, tangents_flat)
    primals_out = tree_unflatten(out_tree(), primals_out_flat)
    tangents_out = tree_unflatten(out_tree(), tangents_out_flat)
    return primals_out, tangents_out

# ============================================================
# Pytree Handling
# ============================================================

class NodeType(NamedTuple):
    name: str
    to_iterable: Callable
    from_iterable: Callable

node_types: dict[type, NodeType] = {}

def register_pytree_node(ty, to_iter, from_iter):
    node_types[ty] = NodeType(str(ty), to_iter, from_iter)

register_pytree_node(tuple, lambda t: (None, t), lambda _, xs: tuple(xs))
register_pytree_node(list, lambda l: (None, l), lambda _, xs: list(xs))
register_pytree_node(dict,
                     lambda d: builtins.map(tuple, unzip2(sorted(d.items()))),
                     lambda keys, vals: dict(builtins.zip(keys, vals)))

class PyTreeDef(NamedTuple):
    node_type: NodeType
    node_metadata: Hashable
    child_treedefs: tuple

class Leaf: pass
leaf = Leaf()

def tree_flatten(x):
    children_iter, treedef = _tree_flatten(x)
    return list(children_iter), treedef

def _tree_flatten(x):
    node_type = node_types.get(type(x))
    if node_type:
        node_metadata, children = node_type.to_iterable(x)
        children_flat, child_trees = unzip2(map(_tree_flatten, children))
        flattened = it.chain.from_iterable(children_flat)
        return flattened, PyTreeDef(node_type, node_metadata, tuple(child_trees))
    else:
        return [x], leaf

def tree_unflatten(treedef, xs):
    return _tree_unflatten(treedef, iter(xs))

def _tree_unflatten(treedef, xs):
    if treedef is leaf:
        return next(xs)
    else:
        children = (_tree_unflatten(t, xs) for t in treedef.child_treedefs)
        return treedef.node_type.from_iterable(treedef.node_metadata, children)

class _Empty: pass
_empty = _Empty()

class _Store:
    val = _empty
    def set_value(self, val):
        assert self.val is _empty
        self.val = val
    def __call__(self): return self.val

def flatten_fun(f, in_tree):
    store = _Store()
    def flat_fun(*args_flat):
        pytree_args = tree_unflatten(in_tree, args_flat)
        out = f(*pytree_args)
        out_flat, out_tree = tree_flatten(out)
        store.set_value(out_tree)
        return out_flat
    return flat_fun, store

# ============================================================
# Jaxpr Data Structures
# ============================================================

class Var:
    def __init__(self, aval): self.aval = aval

class Lit:
    def __init__(self, val):
        self.aval = raise_to_shaped(get_aval(val))
        self.val = np.array(val, self.aval.dtype)

Atom = Union[Var, Lit]

class JaxprEqn(NamedTuple):
    primitive: Primitive
    inputs: list
    params: dict
    out_binders: list

class Jaxpr:
    def __init__(self, in_binders, eqns, outs):
        self.in_binders = in_binders
        self.eqns = eqns
        self.outs = outs
    def __hash__(self): return id(self)
    def __eq__(self, other): return self is other
    def __repr__(self): return pp_jaxpr(self)

class JaxprType(NamedTuple):
    in_types: list
    out_types: list

# ============================================================
# Jaxpr Type Checking
# ============================================================

def typecheck_jaxpr(jaxpr):
    env = set()
    for v in jaxpr.in_binders:
        if v in env: raise TypeError
        env.add(v)
    for eqn in jaxpr.eqns:
        in_types = [typecheck_atom(env, x) for x in eqn.inputs]
        out_types = abstract_eval_rules[eqn.primitive](*in_types, **eqn.params)
        for out_binder, out_type in builtins.zip(eqn.out_binders, out_types):
            if not out_type == out_binder.aval: raise TypeError
        for out_binder in eqn.out_binders:
            if out_binder in env: raise TypeError
            env.add(out_binder)
    in_types = [v.aval for v in jaxpr.in_binders]
    out_types = [typecheck_atom(env, x) for x in jaxpr.outs]
    return JaxprType(in_types, out_types)

def typecheck_atom(env, x):
    if isinstance(x, Var):
        if x not in env: raise TypeError("unbound variable")
        return x.aval
    elif isinstance(x, Lit):
        return raise_to_shaped(get_aval(x.val))
    else:
        assert False

# ============================================================
# Abstract Evaluation Rules
# ============================================================

abstract_eval_rules = {}

def binop_abstract_eval(x, y):
    if not isinstance(x, ShapedArray) or not isinstance(y, ShapedArray):
        raise TypeError
    if raise_to_shaped(x) != raise_to_shaped(y): raise TypeError
    return [ShapedArray(x.shape, x.dtype)]

abstract_eval_rules[add_p] = binop_abstract_eval
abstract_eval_rules[mul_p] = binop_abstract_eval
abstract_eval_rules[div_p] = binop_abstract_eval

def compare_abstract_eval(x, y):
    if not isinstance(x, ShapedArray) or not isinstance(y, ShapedArray):
        raise TypeError
    if x.shape != y.shape: raise TypeError
    return [ShapedArray(x.shape, np.dtype('bool'))]
abstract_eval_rules[greater_p] = compare_abstract_eval
abstract_eval_rules[less_p] = compare_abstract_eval

def vectorized_unop_abstract_eval(x):
    return [ShapedArray(x.shape, x.dtype)]
abstract_eval_rules[sin_p] = vectorized_unop_abstract_eval
abstract_eval_rules[cos_p] = vectorized_unop_abstract_eval
abstract_eval_rules[neg_p] = vectorized_unop_abstract_eval
abstract_eval_rules[exp_p] = vectorized_unop_abstract_eval
abstract_eval_rules[log_p] = vectorized_unop_abstract_eval

def reduce_sum_abstract_eval(x, *, axis):
    axis_ = set(axis)
    new_shape = [d for i, d in enumerate(x.shape) if i not in axis_]
    return [ShapedArray(tuple(new_shape), x.dtype)]
abstract_eval_rules[reduce_sum_p] = reduce_sum_abstract_eval

def broadcast_abstract_eval(x, *, shape, axes):
    return [ShapedArray(tuple(shape), x.dtype)]
abstract_eval_rules[broadcast_p] = broadcast_abstract_eval

def transpose_abstract_eval(x, *, perm):
    return [ShapedArray(tuple(x.shape[p] for p in perm), x.dtype)]
abstract_eval_rules[transpose_p] = transpose_abstract_eval

# ============================================================
# Jaxpr Evaluation
# ============================================================

def eval_jaxpr(jaxpr, args):
    env = {}
    def read(x): return env[x] if type(x) is Var else x.val
    def write(v, val):
        assert v not in env
        env[v] = val
    map(write, jaxpr.in_binders, args)
    for eqn in jaxpr.eqns:
        in_vals = map(read, eqn.inputs)
        outs = bind(eqn.primitive, *in_vals, **eqn.params)
        map(write, eqn.out_binders, outs)
    return map(read, jaxpr.outs)

def jaxpr_as_fun(jaxpr):
    return lambda *args: eval_jaxpr(jaxpr, args)

# ============================================================
# Jaxpr Tracing (make_jaxpr)
# ============================================================

class JaxprTracer(Tracer):
    __slots__ = ['aval']
    def __init__(self, trace, aval):
        self._trace = trace
        self.aval = aval

class JaxprTrace(Trace):
    def new_arg(self, aval):
        aval = raise_to_shaped(aval)
        tracer = self.builder.new_tracer(self, aval)
        self.builder.tracer_to_var[id(tracer)] = Var(aval)
        return tracer

    def get_or_make_const_tracer(self, val):
        tracer = self.builder.const_tracers.get(id(val))
        if tracer is None:
            tracer = self.builder.new_tracer(self, raise_to_shaped(get_aval(val)))
            self.builder.add_const(tracer, val)
        return tracer
    pure = lift = get_or_make_const_tracer

    def process_primitive(self, primitive, tracers, params):
        avals_in = [t.aval for t in tracers]
        avals_out = abstract_eval_rules[primitive](*avals_in, **params)
        out_tracers = [self.builder.new_tracer(self, a) for a in avals_out]
        inputs = [self.builder.getvar(t) for t in tracers]
        outvars = [self.builder.add_var(t) for t in out_tracers]
        self.builder.add_eqn(JaxprEqn(primitive, inputs, params, outvars))
        return out_tracers

    @property
    def builder(self): return self.main.global_data

class JaxprBuilder:
    def __init__(self):
        self.eqns = []
        self.tracer_to_var = {}
        self.const_tracers = {}
        self.constvals = {}
        self.tracers = []

    def new_tracer(self, trace, aval):
        tracer = JaxprTracer(trace, aval)
        self.tracers.append(tracer)
        return tracer

    def add_eqn(self, eqn): self.eqns.append(eqn)

    def add_var(self, tracer):
        assert id(tracer) not in self.tracer_to_var
        var = self.tracer_to_var[id(tracer)] = Var(tracer.aval)
        return var

    def getvar(self, tracer):
        var = self.tracer_to_var.get(id(tracer))
        assert var is not None
        return var

    def add_const(self, tracer, val):
        var = self.add_var(tracer)
        self.const_tracers[id(val)] = tracer
        self.constvals[var] = val
        return var

    def build(self, in_tracers, out_tracers):
        constvars, constvals = unzip2(self.constvals.items())
        t2v = lambda t: self.tracer_to_var[id(t)]
        in_binders = constvars + [t2v(t) for t in in_tracers]
        out_vars = [t2v(t) for t in out_tracers]
        jaxpr = Jaxpr(in_binders, self.eqns, out_vars)
        typecheck_jaxpr(jaxpr)
        jaxpr, constvals = _inline_literals(jaxpr, constvals)
        return jaxpr, constvals

def _inline_literals(jaxpr, consts):
    const_binders, other_binders = split_list(jaxpr.in_binders, len(consts))
    scalars = [type(x) in jax_types and not get_aval(x).shape for x in consts]
    new_const_binders, lit_binders = partition_list(scalars, const_binders)
    new_consts, lit_vals = partition_list(scalars, consts)
    literals = dict(builtins.zip(lit_binders, map(Lit, lit_vals)))
    new_eqns = [JaxprEqn(eqn.primitive, [literals.get(x, x) for x in eqn.inputs],
                         eqn.params, eqn.out_binders) for eqn in jaxpr.eqns]
    new_outs = [literals.get(x, x) for x in jaxpr.outs]
    new_jaxpr = Jaxpr(new_const_binders + other_binders, new_eqns, new_outs)
    typecheck_jaxpr(new_jaxpr)
    return new_jaxpr, new_consts

@lru_cache
def make_jaxpr(f, *avals_in):
    avals_in, in_tree = tree_flatten(avals_in)
    f, out_tree = flatten_fun(f, in_tree)
    builder = JaxprBuilder()
    with new_main(JaxprTrace, builder) as main:
        with new_dynamic(main):
            trace = JaxprTrace(main)
            tracers_in = [trace.new_arg(aval) for aval in avals_in]
            outs = f(*tracers_in)
            tracers_out = [full_raise(trace, out) for out in outs]
            jaxpr, consts = builder.build(tracers_in, tracers_out)
    return jaxpr, consts, out_tree()

# ============================================================
# Utility Functions
# ============================================================

def split_list(lst, n):
    assert 0 <= n <= len(lst)
    return lst[:n], lst[n:]

def split_half(lst):
    assert not len(lst) % 2
    return split_list(lst, len(lst) // 2)

def partition_list(bs, l):
    assert len(bs) == len(l)
    lst1, lst2 = [], []
    for b, x in builtins.zip(bs, l):
        (lst2 if b else lst1).append(x)
    return lst1, lst2

def merge_lists(which, l1, l2):
    l1, l2 = iter(l1), iter(l2)
    out = [next(l2) if b else next(l1) for b in which]
    assert next(l1, None) is next(l2, None) is None
    return out

# ============================================================
# Pretty Printing
# ============================================================

def pp_jaxpr(jaxpr):
    namegen = (''.join(s) for r in it.count(1)
               for s in it.permutations(string.ascii_lowercase, r))
    names = defaultdict(lambda: next(namegen))
    in_binders = ', '.join(f'{names[x]}:{x.aval.str_short()}' for x in jaxpr.in_binders)
    lines = [f'{{ lambda {in_binders} .']
    lines.append('  let')
    for eqn in jaxpr.eqns:
        lhs = ' '.join(f'{names[v]}:{v.aval.str_short()}' for v in eqn.out_binders)
        args = ' '.join(names[x] if isinstance(x, Var) else builtins.str(x.val)
                        for x in eqn.inputs)
        params_str = ''
        if eqn.params:
            params_str = ' [ ' + ', '.join(f'{k}={v}' for k, v in sorted(eqn.params.items())) + ' ]'
        lines.append(f'    {lhs} = {eqn.primitive.name}{params_str} {args}')
    outs = ', '.join(names[v] if isinstance(v, Var) else builtins.str(v.val)
                     for v in jaxpr.outs)
    lines.append(f'  in ( {outs} ) }}')
    return '\n'.join(lines)
