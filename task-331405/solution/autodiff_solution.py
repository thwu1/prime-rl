"""
Reverse-mode automatic differentiation for mini-JAX.
Implements grad via partial evaluation, linearization, and jaxpr transposition.
"""

import numpy as np
from weakref import ref
from functools import partial
import builtins

from minijax import (
    Primitive, Trace, Tracer, MainTrace,
    ShapedArray, ConcreteArray,
    bind, full_raise, full_lower, new_main,
    get_aval, raise_to_shaped, jax_types, vspace,
    add_p, mul_p, neg_p, sin_p, cos_p, exp_p, log_p, div_p,
    reduce_sum_p, greater_p, less_p, transpose_p, broadcast_p,
    add, mul, neg, div, broadcast, reduce_sum, transpose_op,
    JVPTrace, JVPTracer, jvp, jvp_flat, jvp_rules, zeros_like,
    Var, Lit, JaxprEqn, Jaxpr, JaxprType,
    abstract_eval_rules, eval_jaxpr, jaxpr_as_fun, make_jaxpr,
    typecheck_jaxpr,
    tree_flatten, tree_unflatten, flatten_fun, register_pytree_node,
    node_types,
    unzip2, map, zip, split_list, split_half, partition_list, merge_lists,
)


# ============================================================
# Partial Values
# ============================================================

class PartialVal:
    """A value that is either known (concrete) or unknown (abstract)."""
    def __init__(self, aval, const):
        self.aval = aval
        self.const = const

    @classmethod
    def known(cls, val):
        return cls(get_aval(val), val)

    @classmethod
    def unknown(cls, aval):
        return cls(aval, None)

    @property
    def is_known(self):
        return self.const is not None

    @property
    def is_unknown(self):
        return self.const is None


# ============================================================
# Recipe Types for Building Jaxpr from Partial Eval
# ============================================================

class LambdaBindingRecipe:
    pass

class ConstRecipe:
    def __init__(self, val):
        self.val = val

class JaxprEqnRecipe:
    def __init__(self, prim, tracers_in, params, avals_out, tracer_refs_out):
        self.prim = prim
        self.tracers_in = tracers_in
        self.params = params
        self.avals_out = avals_out
        self.tracer_refs_out = tracer_refs_out


# ============================================================
# Partial Evaluation Trace
# ============================================================

class PartialEvalTracer(Tracer):
    def __init__(self, trace, pval, recipe):
        self._trace = trace
        self.pval = pval
        self.recipe = recipe

    @property
    def aval(self):
        return self.pval.aval

    def full_lower(self):
        if self.pval.is_known:
            return full_lower(self.pval.const)
        return self


class PartialEvalTrace(Trace):
    def new_arg(self, pval):
        return PartialEvalTracer(self, pval, LambdaBindingRecipe())

    def lift(self, val):
        return PartialEvalTracer(self, PartialVal.known(val), None)
    pure = lift

    def instantiate_const(self, tracer):
        if tracer.pval.is_unknown:
            return tracer
        else:
            pval = PartialVal.unknown(raise_to_shaped(tracer.aval))
            return PartialEvalTracer(self, pval, ConstRecipe(tracer.pval.const))

    def process_primitive(self, primitive, tracers, params):
        if all(t.pval.is_known for t in tracers):
            return bind(primitive, *builtins.map(full_lower, tracers), **params)
        tracers_in = [self.instantiate_const(t) for t in tracers]
        avals_in = [t.aval for t in tracers_in]
        avals_out = abstract_eval_rules[primitive](*avals_in, **params)
        tracers_out = [PartialEvalTracer(self, PartialVal.unknown(aval), None)
                       for aval in avals_out]
        eqn = JaxprEqnRecipe(primitive, tracers_in, params, avals_out,
                              map(ref, tracers_out))
        for t in tracers_out:
            t.recipe = eqn
        return tracers_out


# ============================================================
# Building Jaxprs from Partial Eval Traces
# ============================================================

def _toposort(out_nodes, parents):
    if not out_nodes:
        return []
    out_nodes = _remove_duplicates(out_nodes)
    child_counts = {}
    stack = list(out_nodes)
    while stack:
        node = stack.pop()
        if id(node) in child_counts:
            child_counts[id(node)] += 1
        else:
            child_counts[id(node)] = 1
            stack.extend(parents(node))
    for node in out_nodes:
        child_counts[id(node)] -= 1
    sorted_nodes = []
    childless_nodes = [node for node in out_nodes if not child_counts[id(node)]]
    while childless_nodes:
        node = childless_nodes.pop()
        sorted_nodes.append(node)
        for parent in parents(node):
            if child_counts[id(parent)] == 1:
                childless_nodes.append(parent)
            else:
                child_counts[id(parent)] -= 1
    sorted_nodes = sorted_nodes[::-1]
    return sorted_nodes


def _remove_duplicates(lst):
    seen = set()
    return [x for x in lst if id(x) not in seen and not seen.add(id(x))]


