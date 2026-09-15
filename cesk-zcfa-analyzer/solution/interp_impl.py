"""
Interpreter for ANF Lambda Calculus.

Supports: closures, letrec, set!, call/cc, and arithmetic primitives.
"""


from lang import (
    parse, Exp, Lam, Var, IntLit, BoolLit, PrimOp,
    App, If, CallCC, SetBang, Letrec, Let,
)


# ============================================================
# Value Domains
# ============================================================

class Void:
    """The void value, returned by set!."""
    def __repr__(self):
        return "void"

VOID = Void()


class Closure:
    """A function closure: pairs a lambda with its defining environment."""
    def __init__(self, lam, env):
        self.lam = lam
        self.env = env

    def __repr__(self):
        return f"<closure {self.lam}>"


class Continuation:
    """A reified first-class continuation value (from call/cc)."""
    def __init__(self, kont):
        self.kont = kont

    def __repr__(self):
        return "<continuation>"


# ============================================================
# Continuation Frames
# ============================================================

class LetK:
    """Continuation frame for let: awaiting the bound value."""
    def __init__(self, var, body, env, kont):
        self.var = var
        self.body = body
        self.env = env
        self.kont = kont


class Halt:
    """Terminal continuation."""
    pass

HALT = Halt()


# ============================================================
# Machine State
# ============================================================

class State:
    def __init__(self, ctrl, env, store, kont):
        self.ctrl = ctrl
        self.env = env
        self.store = store
        self.kont = kont


# ============================================================
# Address Allocation
# ============================================================

_next_addr = 0

def _fresh_addr():
    global _next_addr
    _next_addr += 1
    return _next_addr


# ============================================================
# Atomic Evaluation
# ============================================================

def _eval_atomic(aexp, env, store):
    if isinstance(aexp, IntLit):
        return aexp.value
    elif isinstance(aexp, BoolLit):
        return aexp.value
    elif isinstance(aexp, Var):
        addr = env[aexp.name]
        return store[addr]
    elif isinstance(aexp, Lam):
        return Closure(aexp, dict(env))
    elif isinstance(aexp, PrimOp):
        args = [_eval_atomic(a, env, store) for a in aexp.args]
        return _apply_prim(aexp.op, args)
    else:
        raise RuntimeError(f"Not an atomic expression: {type(aexp).__name__}")


def _apply_prim(op, args):
    if op == '+':
        return args[0] + args[1]
    elif op == '-':
        return args[0] - args[1]
    elif op == '*':
        return args[0] * args[1]
    elif op == '=':
        return args[0] == args[1]
    elif op == '<':
        return args[0] < args[1]
    else:
        raise RuntimeError(f"Unknown primitive: {op}")


# ============================================================
# Continuation Application
# ============================================================

def _apply_kont(kont, value, store):
    if isinstance(kont, Halt):
        return value
    elif isinstance(kont, LetK):
        addr = _fresh_addr()
        env = dict(kont.env)
        env[kont.var] = addr
        store[addr] = value
        return State(kont.body, env, store, kont.kont)
    else:
        raise RuntimeError(f"Unknown continuation type: {type(kont).__name__}")


# ============================================================
# Procedure Application
# ============================================================

def _apply_proc(proc, args, store, kont):
    if isinstance(proc, Closure):
        lam = proc.lam
        env = dict(proc.env)
        for param, arg_val in zip(lam.params, args):
            addr = _fresh_addr()
            env[param] = addr
            store[addr] = arg_val
        return State(lam.body, env, store, kont)
    elif isinstance(proc, Continuation):
        return _apply_kont(proc.kont, args[0], store)
    else:
        raise RuntimeError(f"Cannot apply non-procedure: {proc}")


# ============================================================
# Step Function
# ============================================================

def _step(state):
    ctrl = state.ctrl
    env = state.env
    store = state.store
    kont = state.kont

    if isinstance(ctrl, (IntLit, BoolLit, Var, Lam, PrimOp)):
        value = _eval_atomic(ctrl, env, store)
        return _apply_kont(kont, value, store)

    elif isinstance(ctrl, Let):
        new_kont = LetK(ctrl.var, ctrl.body, env, kont)
        return State(ctrl.rhs, env, store, new_kont)

    elif isinstance(ctrl, App):
        proc = _eval_atomic(ctrl.func, env, store)
        arg_vals = [_eval_atomic(a, env, store) for a in ctrl.args]
        return _apply_proc(proc, arg_vals, store, kont)

    elif isinstance(ctrl, If):
        cond_val = _eval_atomic(ctrl.cond, env, store)
        if cond_val is not False:
            return State(ctrl.then_exp, env, store, kont)
        else:
            return State(ctrl.else_exp, env, store, kont)

    elif isinstance(ctrl, SetBang):
        value = _eval_atomic(ctrl.val, env, store)
        addr = env[ctrl.var]
        store[addr] = value
        return _apply_kont(kont, VOID, store)

    elif isinstance(ctrl, Letrec):
        env_new = dict(env)
        addrs = []
        for var, _ in ctrl.bindings:
            addr = _fresh_addr()
            env_new[var] = addr
            addrs.append(addr)
        for (var, aexp), addr in zip(ctrl.bindings, addrs):
            value = _eval_atomic(aexp, env_new, store)
            store[addr] = value
        return State(ctrl.body, env_new, store, kont)

    elif isinstance(ctrl, CallCC):
        proc = _eval_atomic(ctrl.func, env, store)
        cc = Continuation(kont)
        return _apply_proc(proc, [cc], store, kont)

    else:
        raise RuntimeError(f"Unknown expression type: {type(ctrl).__name__}")


# ============================================================
# Public API
# ============================================================

def run(text):
    """Parse and evaluate the program text. Returns the final value."""
    global _next_addr
    _next_addr = 0

    prog = parse(text)
    state = State(prog, {}, {}, HALT)

    while isinstance(state, State):
        state = _step(state)

    return state
