#!/usr/bin/env python3
"""
Complete ChocoPy interpreter.

Implements all ChocoPy language features: classes with single inheritance
and dynamic dispatch, nested functions with closures, nonlocal/global
variable declarations, lists, string indexing, for loops, the 'is'
operator, and runtime error handling.
"""


import ast
import sys

# ================================================================== #
# Values                                                              #
# ================================================================== #

class NoneVal:
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
    def __init__(self, elems):
        self.elems = list(elems)

class ObjVal:
    def __init__(self, cls_name, attrs):
        self.cls_name = cls_name
        self.attrs = dict(attrs)

class FuncVal:
    def __init__(self, name, params, body, env, globals_set=None, nonlocals_set=None):
        self.name = name
        self.params = params
        self.body = body
        self.env = env
        self.globals_set = globals_set or set()
        self.nonlocals_set = nonlocals_set or set()

# ================================================================== #
# Class definition registry                                          #
# ================================================================== #

class ClassInfo:
    def __init__(self, name, superclass, own_attrs, own_methods):
        self.name = name
        self.superclass = superclass          # ClassInfo | None
        self.own_attrs = own_attrs            # dict: name -> ast literal node
        self.own_methods = own_methods        # dict: name -> ast.FunctionDef

    def get_method(self, name):
        if name in self.own_methods:
            return self.own_methods[name]
        if self.superclass:
            return self.superclass.get_method(name)
        return None

    def get_all_attrs(self):
        if self.superclass:
            attrs = self.superclass.get_all_attrs()
        else:
            attrs = {}
        attrs.update(self.own_attrs)
        return attrs

# ================================================================== #
# Environment                                                        #
# ================================================================== #

class Env:
    def __init__(self, parent=None, global_env=None,
                 globals_decl=None, nonlocals_decl=None):
        self.bindings = {}
        self.parent = parent
        self.global_env = global_env
        self.globals_decl = globals_decl or set()
        self.nonlocals_decl = nonlocals_decl or set()

    def get(self, name):
        if name in self.globals_decl and self.global_env:
            return self.global_env.get(name)
        if name in self.nonlocals_decl and self.parent:
            return self.parent._get_nonlocal(name)
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.get(name)
        raise ChocoPyError(f"Undefined variable: {name}", 1)

    def _get_nonlocal(self, name):
        if name in self.globals_decl and self.global_env:
            return self.global_env.get(name)
        if name in self.nonlocals_decl and self.parent:
            return self.parent._get_nonlocal(name)
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent._get_nonlocal(name)
        raise ChocoPyError(f"Undefined nonlocal variable: {name}", 1)

    def set(self, name, value):
        self.bindings[name] = value

    def assign(self, name, value):
        if name in self.globals_decl and self.global_env:
            self.global_env.bindings[name] = value
            return
        if name in self.nonlocals_decl and self.parent:
            self.parent._assign_nonlocal(name, value)
            return
        self.bindings[name] = value

    def _assign_nonlocal(self, name, value):
        if name in self.globals_decl and self.global_env:
            self.global_env.bindings[name] = value
            return
        if name in self.nonlocals_decl and self.parent:
            self.parent._assign_nonlocal(name, value)
            return
        if name in self.bindings:
            self.bindings[name] = value
            return
        if self.parent:
            self.parent._assign_nonlocal(name, value)
            return
        raise ChocoPyError(f"No binding for nonlocal: {name}", 1)

    def assign_existing(self, name, value):
        """Assign in the nearest scope that already has this binding."""
        if name in self.bindings:
            self.bindings[name] = value
            return True
        if self.parent:
            return self.parent.assign_existing(name, value)
        return False

# ================================================================== #
# Errors                                                              #
# ================================================================== #

class ChocoPyError(Exception):
    def __init__(self, msg, code):
        self.msg = msg
        self.code = code

class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value

# ================================================================== #
# Interpreter                                                        #
# ================================================================== #

