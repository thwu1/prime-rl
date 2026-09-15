#!/usr/bin/env python3
"""
IMP interpreter implementing nonstandard SOS semantics via small-step abstract machine.
Uses Lark for parsing and tracks innermost rule at each machine transition.
"""

import json
import os
import copy
from lark import Lark, Transformer, Token


# ---- AST Nodes ----

class NumVal:
    def __init__(self, value):
        self.value = value
    def __repr__(self):
        return f"NumVal({self.value})"

class BoolVal:
    def __init__(self, value):
        self.value = value
    def __repr__(self):
        return f"BoolVal({self.value})"

class VarRef:
    def __init__(self, name):
        self.name = name

class BinArith:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class UnaryArith:
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

class RelComp:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class NotExpr:
    def __init__(self, operand):
        self.operand = operand

class LogicExpr:
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

class IntDecl:
    def __init__(self, name):
        self.name = name

class Assign:
    def __init__(self, name, expr):
        self.name = name
        self.expr = expr

class IfElse:
    def __init__(self, cond, then_branch, else_branch):
        self.cond = cond
        self.then_branch = then_branch
        self.else_branch = else_branch

class WhileLoop:
    def __init__(self, cond, body):
        self.cond = cond
        self.body = body

class LoopStmt:
    def __init__(self, cond, body):
        self.cond = cond
        self.body = body

class LEStmt:
    pass

class BreakStmt:
    pass

class ContinueStmt:
    pass

class HaltStmt:
    pass

class ErrorState:
    pass


# ---- Lark Transformer ----

class IMPTransformer(Transformer):
    def start(self, items):
        return items[0]

    def stmt_list(self, items):
        return [i for i in items if not isinstance(i, Token)]

    def int_decl(self, items):
        return IntDecl(str(items[0]))

    def assign(self, items):
        return Assign(str(items[0]), items[1])

    def if_else(self, items):
        return IfElse(items[0], items[1], items[2])

    def while_loop(self, items):
        return WhileLoop(items[0], items[1])

    def halt_stmt(self, items):
        return HaltStmt()

    def continue_stmt(self, items):
        return ContinueStmt()

    def break_stmt(self, items):
        return BreakStmt()

    def var_ref(self, items):
        return VarRef(str(items[0]))

    def num_lit(self, items):
        return NumVal(int(str(items[0])))

    def bin_arith(self, items):
        return BinArith(str(items[1]), items[0], items[2])

    def unary_neg(self, items):
        return UnaryArith('-', items[0])

    def unary_pos(self, items):
        return UnaryArith('+', items[0])

    def bool_lit(self, items):
        return BoolVal(str(items[0]) == 'true')

    def rel_comp(self, items):
        return RelComp(str(items[1]), items[0], items[2])

    def not_expr(self, items):
        return NotExpr(items[0])

    def logic_expr(self, items):
        return LogicExpr(str(items[1]), items[0], items[2])


# ---- Helper functions ----

def is_aval(node):
    return isinstance(node, NumVal)

def is_bval(node):
    return isinstance(node, BoolVal)

def trunc_div(a, b):
    if b == 0:
        return None
    result = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        result = -result
    return result

def trunc_mod(a, b):
    if b == 0:
        return None
    return a - trunc_div(a, b) * b


# ---- Small-step expression evaluation ----

def step_aexp(expr, store):
    """One-step reduction of arithmetic expression.
    Returns (new_expr, innermost_rule) or (ErrorState(), rule) on error.
    Returns None if expr is already a value.
    """
    if isinstance(expr, NumVal):
        return None

    if isinstance(expr, VarRef):
        if expr.name in store:
            return (NumVal(store[expr.name]), 1)
        else:
            return (ErrorState(), 2)

    if isinstance(expr, BinArith):
        if not is_aval(expr.left):
            result = step_aexp(expr.left, store)
            if result is None:
                return None
            new_left, rule = result
            if isinstance(new_left, ErrorState):
                return (ErrorState(), rule)
            return (BinArith(expr.op, new_left, expr.right), rule)

        if not is_aval(expr.right):
            result = step_aexp(expr.right, store)
            if result is None:
                return None
            new_right, rule = result
            if isinstance(new_right, ErrorState):
                return (ErrorState(), rule)
            return (BinArith(expr.op, expr.left, new_right), rule)

        v1, v2 = expr.left.value, expr.right.value
        if expr.op == '+':
            return (NumVal(v1 - v2), 12)
        elif expr.op == '-':
            return (NumVal(v1 + v2), 9)
        elif expr.op == '*':
            if v2 == 0:
                return (ErrorState(), 19)
            return (NumVal(trunc_div(v1, v2)), 18)
        elif expr.op == '/':
            return (NumVal(v1 * v2), 15)
        elif expr.op == '%':
            if v2 == 0:
                return (ErrorState(), 23)
            return (NumVal(trunc_mod(v1, v2)), 22)

    if isinstance(expr, UnaryArith):
        if not is_aval(expr.operand):
            result = step_aexp(expr.operand, store)
            if result is None:
                return None
            new_op, rule = result
            if isinstance(new_op, ErrorState):
                return (ErrorState(), rule)
            return (UnaryArith(expr.op, new_op), rule)

        v = expr.operand.value
        if expr.op == '+':
            return (NumVal(-v), 25)
        elif expr.op == '-':
            return (NumVal(v), 27)

    return None


