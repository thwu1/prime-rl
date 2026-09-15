#!/usr/bin/env python3
"""
Sign analysis using Lark parser generator.

"""

import json
import sys
import os
from enum import Enum
from lark import Lark, Transformer, Token


# ── Sign Lattice ──────────────────────────────────────────────────────────────

class Sign(Enum):
    BOTTOM = 0
    NEG = 1
    ZERO = 2
    POS = 3
    TOP = 4


def sign_join(a, b):
    if a == Sign.BOTTOM: return b
    if b == Sign.BOTTOM: return a
    if a == Sign.TOP or b == Sign.TOP: return Sign.TOP
    if a == b: return a
    return Sign.TOP


def sign_meet(a, b):
    if a == Sign.TOP: return b
    if b == Sign.TOP: return a
    if a == Sign.BOTTOM or b == Sign.BOTTOM: return Sign.BOTTOM
    if a == b: return a
    return Sign.BOTTOM


def sign_negate(a):
    if a == Sign.NEG: return Sign.POS
    if a == Sign.POS: return Sign.NEG
    return a


def sign_add(a, b):
    if a == Sign.BOTTOM or b == Sign.BOTTOM: return Sign.BOTTOM
    if a == Sign.TOP or b == Sign.TOP: return Sign.TOP
    if a == Sign.ZERO: return b
    if b == Sign.ZERO: return a
    if a == b: return a
    return Sign.TOP


def sign_sub(a, b):
    return sign_add(a, sign_negate(b))


def sign_mul(a, b):
    if a == Sign.BOTTOM or b == Sign.BOTTOM: return Sign.BOTTOM
    if a == Sign.ZERO or b == Sign.ZERO: return Sign.ZERO
    if a == Sign.TOP or b == Sign.TOP: return Sign.TOP
    if a == b: return Sign.POS
    return Sign.NEG


def sign_of_int(n):
    if n < 0: return Sign.NEG
    if n == 0: return Sign.ZERO
    return Sign.POS


SIGN_STR = {
    Sign.BOTTOM: "bottom", Sign.NEG: "neg", Sign.ZERO: "zero",
    Sign.POS: "pos", Sign.TOP: "top",
}


# ── AST Nodes ─────────────────────────────────────────────────────────────────

class Expr:
    pass

class IntLit(Expr):
    def __init__(self, value):
        self.value = value

class VarRef(Expr):
    def __init__(self, name):
        self.name = name

class BinOp(Expr):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class Cond:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class Stmt:
    pass

class Assign(Stmt):
    def __init__(self, var, expr):
        self.var = var
        self.expr = expr

_call_counter = 0

class FuncCall(Stmt):
    def __init__(self, var, func_name, args):
        global _call_counter
        self.var = var
        self.func_name = func_name
        self.args = args
        _call_counter += 1
        self.site_id = _call_counter

class IfStmt(Stmt):
    def __init__(self, cond, then_body, else_body):
        self.cond = cond
        self.then_body = then_body
        self.else_body = else_body

class WhileStmt(Stmt):
    def __init__(self, cond, body):
        self.cond = cond
        self.body = body

class ReturnStmt(Stmt):
    def __init__(self, expr):
        self.expr = expr

class FuncDef:
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body

class Program:
    def __init__(self, functions):
        self.functions = {f.name: f for f in functions}


# ── Lark AST Builder ─────────────────────────────────────────────────────────

class ASTBuilder(Transformer):
    def int_lit(self, items):
        return IntLit(int(items[0]))

    def var_ref(self, items):
        return VarRef(str(items[0]))

    def add_expr(self, items):
        return BinOp("+", items[0], items[1])

    def sub_expr(self, items):
        return BinOp("-", items[0], items[1])

    def mul_expr(self, items):
        return BinOp("*", items[0], items[1])

    def cond(self, items):
        return Cond(str(items[1]), items[0], items[2])

    def param_list(self, items):
        return [str(t) for t in items]

    def arg_list(self, items):
        return list(items)

    def block(self, items):
        return list(items)

    def assign_stmt(self, items):
        return Assign(str(items[0]), items[1])

    def call_stmt(self, items):
        return FuncCall(str(items[0]), str(items[1]), items[2])

    def if_stmt(self, items):
        return IfStmt(items[0], items[1], items[2])

    def while_stmt(self, items):
        return WhileStmt(items[0], items[1])

    def return_stmt(self, items):
        return ReturnStmt(items[0])

    def function_def(self, items):
        return FuncDef(str(items[0]), items[1], items[2])

    def start(self, items):
        return Program(list(items))


