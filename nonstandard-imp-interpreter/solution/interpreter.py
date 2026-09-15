#!/usr/bin/env python3
"""IMP interpreter using Lark parser generator, following nonstandard SOS rules.

"""

import json
import os
import sys
from lark import Lark, Transformer


# ---------------------------------------------------------------------------
# AST node classes
# ---------------------------------------------------------------------------

class Decl:
    __slots__ = ("name",)
    def __init__(self, name): self.name = name

class Assign:
    __slots__ = ("name", "expr")
    def __init__(self, name, expr): self.name = name; self.expr = expr

class IfElse:
    __slots__ = ("cond", "then_body", "else_body")
    def __init__(self, cond, then_body, else_body):
        self.cond = cond; self.then_body = then_body; self.else_body = else_body

class While:
    __slots__ = ("cond", "body")
    def __init__(self, cond, body): self.cond = cond; self.body = body

class HaltStmt: pass
class BreakStmt: pass
class ContinueStmt: pass

class BinOp:
    __slots__ = ("op", "left", "right")
    def __init__(self, op, left, right):
        self.op = op; self.left = left; self.right = right

class UnaryOp:
    __slots__ = ("op", "operand")
    def __init__(self, op, operand): self.op = op; self.operand = operand

class Var:
    __slots__ = ("name",)
    def __init__(self, name): self.name = name

class Num:
    __slots__ = ("value",)
    def __init__(self, value): self.value = value

class BoolLit:
    __slots__ = ("value",)
    def __init__(self, value): self.value = value

class RelOp:
    __slots__ = ("op", "left", "right")
    def __init__(self, op, left, right):
        self.op = op; self.left = left; self.right = right

class NotOp:
    __slots__ = ("operand",)
    def __init__(self, operand): self.operand = operand

class LogOp:
    __slots__ = ("op", "left", "right")
    def __init__(self, op, left, right):
        self.op = op; self.left = left; self.right = right


# ---------------------------------------------------------------------------
# Lark Transformer — builds AST from parse tree
# ---------------------------------------------------------------------------

class IMPTransformer(Transformer):
    def start(self, items):
        return items[0]

    def stmt_list(self, items):
        return list(items)

    def decl(self, items):
        return Decl(str(items[0]))

    def assign(self, items):
        return Assign(str(items[0]), items[1])

    def if_else(self, items):
        return IfElse(items[0], items[1], items[2])

    def while_loop(self, items):
        return While(items[0], items[1])

    def halt_stmt(self, items):
        return HaltStmt()

    def continue_stmt(self, items):
        return ContinueStmt()

    def break_stmt(self, items):
        return BreakStmt()

    def var(self, items):
        return Var(str(items[0]))

    def num(self, items):
        return Num(int(str(items[0])))

    def add(self, items):
        return BinOp('+', items[0], items[1])

    def sub(self, items):
        return BinOp('-', items[0], items[1])

    def mul(self, items):
        return BinOp('*', items[0], items[1])

    def div(self, items):
        return BinOp('/', items[0], items[1])

    def mod(self, items):
        return BinOp('%', items[0], items[1])

    def unary_plus(self, items):
        return UnaryOp('+', items[0])

    def unary_minus(self, items):
        return UnaryOp('-', items[0])

    def bool_true(self, items):
        return BoolLit(True)

    def bool_false(self, items):
        return BoolLit(False)

    def lt(self, items):
        return RelOp('<', items[0], items[1])

    def le(self, items):
        return RelOp('<=', items[0], items[1])

    def gt(self, items):
        return RelOp('>', items[0], items[1])

    def ge(self, items):
        return RelOp('>=', items[0], items[1])

    def eq(self, items):
        return RelOp('==', items[0], items[1])

    def ne(self, items):
        return RelOp('!=', items[0], items[1])

    def negation(self, items):
        return NotOp(items[0])

    def logical_and(self, items):
        return LogOp('&&', items[0], items[1])

    def logical_or(self, items):
        return LogOp('||', items[0], items[1])


# ---------------------------------------------------------------------------
# Interpreter — nonstandard SOS semantics
# ---------------------------------------------------------------------------

class HaltSignal(Exception): pass
class BreakSignal(Exception): pass
class ContinueSignal(Exception): pass


def _trunc_div(a, b):
    """Integer division truncating toward zero."""
    if b == 0:
        raise RuntimeError("Division by zero")
    return int(a / b)


def _trunc_mod(a, b):
    """Integer modulo consistent with truncation toward zero."""
    if b == 0:
        raise RuntimeError("Modulo by zero")
    return a - int(a / b) * b