class Interpreter:
    def __init__(self):
        self.global_env = Env()
        self.classes = {}

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
        if isinstance(v, ListVal):
            return IntVal(len(v.elems))
        raise ChocoPyError("Invalid argument", 1)

    def _builtin_input(self):
        try:
            line = input()
            return StrVal(line)
        except EOFError:
            return StrVal("")

    # ---- program ------------------------------------------------- #

    def _exec_program(self, tree):
        stmts = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self._define_function(node, self.global_env)
            elif isinstance(node, ast.ClassDef):
                self._define_class(node)
            elif isinstance(node, ast.AnnAssign):
                self._exec_var_def(node, self.global_env)
            else:
                stmts.append(node)
        for stmt in stmts:
            self._exec_stmt(stmt, self.global_env)

    # ---- class definitions --------------------------------------- #

    def _define_class(self, node):
        superclass_name = node.bases[0].id if node.bases else "object"
        superclass = self.classes.get(superclass_name)

        own_attrs = {}
        own_methods = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                own_attrs[item.target.id] = item.value
            elif isinstance(item, ast.FunctionDef):
                own_methods[item.name] = item
            elif isinstance(item, ast.Pass):
                pass

        cls = ClassInfo(node.name, superclass, own_attrs, own_methods)
        self.classes[node.name] = cls
        self.global_env.set(node.name, cls)

    # ---- function definitions ------------------------------------ #

    def _define_function(self, node, env):
        params = [arg.arg for arg in node.args.args]
        globals_set = set()
        nonlocals_set = set()
        for item in node.body:
            if isinstance(item, ast.Global):
                globals_set.update(item.names)
            elif isinstance(item, ast.Nonlocal):
                nonlocals_set.update(item.names)
        func = FuncVal(node.name, params, node.body, env,
                       globals_set, nonlocals_set)
        env.set(node.name, func)

    # ---- variable definitions ------------------------------------ #

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
            self._exec_for(node, env)
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
            pass  # processed at function-definition time
        elif isinstance(node, ast.Nonlocal):
            pass  # processed at function-definition time

    def _exec_assign(self, node, env):
        value = self._eval_expr(node.value, env)
        for target in node.targets:
            self._assign_target(target, value, env)

    def _assign_target(self, target, value, env):
        if isinstance(target, ast.Name):
            env.assign(target.id, value)
        elif isinstance(target, ast.Attribute):
            obj = self._eval_expr(target.value, env)
            if isinstance(obj, NoneVal):
                raise ChocoPyError("Operation on None", 4)
            if isinstance(obj, ObjVal):
                obj.attrs[target.attr] = value
        elif isinstance(target, ast.Subscript):
            lst = self._eval_expr(target.value, env)
            if isinstance(lst, NoneVal):
                raise ChocoPyError("Operation on None", 4)
            idx = self._eval_expr(target.slice, env)
            if isinstance(lst, ListVal) and isinstance(idx, IntVal):
                if idx.v < 0 or idx.v >= len(lst.elems):
                    raise ChocoPyError("Index out of bounds", 3)
                lst.elems[idx.v] = value

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

    def _exec_for(self, node, env):
        iterable = self._eval_expr(node.iter, env)
        var_name = node.target.id

        if isinstance(iterable, NoneVal):
            raise ChocoPyError("Operation on None", 4)

        if isinstance(iterable, ListVal):
            for elem in iterable.elems:
                env.assign(var_name, elem)
                self._exec_block(node.body, env)
        elif isinstance(iterable, StrVal):
            for ch in iterable.v:
                env.assign(var_name, StrVal(ch))
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
        if isinstance(node, ast.Name):
            v = env.get(node.id)
            return v
        if isinstance(node, ast.BinOp):
            return self._eval_binop(node, env)
        if isinstance(node, ast.UnaryOp):
            return self._eval_unaryop(node, env)
        if isinstance(node, ast.BoolOp):
            return self._eval_boolop(node, env)
        if isinstance(node, ast.Compare):
            return self._eval_compare(node, env)
        if isinstance(node, ast.Call):
            return self._eval_call(node, env)
        if isinstance(node, ast.IfExp):
            return self._eval_ifexp(node, env)
        if isinstance(node, ast.Attribute):
            return self._eval_attribute(node, env)
        if isinstance(node, ast.Subscript):
            return self._eval_subscript(node, env)
        if isinstance(node, ast.List):
            return self._eval_list(node, env)
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

        if isinstance(left, IntVal) and isinstance(right, IntVal):
            if isinstance(op, ast.Add):      return IntVal(left.v + right.v)
            if isinstance(op, ast.Sub):      return IntVal(left.v - right.v)
            if isinstance(op, ast.Mult):     return IntVal(left.v * right.v)
            if isinstance(op, ast.FloorDiv):
                if right.v == 0:
                    raise ChocoPyError("Division by zero", 2)
                return IntVal(left.v // right.v)
            if isinstance(op, ast.Mod):
                if right.v == 0:
                    raise ChocoPyError("Division by zero", 2)
                return IntVal(left.v % right.v)

        if isinstance(left, StrVal) and isinstance(right, StrVal):
            if isinstance(op, ast.Add):
                return StrVal(left.v + right.v)

        if isinstance(left, ListVal) and isinstance(right, ListVal):
            if isinstance(op, ast.Add):
                return ListVal(list(left.elems) + list(right.elems))

        raise ChocoPyError("Unsupported binary operation", 1)

    def _eval_unaryop(self, node, env):
        operand = self._eval_expr(node.operand, env)
        if isinstance(node.op, ast.USub) and isinstance(operand, IntVal):
            return IntVal(-operand.v)
        if isinstance(node.op, ast.Not) and isinstance(operand, BoolVal):
            return BoolVal(not operand.v)
        raise ChocoPyError("Unsupported unary operation", 1)

    def _eval_boolop(self, node, env):
        if isinstance(node.op, ast.And):
            left = self._eval_expr(node.values[0], env)
            if not self._is_true(left):
                return BoolVal(False)
            return self._eval_expr(node.values[1], env)
        if isinstance(node.op, ast.Or):
            left = self._eval_expr(node.values[0], env)
            if self._is_true(left):
                return BoolVal(True)
            return self._eval_expr(node.values[1], env)
        raise ChocoPyError("Unsupported boolean operation", 1)

    def _eval_compare(self, node, env):
        left = self._eval_expr(node.left, env)
        right = self._eval_expr(node.comparators[0], env)
        op = node.ops[0]

        # 'is' operator: identity comparison
        if isinstance(op, ast.Is):
            if isinstance(left, NoneVal) and isinstance(right, NoneVal):
                return BoolVal(True)
            if isinstance(left, NoneVal) or isinstance(right, NoneVal):
                return BoolVal(False)
            return BoolVal(left is right)

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
            obj = self._eval_expr(node.func.value, env)
            if isinstance(obj, NoneVal):
                raise ChocoPyError("Operation on None", 4)
            method_name = node.func.attr
            args = [self._eval_expr(a, env) for a in node.args]
            return self._call_method(obj, method_name, args)

        # Function or class call: name(args)
        if isinstance(node.func, ast.Name):
            name = node.func.id
            func = env.get(name)
            args = [self._eval_expr(a, env) for a in node.args]

            if func == "builtin_print":
                return self._builtin_print(args)
            if func == "builtin_len":
                return self._builtin_len(args)
            if func == "builtin_input":
                return self._builtin_input()
            if isinstance(func, ClassInfo):
                return self._construct_object(func, args)
            if isinstance(func, FuncVal):
                return self._call_function(func, args)

        raise ChocoPyError("Not callable", 1)

    def _eval_ifexp(self, node, env):
        cond = self._eval_expr(node.test, env)
        if self._is_true(cond):
            return self._eval_expr(node.body, env)
        return self._eval_expr(node.orelse, env)

    def _eval_attribute(self, node, env):
        obj = self._eval_expr(node.value, env)
        if isinstance(obj, NoneVal):
            raise ChocoPyError("Operation on None", 4)
        if isinstance(obj, ObjVal):
            attr_name = node.attr
            if attr_name in obj.attrs:
                return obj.attrs[attr_name]
        raise ChocoPyError(f"No attribute: {node.attr}", 1)

    def _eval_subscript(self, node, env):
        obj = self._eval_expr(node.value, env)
        if isinstance(obj, NoneVal):
            raise ChocoPyError("Operation on None", 4)
        idx = self._eval_expr(node.slice, env)

        if isinstance(obj, ListVal) and isinstance(idx, IntVal):
            if idx.v < 0 or idx.v >= len(obj.elems):
                raise ChocoPyError("Index out of bounds", 3)
            return obj.elems[idx.v]

        if isinstance(obj, StrVal) and isinstance(idx, IntVal):
            if idx.v < 0 or idx.v >= len(obj.v):
                raise ChocoPyError("Index out of bounds", 3)
            return StrVal(obj.v[idx.v])

        raise ChocoPyError("Invalid subscript", 1)

    def _eval_list(self, node, env):
        elems = [self._eval_expr(e, env) for e in node.elts]
        return ListVal(elems)

    # ---- function / method calls --------------------------------- #

    def _call_function(self, func, args):
        new_env = Env(
            parent=func.env,
            global_env=self.global_env,
            globals_decl=func.globals_set,
            nonlocals_decl=func.nonlocals_set,
        )
        for param, arg in zip(func.params, args):
            new_env.set(param, arg)

        stmts = []
        for node in func.body:
            if isinstance(node, ast.FunctionDef):
                self._define_function(node, new_env)
            elif isinstance(node, ast.AnnAssign):
                self._exec_var_def(node, new_env)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                pass
            else:
                stmts.append(node)

        try:
            for stmt in stmts:
                self._exec_stmt(stmt, new_env)
        except ReturnSignal as r:
            return r.value
        return NONE

    def _construct_object(self, cls, args):
        all_attrs = cls.get_all_attrs()
        attrs = {}
        for attr_name, literal_node in all_attrs.items():
            attrs[attr_name] = self._eval_literal(literal_node)

        obj = ObjVal(cls.name, attrs)

        init_method = cls.get_method("__init__")
        if init_method:
            self._call_method_def(init_method, obj, args)

        return obj

    def _call_method(self, obj, method_name, args):
        if not isinstance(obj, ObjVal):
            raise ChocoPyError("Not an object", 1)
        cls = self.classes.get(obj.cls_name)
        if not cls:
            raise ChocoPyError(f"Unknown class: {obj.cls_name}", 1)
        method_node = cls.get_method(method_name)
        if not method_node:
            raise ChocoPyError(f"No method: {method_name}", 1)
        return self._call_method_def(method_node, obj, args)

    def _call_method_def(self, method_node, obj, args):
        params = [arg.arg for arg in method_node.args.args]

        globals_set = set()
        nonlocals_set = set()
        for item in method_node.body:
            if isinstance(item, ast.Global):
                globals_set.update(item.names)
            elif isinstance(item, ast.Nonlocal):
                nonlocals_set.update(item.names)

        new_env = Env(
            parent=self.global_env,
            global_env=self.global_env,
            globals_decl=globals_set,
            nonlocals_decl=nonlocals_set,
        )

        if params:
            new_env.set(params[0], obj)
        for param, arg in zip(params[1:], args):
            new_env.set(param, arg)

        stmts = []
        for node in method_node.body:
            if isinstance(node, ast.FunctionDef):
                self._define_function(node, new_env)
            elif isinstance(node, ast.AnnAssign):
                self._exec_var_def(node, new_env)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                pass
            else:
                stmts.append(node)

        try:
            for stmt in stmts:
                self._exec_stmt(stmt, new_env)
        except ReturnSignal as r:
            return r.value
        return NONE


# ================================================================== #
# Main                                                                #
# ================================================================== #

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
