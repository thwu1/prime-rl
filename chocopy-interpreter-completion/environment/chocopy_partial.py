#!/usr/bin/env python3
"""
Partial ChocoPy interpreter.

Handles: integer/boolean/string literals, arithmetic, comparisons, logical
operators (short-circuit), variables, if/elif/else, while loops, basic
function calls, print/len built-ins, return statements, conditional
expressions.

TODO features (marked with "# TODO" throughout):
  - Class definitions, object construction, attribute access/assignment
  - Inheritance and dynamic dispatch (method lookup via superclass chain)
  - Nested functions with closures, nonlocal/global declarations
  - List display, list indexing, list element assignment, list concatenation
  - String indexing
  - for loops over lists and strings
  - The 'is' identity operator
  - Runtime error handling for None operations and index-out-of-bounds
"""


import ast
import sys

# ------------------------------------------------------------------ #
# Values                                                              #
# ------------------------------------------------------------------ #

class NoneVal:
    """The ChocoPy None value."""
    pass

NONE = NoneVal()

class IntVal:
    def __init__(self, v):
        self.v = v

class BoolVal:
    def __init__(self, v):
        self.v = v

class StrVal:
    def __init__(self, v):
        self.v = v

class ListVal:
    """TODO: Used for ChocoPy list values."""
    def __init__(self, elems):
        self.elems = list(elems)

class ObjVal:
    """TODO: Used for instances of user-defined classes."""
    def __init__(self, cls_name, attrs):
        self.cls_name = cls_name
        self.attrs = dict(attrs)

class FuncVal:
    def __init__(self, name, params, body, env):
        self.name = name
        self.params = params
        self.body = body
        self.env = env

# ------------------------------------------------------------------ #
# Errors                                                              #
# ------------------------------------------------------------------ #

class ChocoPyError(Exception):
    def __init__(self, msg, code):
        self.msg = msg
        self.code = code

class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value

# ------------------------------------------------------------------ #
# Environment                                                        #
# ------------------------------------------------------------------ #

