
"""
Stack-safe evaluator for the mini functional language with native operator library.
Uses constant Python stack space regardless of source-program recursion depth.
Delegates all binary operator evaluation to the compiled C library (libops.so).
"""

import sys
import os
import ctypes

sys.path.insert(0, '/app')

from dataclasses import dataclass
from typing import Union
from lang import (
    Expr, Var, IntLit, BoolLit, BinOp, If, Lam, App, Let, LetRec,
    VClosure, VRecClosure,
)


# ============ Native operator library via ctypes ============

_lib = ctypes.CDLL('/app/libops.so')

_lib.eval_binop.argtypes = [
    ctypes.c_int, ctypes.c_longlong, ctypes.c_longlong,
    ctypes.POINTER(ctypes.c_longlong), ctypes.POINTER(ctypes.c_int)
]
_lib.eval_binop.restype = ctypes.c_int

_lib.op_from_string.argtypes = [ctypes.c_char_p]
_lib.op_from_string.restype = ctypes.c_int


def native_apply_op(op_str, left, right):
    """Evaluate a binary operator using the native C library."""
    op_code = _lib.op_from_string(op_str.encode('utf-8'))
    if op_code < 0:
        raise ValueError(f"Unknown operator: {op_str}")
    out_val = ctypes.c_longlong()
    out_bool = ctypes.c_int()
    rc = _lib.eval_binop(
        op_code, ctypes.c_longlong(int(left)), ctypes.c_longlong(int(right)),
        ctypes.byref(out_val), ctypes.byref(out_bool)
    )
    if rc == -1:
        raise ZeroDivisionError(f"Division by zero: {left} {op_str} {right}")
    if rc != 0:
        raise RuntimeError(f"eval_binop error code: {rc}")
    if out_bool.value:
        return bool(out_val.value)
    return int(out_val.value)


# ============ Defunctionalized continuation constructors ============

@dataclass
class HaltK:
    pass

@dataclass
class BinOpLeftK:
    op: str
    right: Expr
    env: dict
    k: 'Kont'

@dataclass
class BinOpRightK:
    op: str
    left_val: object
    k: 'Kont'

@dataclass
class IfK:
    then_branch: Expr
    else_branch: Expr
    env: dict
    k: 'Kont'

@dataclass
class AppFuncK:
    arg: Expr
    env: dict
    k: 'Kont'

@dataclass
class AppArgK:
    func_val: object
    k: 'Kont'

@dataclass
class LetK:
    name: str
    body: Expr
    env: dict
    k: 'Kont'

Kont = Union[HaltK, BinOpLeftK, BinOpRightK, IfK, AppFuncK, AppArgK, LetK]


# ============ Trampoline states ============

@dataclass
class EvalState:
    expr: Expr
    env: dict
    k: Kont

@dataclass
class ContState:
    k: Kont
    val: object

@dataclass
class DoneState:
    val: object

State = Union[EvalState, ContState, DoneState]


# ============ Single-step transition functions ============

def step_eval(expr, env, k):
    if isinstance(expr, IntLit):
        return ContState(k, expr.value)
    if isinstance(expr, BoolLit):
        return ContState(k, expr.value)
    if isinstance(expr, Var):
        return ContState(k, env[expr.name])
    if isinstance(expr, BinOp):
        return EvalState(expr.left, env,
                         BinOpLeftK(expr.op, expr.right, env, k))
    if isinstance(expr, If):
        return EvalState(expr.cond, env,
                         IfK(expr.then_branch, expr.else_branch, env, k))
    if isinstance(expr, Lam):
        return ContState(k, VClosure(expr.param, expr.body, dict(env)))
    if isinstance(expr, App):
        return EvalState(expr.func, env,
                         AppFuncK(expr.arg, env, k))
    if isinstance(expr, Let):
        return EvalState(expr.value, env,
                         LetK(expr.name, expr.body, env, k))
    if isinstance(expr, LetRec):
        rec = VRecClosure(expr.name, expr.func_param,
                          expr.func_body, dict(env))
        rec.env[expr.name] = rec
        new_env = dict(env)
        new_env[expr.name] = rec
        return EvalState(expr.body, new_env, k)
    raise TypeError(f"Unknown expression: {type(expr)}")


def step_cont(k, val):
    if isinstance(k, HaltK):
        return DoneState(val)
    if isinstance(k, BinOpLeftK):
        return EvalState(k.right, k.env,
                         BinOpRightK(k.op, val, k.k))
    if isinstance(k, BinOpRightK):
        return ContState(k.k, native_apply_op(k.op, k.left_val, val))
    if isinstance(k, IfK):
        if val:
            return EvalState(k.then_branch, k.env, k.k)
        else:
            return EvalState(k.else_branch, k.env, k.k)
    if isinstance(k, AppFuncK):
        return EvalState(k.arg, k.env, AppArgK(val, k.k))
    if isinstance(k, AppArgK):
        fv = k.func_val
        if isinstance(fv, VRecClosure):
            new_env = dict(fv.env)
            new_env[fv.name] = fv
            new_env[fv.param] = val
            return EvalState(fv.body, new_env, k.k)
        if isinstance(fv, VClosure):
            new_env = dict(fv.env)
            new_env[fv.param] = val
            return EvalState(fv.body, new_env, k.k)
        raise TypeError(f"Cannot apply non-function: {fv}")
    if isinstance(k, LetK):
        new_env = dict(k.env)
        new_env[k.name] = val
        return EvalState(k.body, new_env, k.k)
    raise TypeError(f"Unknown continuation: {type(k)}")


# ============ Main entry point ============

def run(expr):
    """Evaluate an expression using constant Python stack space.
    Uses the native C library for all operator evaluation."""
    state = EvalState(expr, {}, HaltK())
    while True:
        if isinstance(state, EvalState):
            state = step_eval(state.expr, state.env, state.k)
        elif isinstance(state, ContState):
            state = step_cont(state.k, state.val)
        elif isinstance(state, DoneState):
            return state.val