# ── Abstract State ────────────────────────────────────────────────────────────

class AbsState:
    def __init__(self, m=None):
        self.m = dict(m) if m else {}

    def get(self, var):
        return self.m.get(var, Sign.BOTTOM)

    def set(self, var, val):
        s = AbsState(self.m)
        s.m[var] = val
        return s

    def join(self, other):
        r = AbsState()
        for v in set(self.m) | set(other.m):
            r.m[v] = sign_join(self.get(v), other.get(v))
        return r

    def __eq__(self, other):
        if not isinstance(other, AbsState):
            return False
        for v in set(self.m) | set(other.m):
            if self.get(v) != other.get(v):
                return False
        return True

    def copy(self):
        return AbsState(self.m)

    def to_dict(self):
        return {k: SIGN_STR[v] for k, v in self.m.items()}


# ── Analyzer ──────────────────────────────────────────────────────────────────

SWAP_OP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "==", "!=": "!="}


class Analyzer:
    def __init__(self, program, context_depth=2):
        self.program = program
        self.context_depth = context_depth
        self.summaries = {}
        self.analyzing = set()

    def analyze(self):
        state = AbsState()
        result_state, _ = self._analyze_function("main", [], state, ())
        return result_state.to_dict()

    def _ctx_key(self, func_name, arg_signs, cs):
        trimmed = cs[-self.context_depth:] if len(cs) > self.context_depth else cs
        return (func_name, trimmed, arg_signs)

    def _analyze_function(self, func_name, arg_signs, caller_state, call_string):
        func = self.program.functions[func_name]
        arg_t = tuple(arg_signs)
        ctx = self._ctx_key(func_name, arg_t, call_string)

        if ctx in self.summaries and ctx not in self.analyzing:
            return AbsState(), self.summaries[ctx]

        if ctx in self.analyzing:
            return AbsState(), self.summaries.get(ctx, Sign.BOTTOM)

        self.analyzing.add(ctx)
        state = AbsState()
        for p, s in zip(func.params, arg_signs):
            state = state.set(p, s)

        prev_ret = Sign.BOTTOM
        for _ in range(30):
            self.summaries[ctx] = prev_ret
            result_state, ret = self._analyze_stmts(func.body, state, call_string)
            if ret == prev_ret:
                break
            prev_ret = sign_join(prev_ret, ret)
            self.summaries[ctx] = prev_ret

        self.analyzing.discard(ctx)
        self.summaries[ctx] = prev_ret
        return result_state, prev_ret

    def _analyze_stmts(self, stmts, state, cs):
        ret = Sign.BOTTOM
        for stmt in stmts:
            state, r = self._analyze_stmt(stmt, state, cs)
            if r != Sign.BOTTOM:
                ret = sign_join(ret, r)
        return state, ret

    def _analyze_stmt(self, stmt, state, cs):
        if isinstance(stmt, Assign):
            val = self._eval(stmt.expr, state)
            return state.set(stmt.var, val), Sign.BOTTOM

        if isinstance(stmt, FuncCall):
            arg_signs = [self._eval(a, state) for a in stmt.args]
            new_cs = cs + (stmt.site_id,)
            _, ret = self._analyze_function(stmt.func_name, arg_signs, state, new_cs)
            return state.set(stmt.var, ret), Sign.BOTTOM

        if isinstance(stmt, IfStmt):
            ts = self._refine(state, stmt.cond, True)
            fs = self._refine(state, stmt.cond, False)
            then_st, then_r = self._analyze_stmts(stmt.then_body, ts, cs)
            else_st, else_r = self._analyze_stmts(stmt.else_body, fs, cs)
            return then_st.join(else_st), sign_join(then_r, else_r)

        if isinstance(stmt, WhileStmt):
            init = state
            loop_st = state
            acc_ret = Sign.BOTTOM
            for _ in range(60):
                entry = self._refine(loop_st, stmt.cond, True)
                body_st, body_r = self._analyze_stmts(stmt.body, entry, cs)
                acc_ret = sign_join(acc_ret, body_r)
                new_st = init.join(body_st)
                if new_st == loop_st:
                    break
                loop_st = new_st
            exit_st = self._refine(loop_st, stmt.cond, False)
            return exit_st, acc_ret

        if isinstance(stmt, ReturnStmt):
            return state, self._eval(stmt.expr, state)

        raise ValueError(f"Unknown stmt: {type(stmt)}")

    def _eval(self, expr, state):
        if isinstance(expr, IntLit):
            return sign_of_int(expr.value)
        if isinstance(expr, VarRef):
            return state.get(expr.name)
        if isinstance(expr, BinOp):
            l = self._eval(expr.left, state)
            r = self._eval(expr.right, state)
            if expr.op == "+": return sign_add(l, r)
            if expr.op == "-": return sign_sub(l, r)
            if expr.op == "*": return sign_mul(l, r)
            if l == Sign.BOTTOM or r == Sign.BOTTOM: return Sign.BOTTOM
            if l == Sign.ZERO: return Sign.ZERO
            return Sign.TOP
        raise ValueError(f"Unknown expr: {type(expr)}")

    def _refine(self, state, cond, branch):
        new = state.copy()
        if isinstance(cond.left, VarRef):
            rhs_sign = self._eval(cond.right, state)
            cur = state.get(cond.left.name)
            new = new.set(cond.left.name,
                          self._refine_sign(cur, cond.op, rhs_sign, branch))
        if isinstance(cond.right, VarRef):
            lhs_sign = self._eval(cond.left, state)
            cur = state.get(cond.right.name)
            new = new.set(cond.right.name,
                          self._refine_sign(cur, SWAP_OP[cond.op], lhs_sign, branch))
        return new

    def _refine_sign(self, vs, op, rhs, branch):
        if vs == Sign.BOTTOM:
            return Sign.BOTTOM
        if rhs != Sign.ZERO:
            return vs
        if op == "<":
            return sign_meet(vs, Sign.NEG) if branch else (Sign.BOTTOM if vs == Sign.NEG else vs)
        if op == ">":
            return sign_meet(vs, Sign.POS) if branch else (Sign.BOTTOM if vs == Sign.POS else vs)
        if op == "==":
            return sign_meet(vs, Sign.ZERO) if branch else (Sign.BOTTOM if vs == Sign.ZERO else vs)
        if op == "!=":
            return (Sign.BOTTOM if vs == Sign.ZERO else vs) if branch else sign_meet(vs, Sign.ZERO)
        if op == "<=":
            return (Sign.BOTTOM if vs == Sign.POS else vs) if branch else sign_meet(vs, Sign.POS)
        if op == ">=":
            return (Sign.BOTTOM if vs == Sign.NEG else vs) if branch else sign_meet(vs, Sign.NEG)
        return vs


# ── Main ──────────────────────────────────────────────────────────────────────

GRAMMAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grammar.lark")


def parse_and_analyze(filename):
    with open(GRAMMAR_PATH) as f:
        grammar_text = f.read()
    lark_parser = Lark(grammar_text, parser="lalr")

    with open(filename) as f:
        code = f.read()
    tree = lark_parser.parse(code)
    program = ASTBuilder().transform(tree)
    return Analyzer(program, context_depth=2).analyze()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 analyzer.py <program_file>", file=sys.stderr)
        sys.exit(1)
    result = parse_and_analyze(sys.argv[1])
    print(json.dumps(result, indent=2))