class Env:
    def __init__(self, parent=None):
        self.bindings = {}
        self.parent = parent

    def get(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.get(name)
        raise ChocoPyError(f"Undefined variable: {name}", 1)

    def set(self, name, value):
        """Create or overwrite a binding in the current scope."""
        self.bindings[name] = value

    def assign(self, name, value):
        """Assign to the nearest scope that already has this binding."""
        if name in self.bindings:
            self.bindings[name] = value
            return True
        if self.parent:
            return self.parent.assign(name, value)
        return False

# ------------------------------------------------------------------ #
# Interpreter                                                        #
# ------------------------------------------------------------------ #

class Interpreter:
    def __init__(self):
        self.global_env = Env()
        self.classes = {}  # TODO: class name -> class definition

    def run(self, source):
        tree = ast.parse(source)
        self._init_builtins()
        self._exec_program(tree)

    # ---- builtins ------------------------------------------------ #

    def _init_builtins(self):
        self.global_env.set("print", "builtin_print")
        self.global_env.set("len", "builtin_len")
        self.global_env.set("input", "builtin_input")

    def _builtin_print(self, args):
        if len(args) != 1:
            raise ChocoPyError("Invalid argument", 1)
        v = args[0]
        if isinstance(v, IntVal):
            print(v.v)
        elif isinstance(v, BoolVal):
            print("True" if v.v else "False")
        elif isinstance(v, StrVal):
            print(v.v)
        else:
            raise ChocoPyError("Invalid argument", 1)
        return NONE

    def _builtin_len(self, args):
        if len(args) != 1:
            raise ChocoPyError("Invalid argument", 1)
        v = args[0]
        if isinstance(v, StrVal):
            return IntVal(len(v.v))
        elif isinstance(v, ListVal):
            return IntVal(len(v.elems))
        else:
            raise ChocoPyError("Invalid argument", 1)

    def _builtin_input(self):
        try:
            line = input()
            return StrVal(line)
        except EOFError:
            return StrVal("")

    # ---- program ------------------------------------------------- #

    def _exec_program(self, tree):
        # First pass: collect all definitions
        stmts = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self._define_function(node, self.global_env)
            elif isinstance(node, ast.ClassDef):
                # TODO: implement class definitions
                pass
            elif isinstance(node, ast.AnnAssign):
                self._exec_var_def(node, self.global_env)
            else:
                stmts.append(node)
        # Second pass: execute statements
        for stmt in stmts:
            self._exec_stmt(stmt, self.global_env)

    # ---- definitions --------------------------------------------- #

    def _define_function(self, node, env):
        params = [arg.arg for arg in node.args.args]
        func = FuncVal(node.name, params, node.body, env)
        env.set(node.name, func)

    def _exec_var_def(self, node, env):
        name = node.target.id
        value = self._eval_literal(node.value)
        env.set(name, value)

    def _eval_literal(self, node):
        if isinstance(node, ast.Constant):
            if node.value is None:
                return NONE
            if isinstance(node.value, bool):
                return BoolVal(node.value)
            if isinstance(node.value, int):
                return IntVal(node.value)
            if isinstance(node.value, str):
                return StrVal(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self._eval_literal(node.operand)
            if isinstance(inner, IntVal):
                return IntVal(-inner.v)
        if isinstance(node, ast.List) and len(node.elts) == 0:
            return ListVal([])
        return NONE

    # ---- statements ---------------------------------------------- #

    def _exec_stmt(self, node, env):
        if isinstance(node, ast.Expr):
            self._eval_expr(node.value, env)
        elif isinstance(node, ast.Assign):
            self._exec_assign(node, env)
        elif isinstance(node, ast.AnnAssign):
            self._exec_var_def(node, env)
        elif isinstance(node, ast.If):
            self._exec_if(node, env)
        elif isinstance(node, ast.While):
            self._exec_while(node, env)
        elif isinstance(node, ast.For):
            # TODO: implement for loops
            raise ChocoPyError("for loops not yet implemented", 1)
        elif isinstance(node, ast.Return):
            val = NONE
            if node.value:
                val = self._eval_expr(node.value, env)
            raise ReturnSignal(val)
        elif isinstance(node, ast.Pass):
            pass
        elif isinstance(node, ast.FunctionDef):
            self._define_function(node, env)
        elif isinstance(node, ast.Global):
            # TODO: implement global variable declarations
            pass
        elif isinstance(node, ast.Nonlocal):
            # TODO: implement nonlocal variable declarations
            pass

    def _exec_assign(self, node, env):
        value = self._eval_expr(node.value, env)
        for target in node.targets:
            self._assign_target(target, value, env)

    def _assign_target(self, target, value, env):
        if isinstance(target, ast.Name):
            if not env.assign(target.id, value):
                env.set(target.id, value)
        elif isinstance(target, ast.Attribute):
            # TODO: implement attribute assignment (obj.attr = val)
            raise ChocoPyError("attribute assignment not yet implemented", 1)
        elif isinstance(target, ast.Subscript):
            # TODO: implement index assignment (lst[i] = val)
            raise ChocoPyError("index assignment not yet implemented", 1)

    def _exec_if(self, node, env):
        cond = self._eval_expr(node.test, env)
        if self._is_true(cond):
            self._exec_block(node.body, env)
        elif node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                self._exec_if(node.orelse[0], env)
            else:
                self._exec_block(node.orelse, env)

    def _exec_while(self, node, env):
        while True:
            cond = self._eval_expr(node.test, env)
            if not self._is_true(cond):
                break
            self._exec_block(node.body, env)

    def _exec_block(self, stmts, env):
        for stmt in stmts:
            self._exec_stmt(stmt, env)

    # ---- helpers ------------------------------------------------- #

    def _is_true(self, value):
        return isinstance(value, BoolVal) and value.v

    # ---- expressions --------------------------------------------- #

    def _eval_expr(self, node, env):
        if isinstance(node, ast.Constant):
            return self._eval_constant(node)
        elif isinstance(node, ast.Name):
            return env.get(node.id)
        elif isinstance(node, ast.BinOp):
            return self._eval_binop(node, env)
        elif isinstance(node, ast.UnaryOp):
            return self._eval_unaryop(node, env)
        elif isinstance(node, ast.BoolOp):
            return self._eval_boolop(node, env)
        elif isinstance(node, ast.Compare):
            return self._eval_compare(node, env)
        elif isinstance(node, ast.Call):
            return self._eval_call(node, env)
        elif isinstance(node, ast.IfExp):
            return self._eval_ifexp(node, env)
        elif isinstance(node, ast.Attribute):
            # TODO: implement attribute access (obj.attr)
            raise ChocoPyError("attribute access not yet implemented", 1)
        elif isinstance(node, ast.Subscript):
            # TODO: implement index access (obj[i])
            raise ChocoPyError("index access not yet implemented", 1)
        elif isinstance(node, ast.List):
            # TODO: implement list display ([e1, e2, ...])
            raise ChocoPyError("list display not yet implemented", 1)
        else:
            raise ChocoPyError(f"Unsupported expression: {type(node).__name__}", 1)

    def _eval_constant(self, node):
        v = node.value
        if v is None:
            return NONE
        if isinstance(v, bool):
            return BoolVal(v)
        if isinstance(v, int):
            return IntVal(v)
        if isinstance(v, str):
            return StrVal(v)
        raise ChocoPyError("Unknown constant", 1)

    def _eval_binop(self, node, env):
        left = self._eval_expr(node.left, env)
        right = self._eval_expr(node.right, env)
        op = node.op

        # Integer arithmetic
        if isinstance(left, IntVal) and isinstance(right, IntVal):
            if isinstance(op, ast.Add):
                return IntVal(left.v + right.v)
            if isinstance(op, ast.Sub):
                return IntVal(left.v - right.v)
            if isinstance(op, ast.Mult):
                return IntVal(left.v * right.v)
            if isinstance(op, ast.FloorDiv):
                if right.v == 0:
                    raise ChocoPyError("Division by zero", 2)
                return IntVal(left.v // right.v)
            if isinstance(op, ast.Mod):
                if right.v == 0:
                    raise ChocoPyError("Division by zero", 2)
                return IntVal(left.v % right.v)

        # String concatenation
        if isinstance(left, StrVal) and isinstance(right, StrVal):
            if isinstance(op, ast.Add):
                return StrVal(left.v + right.v)

        # TODO: list concatenation (ListVal + ListVal)

        raise ChocoPyError("Unsupported binary operation", 1)

    def _eval_unaryop(self, node, env):
        operand = self._eval_expr(node.operand, env)
        if isinstance(node.op, ast.USub) and isinstance(operand, IntVal):
            return IntVal(-operand.v)
        if isinstance(node.op, ast.Not) and isinstance(operand, BoolVal):
            return BoolVal(not operand.v)
        raise ChocoPyError("Unsupported unary operation", 1)

    def _eval_boolop(self, node, env):
        # Short-circuit evaluation
        if isinstance(node.op, ast.And):
            left = self._eval_expr(node.values[0], env)
            if not self._is_true(left):
                return BoolVal(False)
            return self._eval_expr(node.values[1], env)
        elif isinstance(node.op, ast.Or):
            left = self._eval_expr(node.values[0], env)
            if self._is_true(left):
                return BoolVal(True)
            return self._eval_expr(node.values[1], env)
        raise ChocoPyError("Unsupported boolean operation", 1)

    def _eval_compare(self, node, env):
        left = self._eval_expr(node.left, env)
        right = self._eval_expr(node.comparators[0], env)
        op = node.ops[0]

        # TODO: implement the 'is' operator (ast.Is)

        # Integer comparisons
        if isinstance(left, IntVal) and isinstance(right, IntVal):
            if isinstance(op, ast.Lt):    return BoolVal(left.v < right.v)
            if isinstance(op, ast.LtE):   return BoolVal(left.v <= right.v)
            if isinstance(op, ast.Gt):    return BoolVal(left.v > right.v)
            if isinstance(op, ast.GtE):   return BoolVal(left.v >= right.v)
            if isinstance(op, ast.Eq):    return BoolVal(left.v == right.v)
            if isinstance(op, ast.NotEq): return BoolVal(left.v != right.v)

        # String comparisons
        if isinstance(left, StrVal) and isinstance(right, StrVal):
            if isinstance(op, ast.Eq):    return BoolVal(left.v == right.v)
            if isinstance(op, ast.NotEq): return BoolVal(left.v != right.v)

        # Boolean comparisons
        if isinstance(left, BoolVal) and isinstance(right, BoolVal):
            if isinstance(op, ast.Eq):    return BoolVal(left.v == right.v)
            if isinstance(op, ast.NotEq): return BoolVal(left.v != right.v)

        raise ChocoPyError("Unsupported comparison", 1)

    def _eval_call(self, node, env):
        # Method call: obj.method(args)
        if isinstance(node.func, ast.Attribute):
            # TODO: implement method calls with dynamic dispatch
            raise ChocoPyError("method calls not yet implemented", 1)

        # Function or class-constructor call: name(args)
        if isinstance(node.func, ast.Name):
            name = node.func.id
            func = env.get(name)
            args = [self._eval_expr(a, env) for a in node.args]

            if func == "builtin_print":
                return self._builtin_print(args)
            elif func == "builtin_len":
                return self._builtin_len(args)
            elif func == "builtin_input":
                return self._builtin_input()
            elif isinstance(func, FuncVal):
                return self._call_function(func, args)
            # TODO: handle class construction (func is a ClassDef)

        raise ChocoPyError("Not callable", 1)

    def _call_function(self, func, args):
        new_env = Env(parent=func.env)
        # Bind parameters
        for param, arg in zip(func.params, args):
            new_env.set(param, arg)
        # Process definitions first, then statements
        stmts = []
        for node in func.body:
            if isinstance(node, ast.FunctionDef):
                self._define_function(node, new_env)
            elif isinstance(node, ast.AnnAssign):
                self._exec_var_def(node, new_env)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                pass  # TODO: handle global/nonlocal properly
            else:
                stmts.append(node)
        try:
            for stmt in stmts:
                self._exec_stmt(stmt, new_env)
        except ReturnSignal as r:
            return r.value
        return NONE

    def _eval_ifexp(self, node, env):
        cond = self._eval_expr(node.test, env)
        if self._is_true(cond):
            return self._eval_expr(node.body, env)
        else:
            return self._eval_expr(node.orelse, env)


# ------------------------------------------------------------------ #
# Main                                                                #
# ------------------------------------------------------------------ #

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 chocopy.py <file>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    interp = Interpreter()
    try:
        interp.run(source)
    except ChocoPyError as e:
        print(e.msg, file=sys.stderr)
        sys.exit(e.code)

if __name__ == "__main__":
    main()
