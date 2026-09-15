#!/usr/bin/env python3
"""ChocoPy to C transpiler.

Reads a ChocoPy source file, generates C code that links against the
ChocoPy C runtime (runtime.h / runtime.c).

Usage:
    python3 transpile.py input.py output.c
"""


import ast
import sys


# ------------------------------------------------------------------ #
# Class metadata                                                      #
# ------------------------------------------------------------------ #

class ClassInfo:
    def __init__(self, name, super_name, own_attrs, own_methods):
        self.name = name
        self.super_name = super_name
        self.own_attrs = own_attrs        # [(attr_name, default_ast_node)]
        self.own_methods = own_methods    # [(method_name, FunctionDef)]
        # Resolved after _resolve_classes():
        self.all_attrs = []               # [(name, default_node)] parent-first
        self.method_names = []            # [name] in vtable order
        self.method_impls = {}            # {name: (owner_class, FunctionDef)}
        self.attr_index = {}              # {name: int}
        self.method_index = {}            # {name: int}


# ------------------------------------------------------------------ #
# Simple type environment for vtable index resolution                 #
# ------------------------------------------------------------------ #

class TypeEnv:
    def __init__(self, parent=None):
        self._m = {}
        self._parent = parent

    def set(self, name, typ):
        self._m[name] = typ

    def get(self, name):
        if name in self._m:
            return self._m[name]
        if self._parent:
            return self._parent.get(name)
        return None

    def child(self):
        return TypeEnv(parent=self)


# ------------------------------------------------------------------ #
# Transpiler                                                          #
# ------------------------------------------------------------------ #