def _tracer_parents(t):
    return t.recipe.tracers_in if isinstance(t.recipe, JaxprEqnRecipe) else []


def _recipe_to_eqn(tracer_to_var, recipe):
    inputs = [tracer_to_var[id(t)] for t in recipe.tracers_in]
    out_binders = [Var(aval) for aval in recipe.avals_out]
    for t_ref, var in builtins.zip(recipe.tracer_refs_out, out_binders):
        if t_ref() is not None:
            tracer_to_var[id(t_ref())] = var
    return JaxprEqn(recipe.prim, inputs, recipe.params, out_binders)


def _tracers_to_jaxpr(tracers_in, tracers_out):
    tracer_to_var = {id(t): Var(raise_to_shaped(t.aval)) for t in tracers_in}
    constvar_to_val = {}
    constid_to_var = {}
    processed_eqns = set()
    eqns = []

    for t in _toposort(tracers_out, _tracer_parents):
        if isinstance(t.recipe, LambdaBindingRecipe):
            assert id(t) in set(builtins.map(id, tracers_in))
        elif isinstance(t.recipe, ConstRecipe):
            val = t.recipe.val
            var = constid_to_var.get(id(val))
            if var is None:
                aval = raise_to_shaped(get_aval(val))
                var = constid_to_var[id(val)] = Var(aval)
                constvar_to_val[var] = val
            tracer_to_var[id(t)] = var
        elif isinstance(t.recipe, JaxprEqnRecipe):
            if id(t.recipe) not in processed_eqns:
                eqns.append(_recipe_to_eqn(tracer_to_var, t.recipe))
                processed_eqns.add(id(t.recipe))
        else:
            raise TypeError(t.recipe)

    constvars, constvals = unzip2(constvar_to_val.items())
    in_binders = list(constvars) + [tracer_to_var[id(t)] for t in tracers_in]
    out_vars = [tracer_to_var[id(t)] for t in tracers_out]
    jaxpr = Jaxpr(in_binders, eqns, out_vars)
    typecheck_jaxpr(jaxpr)
    return jaxpr, list(constvals)


# ============================================================
# Partial Evaluation
# ============================================================

def partial_eval_flat(f, pvals_in):
    with new_main(PartialEvalTrace) as main:
        trace = PartialEvalTrace(main)
        tracers_in = [trace.new_arg(pval) for pval in pvals_in]
        outs = f(*tracers_in)
        tracers_out = [full_raise(trace, out) for out in outs]
        pvals_out = [t.pval for t in tracers_out]
        unk_tracers_in = [t for t in tracers_in if t.pval.is_unknown]
        unk_tracers_out = [t for t in tracers_out if t.pval.is_unknown]
        jaxpr, consts = _tracers_to_jaxpr(unk_tracers_in, unk_tracers_out)
    return jaxpr, pvals_out, consts


# ============================================================
# Linearize
# ============================================================

def linearize_flat(f, *primals_in):
    pvals_in = ([PartialVal.known(x) for x in primals_in] +
                [PartialVal.unknown(vspace(get_aval(x))) for x in primals_in])

    def f_jvp(*primals_tangents_in):
        n = len(primals_tangents_in) // 2
        primals_list = list(primals_tangents_in[:n])
        tangents_list = list(primals_tangents_in[n:])
        primals_out, tangents_out = jvp_flat(f, primals_list, tangents_list)
        return [*primals_out, *tangents_out]

    jaxpr, pvals_out, consts = partial_eval_flat(f_jvp, pvals_in)
    primal_pvals, _ = split_half(pvals_out)
    assert all(pval.is_known for pval in primal_pvals)
    primals_out = [pval.const for pval in primal_pvals]
    f_lin = lambda *tangents: eval_jaxpr(jaxpr, [*consts, *tangents])
    return primals_out, f_lin


def linearize(f, *primals_in):
    primals_in_flat, in_tree = tree_flatten(primals_in)
    f, out_tree = flatten_fun(f, in_tree)
    primals_out_flat, f_lin_flat = linearize_flat(f, *primals_in_flat)
    primals_out = tree_unflatten(out_tree(), primals_out_flat)

    def f_lin(*tangents_in):
        tangents_in_flat, in_tree2 = tree_flatten(tangents_in)
        if in_tree != in_tree2:
            raise TypeError
        tangents_out_flat = f_lin_flat(*tangents_in_flat)
        return tree_unflatten(out_tree(), tangents_out_flat)

    return primals_out, f_lin


# ============================================================
# Transpose (Reverse-Mode Core)
# ============================================================

class UndefPrimal:
    """Marks an input position as the one we differentiate with respect to."""
    def __init__(self, aval):
        self.aval = aval

register_pytree_node(UndefPrimal,
                     lambda u: (u.aval, ()),
                     lambda aval, _: UndefPrimal(aval))