def step_bexp(expr, store):
    """One-step reduction of boolean expression.
    Returns (new_expr, innermost_rule) or (ErrorState(), rule) on error.
    Returns None if expr is already a value.
    """
    if isinstance(expr, BoolVal):
        return None

    if isinstance(expr, RelComp):
        if not is_aval(expr.left):
            result = step_aexp(expr.left, store)
            if result is None:
                return None
            new_left, rule = result
            if isinstance(new_left, ErrorState):
                return (ErrorState(), rule)
            return (RelComp(expr.op, new_left, expr.right), rule)

        if not is_aval(expr.right):
            result = step_aexp(expr.right, store)
            if result is None:
                return None
            new_right, rule = result
            if isinstance(new_right, ErrorState):
                return (ErrorState(), rule)
            return (RelComp(expr.op, expr.left, new_right), rule)

        v1, v2 = expr.left.value, expr.right.value
        if expr.op == '<':
            return (BoolVal(v1 > v2), 38 if v1 > v2 else 39)
        elif expr.op == '<=':
            return (BoolVal(v1 >= v2), 42 if v1 >= v2 else 43)
        elif expr.op == '>':
            return (BoolVal(v1 < v2), 30 if v1 < v2 else 31)
        elif expr.op == '>=':
            return (BoolVal(v1 <= v2), 34 if v1 <= v2 else 35)
        elif expr.op == '==':
            return (BoolVal(v1 != v2), 50 if v1 != v2 else 51)
        elif expr.op == '!=':
            return (BoolVal(v1 == v2), 46 if v1 == v2 else 47)

    if isinstance(expr, NotExpr):
        if not is_bval(expr.operand):
            result = step_bexp(expr.operand, store)
            if result is None:
                return None
            new_op, rule = result
            if isinstance(new_op, ErrorState):
                return (ErrorState(), rule)
            return (NotExpr(new_op), rule)

        if expr.operand.value is False:
            return (BoolVal(True), 61)
        else:
            return (BoolVal(False), 62)

    if isinstance(expr, LogicExpr):
        if not is_bval(expr.left):
            result = step_bexp(expr.left, store)
            if result is None:
                return None
            new_left, rule = result
            if isinstance(new_left, ErrorState):
                return (ErrorState(), rule)
            return (LogicExpr(expr.op, new_left, expr.right), rule)

        if not is_bval(expr.right):
            result = step_bexp(expr.right, store)
            if result is None:
                return None
            new_right, rule = result
            if isinstance(new_right, ErrorState):
                return (ErrorState(), rule)
            return (LogicExpr(expr.op, expr.left, new_right), rule)

        q1, q2 = expr.left.value, expr.right.value
        if expr.op == '&&':
            if q1 or q2:
                return (BoolVal(True), 58)
            else:
                return (BoolVal(False), 59)
        elif expr.op == '||':
            if q1 and q2:
                return (BoolVal(True), 54)
            else:
                return (BoolVal(False), 55)

    return None


# ---- Abstract machine ----