def eval_aexp(expr, store):
    """Evaluate arithmetic expression under nonstandard SOS rules."""
    if isinstance(expr, Num):
        return expr.value
    if isinstance(expr, Var):
        if expr.name not in store:
            raise RuntimeError(f"Undefined variable: {expr.name}")
        return store[expr.name]
    if isinstance(expr, UnaryOp):
        val = eval_aexp(expr.operand, store)
        if expr.op == '+':
            return -val            # Rule 25: unary + negates
        else:
            return val             # Rule 27: unary - is identity
    if isinstance(expr, BinOp):
        v1 = eval_aexp(expr.left, store)
        v2 = eval_aexp(expr.right, store)
        op = expr.op
        if op == '+': return v1 - v2              # Rule 12: + computes subtraction
        elif op == '-': return v1 + v2            # Rule 9:  - computes addition
        elif op == '*': return _trunc_div(v1, v2) # Rule 18: * computes division
        elif op == '/': return v1 * v2            # Rule 15: / computes multiplication
        elif op == '%': return _trunc_mod(v1, v2) # Rule 22: % unchanged
    raise RuntimeError(f"Unknown aexp: {type(expr).__name__}")


def eval_bexp(expr, store):
    """Evaluate boolean expression under nonstandard SOS rules."""
    if isinstance(expr, BoolLit):
        return expr.value
    if isinstance(expr, RelOp):
        v1 = eval_aexp(expr.left, store)
        v2 = eval_aexp(expr.right, store)
        op = expr.op
        if op == '>':  return v1 < v2   # Rule 30: > checks <
        elif op == '>=': return v1 <= v2  # Rule 34: >= checks <=
        elif op == '<':  return v1 > v2   # Rule 38: < checks >
        elif op == '<=': return v1 >= v2  # Rule 42: <= checks >=
        elif op == '==': return v1 != v2  # Rule 50: == checks !=
        elif op == '!=': return v1 == v2  # Rule 46: != checks ==
    if isinstance(expr, NotOp):
        return not eval_bexp(expr.operand, store)
    if isinstance(expr, LogOp):
        v1 = eval_bexp(expr.left, store)
        v2 = eval_bexp(expr.right, store)
        if expr.op == '||': return v1 and v2  # Rule 54: || computes AND
        elif expr.op == '&&': return v1 or v2  # Rule 58: && computes OR
    raise RuntimeError(f"Unknown bexp: {type(expr).__name__}")


def exec_stmts(stmts, store):
    """Execute a list of statements."""
    for stmt in stmts:
        exec_stmt(stmt, store)


def exec_stmt(stmt, store):
    """Execute a single statement."""
    if isinstance(stmt, Decl):
        store[stmt.name] = 0
    elif isinstance(stmt, Assign):
        if stmt.name not in store:
            raise RuntimeError(f"Assignment to undeclared: {stmt.name}")
        store[stmt.name] = eval_aexp(stmt.expr, store)
    elif isinstance(stmt, IfElse):
        if eval_bexp(stmt.cond, store):
            exec_stmts(stmt.then_body, store)
        else:
            exec_stmts(stmt.else_body, store)
    elif isinstance(stmt, While):
        while eval_bexp(stmt.cond, store):
            try:
                exec_stmts(stmt.body, store)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
    elif isinstance(stmt, HaltStmt):
        raise HaltSignal()
    elif isinstance(stmt, BreakStmt):
        raise BreakSignal()
    elif isinstance(stmt, ContinueStmt):
        raise ContinueSignal()
    else:
        raise RuntimeError(f"Unknown statement: {type(stmt).__name__}")


def run_program(stmts):
    """Execute program and return final store."""
    store = {}
    try:
        exec_stmts(stmts, store)
    except HaltSignal:
        pass
    return store


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    grammar_path = "/app/imp.lark"
    programs_dir = "/app/programs"
    output_dir = "/app/output"

    with open(grammar_path) as f:
        grammar_text = f.read()

    parser = Lark(grammar_text, start='start', parser='earley')
    transformer = IMPTransformer()

    os.makedirs(output_dir, exist_ok=True)

    for fname in sorted(os.listdir(programs_dir)):
        if not fname.endswith(".imp"):
            continue
        path = os.path.join(programs_dir, fname)
        with open(path) as f:
            source = f.read()

        tree = parser.parse(source)
        stmts = transformer.transform(tree)
        store = run_program(stmts)

        out_name = fname[:-4] + ".json"
        out_path = os.path.join(output_dir, out_name)
        with open(out_path, "w") as f:
            json.dump(dict(sorted(store.items())), f)
        print(f"  {fname} -> {dict(sorted(store.items()))}")


if __name__ == "__main__":
    main()
