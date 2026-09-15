"""
0-CFA (Zeroth-Order Control-Flow Analysis) for ANF Lambda Calculus.

Computes a conservative mapping from variable names to sets of lambda
labels that may flow to each variable at runtime.

Uses constraint-based flow analysis with fixed-point iteration.
"""


from collections import defaultdict
from lang import (
    parse, Exp, Lam, Var, IntLit, BoolLit, PrimOp,
    App, If, CallCC, SetBang, Letrec, Let,
)


# ============================================================
# Lambda Collection
# ============================================================

def _collect_lambdas(exp, lambdas):
    """Recursively collect all Lam nodes into lambdas dict (label -> Lam)."""
    if isinstance(exp, Lam):
        lambdas[exp.label] = exp
        _collect_lambdas(exp.body, lambdas)
    elif isinstance(exp, Let):
        _collect_lambdas(exp.rhs, lambdas)
        _collect_lambdas(exp.body, lambdas)
    elif isinstance(exp, App):
        _collect_lambdas(exp.func, lambdas)
        for arg in exp.args:
            _collect_lambdas(arg, lambdas)
    elif isinstance(exp, If):
        _collect_lambdas(exp.cond, lambdas)
        _collect_lambdas(exp.then_exp, lambdas)
        _collect_lambdas(exp.else_exp, lambdas)
    elif isinstance(exp, Letrec):
        for _, aexp in exp.bindings:
            _collect_lambdas(aexp, lambdas)
        _collect_lambdas(exp.body, lambdas)
    elif isinstance(exp, SetBang):
        _collect_lambdas(exp.val, lambdas)
    elif isinstance(exp, CallCC):
        _collect_lambdas(exp.func, lambdas)
    elif isinstance(exp, PrimOp):
        for arg in exp.args:
            _collect_lambdas(arg, lambdas)


# ============================================================
# Flow Computation
# ============================================================

def _flow_of(exp, flow, lambdas, processing):
    """Compute the set of lambda labels that exp may evaluate to.

    Updates `flow` (variable -> set of labels) as a side effect.
    `processing` tracks lambda labels currently on the call stack
    to prevent infinite recursion.

    Returns frozenset of labels.
    """
    if isinstance(exp, Lam):
        return frozenset({exp.label})

    elif isinstance(exp, Var):
        return frozenset(flow[exp.name])

    elif isinstance(exp, (IntLit, BoolLit)):
        return frozenset()

    elif isinstance(exp, PrimOp):
        # Process arguments for side effects (e.g., variable lookups)
        for arg in exp.args:
            _flow_of(arg, flow, lambdas, processing)
        return frozenset()

    elif isinstance(exp, Let):
        rhs_flow = _flow_of(exp.rhs, flow, lambdas, processing)
        flow[exp.var] |= rhs_flow
        return _flow_of(exp.body, flow, lambdas, processing)

    elif isinstance(exp, App):
        func_flow = _flow_of(exp.func, flow, lambdas, processing)
        arg_flows = [_flow_of(a, flow, lambdas, processing) for a in exp.args]
        result = set()
        for label in func_flow:
            if label in lambdas:
                lam = lambdas[label]
                # Always flow arguments to parameters
                for param, af in zip(lam.params, arg_flows):
                    flow[param] |= af
                # Only process body if not already on the call stack
                if label not in processing:
                    processing.add(label)
                    body_flow = _flow_of(lam.body, flow, lambdas, processing)
                    result |= body_flow
                    processing.discard(label)
        return frozenset(result)

    elif isinstance(exp, If):
        _flow_of(exp.cond, flow, lambdas, processing)
        t_flow = _flow_of(exp.then_exp, flow, lambdas, processing)
        e_flow = _flow_of(exp.else_exp, flow, lambdas, processing)
        return t_flow | e_flow

    elif isinstance(exp, Letrec):
        for var, aexp in exp.bindings:
            af = _flow_of(aexp, flow, lambdas, processing)
            flow[var] |= af
        return _flow_of(exp.body, flow, lambdas, processing)

    elif isinstance(exp, SetBang):
        vf = _flow_of(exp.val, flow, lambdas, processing)
        flow[exp.var] |= vf
        return frozenset()

    elif isinstance(exp, CallCC):
        _flow_of(exp.func, flow, lambdas, processing)
        return frozenset()

    else:
        return frozenset()


# ============================================================
# Public API
# ============================================================

def analyze(text):
    """Perform 0-CFA on the given program text.

    Returns a dict mapping variable names (str) to sets of lambda
    labels (set of int) that may flow to each variable.
    """
    prog = parse(text)

    # Collect all lambda terms by label
    lambdas = {}
    _collect_lambdas(prog, lambdas)

    # Flow sets: variable name -> set of lambda labels
    flow = defaultdict(set)

    # Fixed-point iteration: repeat until no flow set grows
    while True:
        old_total = sum(len(v) for v in flow.values())
        _flow_of(prog, flow, lambdas, set())
        new_total = sum(len(v) for v in flow.values())
        if new_total == old_total:
            break

    return dict(flow)