def step_machine(stmts, store, stack):
    """Take one abstract machine step.
    Returns (new_stmts, new_store, new_stack, innermost_rule, terminal_kind)
    terminal_kind is None (not terminal), 'normal', 'halt', or 'error'.
    """
    if not stmts:
        return stmts, store, stack, None, 'normal'

    head = stmts[0]
    rest = stmts[1:]

    if isinstance(head, IntDecl):
        new_store = dict(store)
        new_store[head.name] = 0
        return rest, new_store, stack, 3, None

    if isinstance(head, Assign):
        if is_aval(head.expr):
            if head.name not in store:
                return [], store, stack, 6, 'error'
            new_store = dict(store)
            new_store[head.name] = head.expr.value
            return rest, new_store, stack, 5, None
        else:
            result = step_aexp(head.expr, store)
            if result is None:
                return [], store, stack, 6, 'error'
            new_expr, rule = result
            if isinstance(new_expr, ErrorState):
                return [], store, stack, rule, 'error'
            return [Assign(head.name, new_expr)] + rest, store, stack, rule, None

    if isinstance(head, IfElse):
        if is_bval(head.cond):
            if head.cond.value:
                return head.then_branch + rest, store, stack, 65, None
            else:
                return head.else_branch + rest, store, stack, 66, None
        else:
            result = step_bexp(head.cond, store)
            if result is None:
                return [], store, stack, None, 'error'
            new_cond, rule = result
            if isinstance(new_cond, ErrorState):
                return [], store, stack, rule, 'error'
            return [IfElse(new_cond, head.then_branch, head.else_branch)] + rest, store, stack, rule, None

    if isinstance(head, WhileLoop):
        new_stack = [copy.deepcopy(head)] + stack
        return [LoopStmt(copy.deepcopy(head.cond), head.body)] + rest, store, new_stack, 67, None

    if isinstance(head, LoopStmt):
        if is_bval(head.cond):
            if head.cond.value:
                return head.body + [LEStmt()] + rest, store, stack, 70, None
            else:
                return rest, store, stack[1:], 69, None
        else:
            result = step_bexp(head.cond, store)
            if result is None:
                return [], store, stack, None, 'error'
            new_cond, rule = result
            if isinstance(new_cond, ErrorState):
                return [], store, stack, rule, 'error'
            return [LoopStmt(new_cond, head.body)] + rest, store, stack, rule, None

    if isinstance(head, LEStmt):
        if not stack:
            return [], store, stack, None, 'error'
        s = copy.deepcopy(stack[0])
        return [s] + rest, store, stack[1:], 77, None

    if isinstance(head, BreakStmt):
        if not stack:
            return [], store, stack, 73, 'error'
        if not rest:
            return [], store, stack, 73, 'error'
        next_s = rest[0]
        if isinstance(next_s, LEStmt):
            return rest[1:], store, stack[1:], 72, None
        else:
            return [BreakStmt()] + rest[1:], store, stack, 71, None

    if isinstance(head, ContinueStmt):
        if not stack:
            return [], store, stack, 76, 'error'
        if not rest:
            return [], store, stack, 76, 'error'
        next_s = rest[0]
        if isinstance(next_s, LEStmt):
            s1 = copy.deepcopy(stack[0])
            return [s1] + rest[1:], store, stack[1:], 75, None
        else:
            return [ContinueStmt()] + rest[1:], store, stack, 74, None

    if isinstance(head, HaltStmt):
        return [], store, stack, 78, 'halt'

    return [], store, stack, None, 'error'


def run_program(stmts):
    """Run a program to completion, tracking rule applications.
    Returns (final_store_or_error, step_count, rule_histogram).
    """
    store = {}
    stack = []
    histogram = {}
    step_count = 0
    max_steps = 100000

    while stmts and step_count < max_steps:
        new_stmts, new_store, new_stack, rule, terminal = step_machine(stmts, store, stack)

        if rule is not None:
            step_count += 1
            r_str = str(rule)
            histogram[r_str] = histogram.get(r_str, 0) + 1

        if terminal == 'error':
            return "ERROR", step_count, histogram
        if terminal == 'halt':
            return dict(store), step_count, histogram
        if terminal == 'normal' and not new_stmts:
            return dict(new_store), step_count, histogram

        stmts = new_stmts
        store = new_store
        stack = new_stack

    return dict(store), step_count, histogram


# ---- Main ----

def main():
    grammar_path = "/app/imp.lark"
    with open(grammar_path) as f:
        grammar = f.read()

    parser = Lark(grammar, parser='earley', ambiguity='resolve')
    transformer = IMPTransformer()

    operator_mapping = {
        "binary_+": "subtraction",
        "binary_-": "addition",
        "binary_*": "division",
        "binary_/": "multiplication",
        "binary_%": "modulo",
        "unary_+": "negation",
        "unary_-": "identity",
        "<": "greater_than",
        "<=": "greater_equal",
        ">": "less_than",
        ">=": "less_equal",
        "==": "not_equal",
        "!=": "equal",
        "&&": "disjunction",
        "||": "conjunction",
        "!": "negation",
    }

    programs = {}
    prog_dir = "/app/programs"
    for fname in sorted(os.listdir(prog_dir)):
        if not fname.endswith('.imp'):
            continue
        name = fname[:-4]
        with open(os.path.join(prog_dir, fname)) as f:
            source = f.read()

        tree = parser.parse(source)
        stmts = transformer.transform(tree)

        final_state, step_count, histogram = run_program(stmts)
        programs[name] = {
            "final_state": final_state,
            "step_count": step_count,
            "rule_histogram": histogram,
        }

    results = {
        "operator_mapping": operator_mapping,
        "programs": programs,
    }

    out_path = "/app/results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, sort_keys=True)
    print(f"Wrote {out_path} with {len(programs)} programs.")


if __name__ == "__main__":
    main()