class Transpiler:
    def __init__(self):
        self.classes = {}
        self.class_order = []
        self.functions = []
        self.global_vars = []
        self.top_stmts = []
        self._lines = []
        self._ind = 0
        self._tmp = 0

    # ---- helpers ------------------------------------------------- #

    def _emit(self, s=""):
        self._lines.append("  " * self._ind + s)

    def _fresh(self):
        self._tmp += 1
        return f"__t{self._tmp}"

    @staticmethod
    def _esc(s):
        return (s.replace("\\", "\\\\")
                 .replace('"', '\\"')
                 .replace("\n", "\\n")
                 .replace("\t", "\\t")
                 .replace("\r", "\\r"))

    # ---- entry point --------------------------------------------- #

    def transpile(self, source):
        tree = ast.parse(source)
        self._collect(tree)
        self._resolve_classes()
        self._generate()
        return "\n".join(self._lines) + "\n"

    # ---- phase 1: collect definitions ---------------------------- #

    def _collect(self, tree):
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._collect_class(node)
            elif isinstance(node, ast.FunctionDef):
                self.functions.append((node.name, node))
            elif isinstance(node, ast.AnnAssign):
                self.global_vars.append(node)
            else:
                self.top_stmts.append(node)

    def _collect_class(self, node):
        super_name = node.bases[0].id if node.bases else "object"
        attrs, methods = [], []
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                attrs.append((item.target.id, item.value))
            elif isinstance(item, ast.FunctionDef):
                methods.append((item.name, item))
        cls = ClassInfo(node.name, super_name, attrs, methods)
        self.classes[node.name] = cls
        self.class_order.append(node.name)

    # ---- phase 2: resolve class hierarchies ---------------------- #

    def _resolve_classes(self):
        for cn in self.class_order:
            cls = self.classes[cn]
            parent = self.classes.get(cls.super_name)
            if parent:
                cls.all_attrs = list(parent.all_attrs)
                cls.method_names = list(parent.method_names)
                cls.method_impls = dict(parent.method_impls)
            else:
                cls.all_attrs = []
                cls.method_names = []
                cls.method_impls = {}
            # own attributes
            for aname, adef in cls.own_attrs:
                found = False
                for i, (en, _) in enumerate(cls.all_attrs):
                    if en == aname:
                        cls.all_attrs[i] = (aname, adef)
                        found = True
                        break
                if not found:
                    cls.all_attrs.append((aname, adef))
            # own methods
            for mname, mnode in cls.own_methods:
                if mname in cls.method_impls:
                    cls.method_impls[mname] = (cn, mnode)
                else:
                    cls.method_names.append(mname)
                    cls.method_impls[mname] = (cn, mnode)
            cls.attr_index = {n: i for i, (n, _) in enumerate(cls.all_attrs)}
            cls.method_index = {n: i for i, n in enumerate(cls.method_names)}

    # ---- phase 3: code generation -------------------------------- #

    def _generate(self):
        self._emit('#include "runtime.h"')
        self._emit("#include <stdlib.h>")
        self._emit()
        self._gen_forward_decls()
        self._gen_vtables()
        self._gen_global_decls()
        self._gen_all_methods()
        self._gen_all_constructors()
        self._gen_all_functions()
        self._gen_main()

    # -- forward declarations --

    def _gen_forward_decls(self):
        seen = set()
        for cn in self.class_order:
            cls = self.classes[cn]
            for mname in cls.method_names:
                owner, _ = cls.method_impls[mname]
                key = f"{owner}_{mname}"
                if key not in seen:
                    seen.add(key)
                    self._emit(f"ChpyVal* method_{key}(int, ChpyVal**);")
            self._emit(f"ChpyVal* construct_{cn}(int, ChpyVal**);")
        for fname, _ in self.functions:
            self._emit(f"ChpyVal* fn_{fname}(int, ChpyVal**);")
        self._emit()

    # -- vtable arrays --

    def _gen_vtables(self):
        for cn in self.class_order:
            cls = self.classes[cn]
            if cls.method_names:
                entries = []
                for mname in cls.method_names:
                    owner, _ = cls.method_impls[mname]
                    entries.append(f"(ChpyFuncPtr)method_{owner}_{mname}")
                self._emit(f"ChpyFuncPtr vtable_{cn}[] = {{ {', '.join(entries)} }};")
            else:
                self._emit(f"ChpyFuncPtr vtable_{cn}[1] = {{ NULL }};")
        self._emit()

    # -- global variable declarations --

    def _gen_global_decls(self):
        for node in self.global_vars:
            self._emit(f"ChpyVal* {node.target.id};")
        if self.global_vars:
            self._emit()

    # -- methods --

    def _gen_all_methods(self):
        seen = set()
        for cn in self.class_order:
            cls = self.classes[cn]
            for mname, mnode in cls.own_methods:
                key = f"{cn}_{mname}"
                if key not in seen:
                    seen.add(key)
                    self._gen_method(cn, cls, mname, mnode)

    def _gen_method(self, cn, cls, mname, mnode):
        self._emit(f"ChpyVal* method_{cn}_{mname}(int nargs, ChpyVal** args) {{")
        self._ind += 1
        env = TypeEnv()
        params = [a.arg for a in mnode.args.args]
        for i, p in enumerate(params):
            self._emit(f"ChpyVal* {p} = args[{i}];")
            ann = mnode.args.args[i].annotation
            t = self._ann_type(ann)
            if t:
                env.set(p, t)
        self._emit_body(mnode.body, env)
        self._emit("return chpy_none();")
        self._ind -= 1
        self._emit("}")
        self._emit()

    # -- constructors --

    def _gen_all_constructors(self):
        for cn in self.class_order:
            self._gen_constructor(cn, self.classes[cn])

    def _gen_constructor(self, cn, cls):
        self._emit(f"ChpyVal* construct_{cn}(int nargs, ChpyVal** args) {{")
        self._ind += 1
        na = len(cls.all_attrs)
        nm = len(cls.method_names)
        if na > 0:
            defs = ", ".join(self._gen_literal(d) for _, d in cls.all_attrs)
            self._emit(f'ChpyVal* obj = chpy_new_obj("{cn}", '
                       f"(ChpyFuncPtr*)vtable_{cn}, {nm}, {na}, {defs});")
        else:
            self._emit(f'ChpyVal* obj = chpy_new_obj("{cn}", '
                       f"(ChpyFuncPtr*)vtable_{cn}, {nm}, 0);")
        if "__init__" in cls.method_index:
            idx = cls.method_index["__init__"]
            self._emit(f"ChpyVal* __ia[nargs + 1];")
            self._emit(f"__ia[0] = obj;")
            self._emit(f"for (int __i = 0; __i < nargs; __i++) __ia[__i+1] = args[__i];")
            self._emit(f"vtable_{cn}[{idx}](nargs + 1, __ia);")
        self._emit("return obj;")
        self._ind -= 1
        self._emit("}")
        self._emit()

    # -- user functions --

    def _gen_all_functions(self):
        for fname, fnode in self.functions:
            self._gen_function(fname, fnode)

    def _gen_function(self, fname, fnode):
        self._emit(f"ChpyVal* fn_{fname}(int nargs, ChpyVal** args) {{")
        self._ind += 1
        env = TypeEnv()
        params = [a.arg for a in fnode.args.args]
        for i, p in enumerate(params):
            self._emit(f"ChpyVal* {p} = args[{i}];")
            ann = fnode.args.args[i].annotation
            t = self._ann_type(ann)
            if t:
                env.set(p, t)
        self._emit_body(fnode.body, env)
        self._emit("return chpy_none();")
        self._ind -= 1
        self._emit("}")
        self._emit()

    # -- main --

    def _gen_main(self):
        self._emit("int main(void) {")
        self._ind += 1
        env = TypeEnv()
        for node in self.global_vars:
            name = node.target.id
            val = self._gen_literal(node.value)
            self._emit(f"{name} = {val};")
            t = self._ann_type(node.annotation) if node.annotation else None
            if t:
                env.set(name, t)
        for stmt in self.top_stmts:
            self._emit_stmt(stmt, env)
        self._emit("return 0;")
        self._ind -= 1
        self._emit("}")

    # ---- type annotation helper ---------------------------------- #

    def _ann_type(self, node):
        if node is None:
            return None
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def _expr_type(self, node, env):
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in self.classes:
                return node.func.id
        return None

    # ---- statement emission -------------------------------------- #

    def _emit_body(self, stmts, env):
        for s in stmts:
            self._emit_stmt(s, env)

    def _emit_stmt(self, node, env):
        if isinstance(node, ast.Expr):
            e = self._gen_expr(node.value, env)
            self._emit(f"{e};")
        elif isinstance(node, ast.Assign):
            self._emit_assign(node, env)
        elif isinstance(node, ast.AnnAssign):
            self._emit_ann_assign(node, env)
        elif isinstance(node, ast.If):
            self._emit_if(node, env)
        elif isinstance(node, ast.While):
            self._emit_while(node, env)
        elif isinstance(node, ast.For):
            self._emit_for(node, env)
        elif isinstance(node, ast.Return):
            if node.value:
                e = self._gen_expr(node.value, env)
                self._emit(f"return {e};")
            else:
                self._emit("return chpy_none();")
        elif isinstance(node, ast.Pass):
            pass
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            pass
        elif isinstance(node, ast.FunctionDef):
            pass  # nested funcs handled separately if needed

    def _emit_assign(self, node, env):
        val = self._gen_expr(node.value, env)
        if len(node.targets) > 1:
            tmp = self._fresh()
            self._emit(f"ChpyVal* {tmp} = {val};")
            for t in node.targets:
                self._emit_target(t, tmp, env)
        else:
            self._emit_target(node.targets[0], val, env)

    def _emit_target(self, target, val_expr, env):
        if isinstance(target, ast.Name):
            self._emit(f"{target.id} = {val_expr};")
        elif isinstance(target, ast.Attribute):
            obj = self._gen_expr(target.value, env)
            ot = self._expr_type(target.value, env)
            idx = 0
            if ot and ot in self.classes:
                idx = self.classes[ot].attr_index.get(target.attr, 0)
            self._emit(f"chpy_set_attr({obj}, {idx}, {val_expr});")
        elif isinstance(target, ast.Subscript):
            obj = self._gen_expr(target.value, env)
            ix = self._gen_expr(target.slice, env)
            self._emit(f"chpy_index_set({obj}, {ix}, {val_expr});")

    def _emit_ann_assign(self, node, env):
        name = node.target.id
        val = self._gen_literal(node.value)
        self._emit(f"ChpyVal* {name} = {val};")
        t = self._ann_type(node.annotation)
        if t:
            env.set(name, t)

    def _emit_if(self, node, env):
        cond = self._gen_expr(node.test, env)
        self._emit(f"if (chpy_is_true({cond})) {{")
        self._ind += 1
        self._emit_body(node.body, env)
        self._ind -= 1
        self._emit_else(node.orelse, env)

    def _emit_else(self, orelse, env):
        if not orelse:
            self._emit("}")
            return
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            n = orelse[0]
            cond = self._gen_expr(n.test, env)
            self._emit(f"}} else if (chpy_is_true({cond})) {{")
            self._ind += 1
            self._emit_body(n.body, env)
            self._ind -= 1
            self._emit_else(n.orelse, env)
        else:
            self._emit("} else {")
            self._ind += 1
            self._emit_body(orelse, env)
            self._ind -= 1
            self._emit("}")

    def _emit_while(self, node, env):
        self._emit("while (1) {")
        self._ind += 1
        cond = self._gen_expr(node.test, env)
        self._emit(f"if (!chpy_is_true({cond})) break;")
        self._emit_body(node.body, env)
        self._ind -= 1
        self._emit("}")

    def _emit_for(self, node, env):
        it = self._gen_expr(node.iter, env)
        var = node.target.id
        tv = self._fresh()
        tl = self._fresh()
        ti = self._fresh()
        self._emit("{")
        self._ind += 1
        self._emit(f"ChpyVal* {tv} = {it};")
        self._emit(f"int {tl} = chpy_iter_len({tv});")
        self._emit(f"for (int {ti} = 0; {ti} < {tl}; {ti}++) {{")
        self._ind += 1
        self._emit(f"{var} = chpy_iter_get({tv}, {ti});")
        self._emit_body(node.body, env)
        self._ind -= 1
        self._emit("}")
        self._ind -= 1
        self._emit("}")

    # ---- expression generation ----------------------------------- #

    def _gen_expr(self, node, env):
        if isinstance(node, ast.Constant):
            return self._gen_constant(node)
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.BinOp):
            return self._gen_binop(node, env)
        if isinstance(node, ast.UnaryOp):
            return self._gen_unaryop(node, env)
        if isinstance(node, ast.BoolOp):
            return self._gen_boolop(node, env)
        if isinstance(node, ast.Compare):
            return self._gen_compare(node, env)
        if isinstance(node, ast.Call):
            return self._gen_call(node, env)
        if isinstance(node, ast.IfExp):
            return self._gen_ifexp(node, env)
        if isinstance(node, ast.Attribute):
            return self._gen_attr(node, env)
        if isinstance(node, ast.Subscript):
            return self._gen_subscript(node, env)
        if isinstance(node, ast.List):
            return self._gen_list(node, env)
        return "chpy_none()"

    def _gen_constant(self, node):
        v = node.value
        if v is None:
            return "chpy_none()"
        if isinstance(v, bool):
            return f"chpy_bool({1 if v else 0})"
        if isinstance(v, int):
            return f"chpy_int({v})"
        if isinstance(v, str):
            return f'chpy_str("{self._esc(v)}")'
        return "chpy_none()"

    def _gen_literal(self, node):
        if isinstance(node, ast.Constant):
            return self._gen_constant(node)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self._gen_literal(node.operand)
            return f"chpy_neg({inner})"
        if isinstance(node, ast.List) and len(node.elts) == 0:
            return "chpy_empty_list()"
        return "chpy_none()"

    def _gen_binop(self, node, env):
        l = self._gen_expr(node.left, env)
        r = self._gen_expr(node.right, env)
        m = {
            ast.Add: "chpy_add",
            ast.Sub: "chpy_sub",
            ast.Mult: "chpy_mul",
            ast.FloorDiv: "chpy_div",
            ast.Mod: "chpy_mod",
        }
        fn = m.get(type(node.op))
        return f"{fn}({l}, {r})" if fn else "chpy_none()"

    def _gen_unaryop(self, node, env):
        o = self._gen_expr(node.operand, env)
        if isinstance(node.op, ast.USub):
            return f"chpy_neg({o})"
        if isinstance(node.op, ast.Not):
            return f"chpy_not({o})"
        return "chpy_none()"

    def _gen_boolop(self, node, env):
        l = self._gen_expr(node.values[0], env)
        r = self._gen_expr(node.values[1], env)
        if isinstance(node.op, ast.And):
            return f"(chpy_is_true({l}) ? {r} : chpy_bool(0))"
        if isinstance(node.op, ast.Or):
            return f"(chpy_is_true({l}) ? chpy_bool(1) : {r})"
        return "chpy_none()"

    def _gen_compare(self, node, env):
        l = self._gen_expr(node.left, env)
        r = self._gen_expr(node.comparators[0], env)
        m = {
            ast.Eq: "chpy_eq",
            ast.NotEq: "chpy_neq",
            ast.Lt: "chpy_lt",
            ast.LtE: "chpy_lte",
            ast.Gt: "chpy_gt",
            ast.GtE: "chpy_gte",
            ast.Is: "chpy_is_op",
        }
        fn = m.get(type(node.ops[0]))
        return f"{fn}({l}, {r})" if fn else "chpy_none()"

    def _gen_call(self, node, env):
        # Method call: obj.method(args)
        if isinstance(node.func, ast.Attribute):
            obj = self._gen_expr(node.func.value, env)
            mname = node.func.attr
            ot = self._expr_type(node.func.value, env)
            idx = 0
            if ot and ot in self.classes:
                idx = self.classes[ot].method_index.get(mname, 0)
            args = [self._gen_expr(a, env) for a in node.args]
            return self._fmt_method_call(obj, idx, args)

        if isinstance(node.func, ast.Name):
            name = node.func.id
            # Built-ins
            if name == "print":
                a = self._gen_expr(node.args[0], env)
                return f"chpy_print({a})"
            if name == "len":
                a = self._gen_expr(node.args[0], env)
                return f"chpy_len({a})"
            # Constructor
            if name in self.classes:
                args = [self._gen_expr(a, env) for a in node.args]
                return self._fmt_func_call(f"construct_{name}", args)
            # User function
            args = [self._gen_expr(a, env) for a in node.args]
            return self._fmt_func_call(f"fn_{name}", args)

        return "chpy_none()"

    def _gen_ifexp(self, node, env):
        c = self._gen_expr(node.test, env)
        t = self._gen_expr(node.body, env)
        f = self._gen_expr(node.orelse, env)
        return f"(chpy_is_true({c}) ? {t} : {f})"

    def _gen_attr(self, node, env):
        obj = self._gen_expr(node.value, env)
        ot = self._expr_type(node.value, env)
        idx = 0
        if ot and ot in self.classes:
            idx = self.classes[ot].attr_index.get(node.attr, 0)
        return f"chpy_get_attr({obj}, {idx})"

    def _gen_subscript(self, node, env):
        obj = self._gen_expr(node.value, env)
        ix = self._gen_expr(node.slice, env)
        return f"chpy_index({obj}, {ix})"

    def _gen_list(self, node, env):
        if not node.elts:
            return "chpy_empty_list()"
        elems = [self._gen_expr(e, env) for e in node.elts]
        return f"chpy_new_list({len(elems)}, {', '.join(elems)})"

    # ---- call formatting helpers --------------------------------- #

    def _fmt_func_call(self, fn, args):
        if args:
            astr = ", ".join(args)
            return f"{fn}({len(args)}, (ChpyVal*[]){{{astr}}})"
        return f"{fn}(0, NULL)"

    def _fmt_method_call(self, obj, idx, args):
        if args:
            astr = ", ".join(args)
            return (f"chpy_call_method({obj}, {idx}, "
                    f"{len(args)}, (ChpyVal*[]){{{astr}}})")
        return f"chpy_call_method({obj}, {idx}, 0, NULL)"


# ------------------------------------------------------------------ #
# Main                                                                #
# ------------------------------------------------------------------ #

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 transpile.py input.py output.c",
              file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    t = Transpiler()
    c_code = t.transpile(source)
    with open(sys.argv[2], "w") as f:
        f.write(c_code)


if __name__ == "__main__":
    main()