def eval_jaxpr_transposed(jaxpr, args, cotangents):
    """Evaluate a linear jaxpr in reverse, propagating cotangents."""
    primal_env = {}
    ct_env = {}

    def read_primal(x):
        return primal_env.get(x, UndefPrimal(x.aval)) if type(x) is Var else x.val

    def write_primal(v, val):
        if type(val) is not UndefPrimal:
            primal_env[v] = val

    def read_cotangent(v):
        return ct_env.pop(v, np.zeros(v.aval.shape, v.aval.dtype))

    def write_cotangent(x, val):
        if type(x) is Var and val is not None:
            ct_env[x] = add(ct_env[x], val) if x in ct_env else val

    map(write_primal, jaxpr.in_binders, args)
    map(write_cotangent, jaxpr.outs, cotangents)

    for eqn in jaxpr.eqns[::-1]:
        primals_in = map(read_primal, eqn.inputs)
        cts_in = map(read_cotangent, eqn.out_binders)
        rule = transpose_rules[eqn.primitive]
        cts_out = rule(cts_in, *primals_in, **eqn.params)
        map(write_cotangent, eqn.inputs, cts_out)

    return [read_cotangent(v) for v, x in builtins.zip(jaxpr.in_binders, args)
            if type(x) is UndefPrimal]


transpose_rules = {}


def mul_transpose_rule(cts, x, y):
    z_bar, = cts
    assert (type(x) is UndefPrimal) ^ (type(y) is UndefPrimal)
    if type(x) is UndefPrimal:
        return [mul(z_bar, y), None]
    else:
        return [None, mul(x, z_bar)]
transpose_rules[mul_p] = mul_transpose_rule


def add_transpose_rule(cts, x, y):
    z_bar, = cts
    return [z_bar, z_bar]
transpose_rules[add_p] = add_transpose_rule


def neg_transpose_rule(cts, x):
    y_bar, = cts
    assert type(x) is UndefPrimal
    return [neg(y_bar)]
transpose_rules[neg_p] = neg_transpose_rule


def div_transpose_rule(cts, x, y):
    z_bar, = cts
    # div(x, y) is linear in x when y is a residual
    assert type(x) is UndefPrimal and type(y) is not UndefPrimal
    return [div(z_bar, y), None]
transpose_rules[div_p] = div_transpose_rule


def reduce_sum_transpose_rule(cts, x, *, axis):
    y_bar, = cts
    return [broadcast(y_bar, x.aval.shape, axis)]
transpose_rules[reduce_sum_p] = reduce_sum_transpose_rule


def broadcast_transpose_rule(cts, x, *, shape, axes):
    z_bar, = cts
    return [reduce_sum(z_bar, axis=tuple(axes))]
transpose_rules[broadcast_p] = broadcast_transpose_rule


def transpose_op_transpose_rule(cts, x, *, perm):
    z_bar, = cts
    inv_perm = [0] * len(perm)
    for i, p in enumerate(perm):
        inv_perm[p] = i
    return [transpose_op(z_bar, tuple(inv_perm))]
transpose_rules[transpose_p] = transpose_op_transpose_rule


# ============================================================
# VJP and Grad
# ============================================================

def vjp_flat(f, *primals_in):
    pvals_in = ([PartialVal.known(x) for x in primals_in] +
                [PartialVal.unknown(vspace(get_aval(x))) for x in primals_in])

    def f_jvp(*primals_tangents_in):
        n = len(primals_tangents_in) // 2
        primals_list = list(primals_tangents_in[:n])
        tangents_list = list(primals_tangents_in[n:])
        primals_out, tangents_out = jvp_flat(f, primals_list, tangents_list)
        return [*primals_out, *tangents_out]

    jaxpr, pvals_out, consts = partial_eval_flat(f_jvp, pvals_in)
    primal_pvals, _ = split_half(pvals_out)
    assert all(pval.is_known for pval in primal_pvals)
    primals_out = [pval.const for pval in primal_pvals]
    tangent_pvals_in = pvals_in[len(primals_in):]
    transpose_inputs = consts + [UndefPrimal(p.aval) for p in tangent_pvals_in]
    f_vjp = lambda *cts: eval_jaxpr_transposed(jaxpr, transpose_inputs, cts)
    return primals_out, f_vjp


def vjp(f, *primals_in):
    primals_in_flat, in_tree = tree_flatten(primals_in)
    f, out_tree = flatten_fun(f, in_tree)
    primals_out_flat, f_vjp_flat = vjp_flat(f, *primals_in_flat)
    primals_out = tree_unflatten(out_tree(), primals_out_flat)

    def f_vjp(*cotangents_out):
        cotangents_out_flat, _ = tree_flatten(cotangents_out)
        cotangents_in_flat = f_vjp_flat(*cotangents_out_flat)
        return tree_unflatten(in_tree, cotangents_in_flat)

    return primals_out, f_vjp


def grad(f):
    """Compute the gradient of a scalar-valued function."""
    def gradfun(x, *xs):
        y, f_vjp = vjp(f, x, *xs)
        if np.shape(y) != ():
            raise TypeError("grad requires scalar output")
        x_bar, *_ = f_vjp(np.ones(np.shape(y), np.result_type(y)))
        return x_bar
    return gradfun
