"""
ChocoPy Type Checker — Solution Implementation

"""

import ast
from typing import Dict, List, Optional, Tuple


# ============================================================
# Type representations
# ============================================================

class CType:
    pass

class IntType(CType):
    def __repr__(self): return "int"
    def __eq__(self, o): return isinstance(o, IntType)
    def __hash__(self): return hash("int")

class BoolType(CType):
    def __repr__(self): return "bool"
    def __eq__(self, o): return isinstance(o, BoolType)
    def __hash__(self): return hash("bool")

class StrType(CType):
    def __repr__(self): return "str"
    def __eq__(self, o): return isinstance(o, StrType)
    def __hash__(self): return hash("str")

class NoneType_(CType):
    def __repr__(self): return "<None>"
    def __eq__(self, o): return isinstance(o, NoneType_)
    def __hash__(self): return hash("<None>")

class EmptyType(CType):
    def __repr__(self): return "<Empty>"
    def __eq__(self, o): return isinstance(o, EmptyType)
    def __hash__(self): return hash("<Empty>")

class ObjectType(CType):
    def __repr__(self): return "object"
    def __eq__(self, o): return isinstance(o, ObjectType)
    def __hash__(self): return hash("object")

class ListType(CType):
    def __init__(self, elem: CType):
        self.elem = elem
    def __repr__(self): return f"[{self.elem}]"
    def __eq__(self, o): return isinstance(o, ListType) and self.elem == o.elem
    def __hash__(self): return hash(("list", self.elem))

class ClassType(CType):
    def __init__(self, name: str):
        self.name = name
    def __repr__(self): return self.name
    def __eq__(self, o): return isinstance(o, ClassType) and self.name == o.name
    def __hash__(self): return hash(("class", self.name))

class FuncType(CType):
    def __init__(self, params: Tuple[CType, ...], ret: CType, names: Tuple[str, ...] = ()):
        self.params = params
        self.ret = ret
        self.names = names
    def __repr__(self):
        return f"({', '.join(str(p) for p in self.params)}) -> {self.ret}"
    def __eq__(self, o):
        return isinstance(o, FuncType) and self.params == o.params and self.ret == o.ret
    def __hash__(self):
        return hash(("func", self.params, self.ret))


# ============================================================
# Class info
# ============================================================

class ClassInfo:
    def __init__(self, name: str, superclass: Optional[str],
                 attrs: Dict[str, CType], methods: Dict[str, FuncType]):
        self.name = name
        self.superclass = superclass
        self.attrs = dict(attrs)
        self.methods = dict(methods)


# ============================================================
# Scope
# ============================================================

class Scope:
    def __init__(self, parent: Optional["Scope"] = None):
        self.bindings: Dict[str, CType] = {}
        self.parent = parent

    def define(self, name: str, typ: CType):
        self.bindings[name] = typ

    def lookup(self, name: str) -> Optional[CType]:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        return None


# ============================================================
# Type Checker
# ============================================================

class TypeChecker:
    def __init__(self):
        self.classes: Dict[str, ClassInfo] = {}
        self.errors: List[str] = []
        self.global_scope = Scope()
        self._init_builtins()

    def _init_builtins(self):
        self.classes["object"] = ClassInfo("object", None, {},
            {"__init__": FuncType((ClassType("object"),), NoneType_(), ("self",))})
        self.classes["int"] = ClassInfo("int", "object", {},
            {"__init__": FuncType((ClassType("int"),), NoneType_(), ("self",))})
        self.classes["bool"] = ClassInfo("bool", "object", {},
            {"__init__": FuncType((ClassType("bool"),), NoneType_(), ("self",))})
        self.classes["str"] = ClassInfo("str", "object", {},
            {"__init__": FuncType((ClassType("str"),), NoneType_(), ("self",))})

    def _err(self, msg: str):
        self.errors.append(msg)

    # ----------------------------------------------------------
    # Type resolution
    # ----------------------------------------------------------

    def _resolve_type(self, node) -> CType:
        if isinstance(node, ast.Name):
            n = node.id
            if n == "int": return IntType()
            if n == "bool": return BoolType()
            if n == "str": return StrType()
            if n == "object": return ObjectType()
            if n in self.classes: return ClassType(n)
            self._err(f"Unknown type '{n}'")
            return ObjectType()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            n = node.value
            if n == "int": return IntType()
            if n == "bool": return BoolType()
            if n == "str": return StrType()
            if n == "object": return ObjectType()
            if n in self.classes: return ClassType(n)
            self._err(f"Unknown type '{n}'")
            return ObjectType()
        if isinstance(node, ast.List):
            if len(node.elts) == 1:
                return ListType(self._resolve_type(node.elts[0]))
            self._err("Invalid list type annotation")
            return ObjectType()
        if isinstance(node, ast.Subscript):
            return ListType(self._resolve_type(node.slice))
        self._err(f"Invalid type annotation")
        return ObjectType()

    # ----------------------------------------------------------
    # Type utilities
    # ----------------------------------------------------------

    def _is_primitive(self, t: CType) -> bool:
        return isinstance(t, (IntType, BoolType, StrType))

    def _class_name(self, t: CType) -> Optional[str]:
        if isinstance(t, IntType): return "int"
        if isinstance(t, BoolType): return "bool"
        if isinstance(t, StrType): return "str"
        if isinstance(t, ObjectType): return "object"
        if isinstance(t, ClassType): return t.name
        return None

    def _name_to_type(self, n: str) -> CType:
        if n == "int": return IntType()
        if n == "bool": return BoolType()
        if n == "str": return StrType()
        if n == "object": return ObjectType()
        return ClassType(n)

    def _all_attrs(self, cname: str) -> Dict[str, CType]:
        result = {}
        ci = self.classes.get(cname)
        if ci and ci.superclass:
            result.update(self._all_attrs(ci.superclass))
        if ci:
            result.update(ci.attrs)
        return result

    def _all_methods(self, cname: str) -> Dict[str, FuncType]:
        result = {}
        ci = self.classes.get(cname)
        if ci and ci.superclass:
            result.update(self._all_methods(ci.superclass))
        if ci:
            result.update(ci.methods)
        return result

    def _ancestors(self, cname: str) -> List[str]:
        chain = []
        cur = cname
        while cur is not None:
            chain.append(cur)
            ci = self.classes.get(cur)
            cur = ci.superclass if ci else None
        return chain

    # ----------------------------------------------------------
    # Conformance: t1 <= t2
    # ----------------------------------------------------------

    def conforms(self, t1: CType, t2: CType) -> bool:
        if t1 == t2:
            return True
        if isinstance(t1, NoneType_) and isinstance(t2, ObjectType):
            return True
        if isinstance(t1, EmptyType) and isinstance(t2, ObjectType):
            return True
        if isinstance(t1, ListType) and isinstance(t2, ObjectType):
            return True
        n1 = self._class_name(t1)
        n2 = self._class_name(t2)
        if n1 is not None and n2 is not None:
            return n2 in self._ancestors(n1)
        return False

    # ----------------------------------------------------------
    # Assignment compatibility: t1 <=a t2
    # ----------------------------------------------------------

    def assign_compat(self, t1: CType, t2: CType) -> bool:
        if self.conforms(t1, t2):
            return True
        if isinstance(t1, NoneType_) and not self._is_primitive(t2):
            return True
        if isinstance(t1, EmptyType) and isinstance(t2, ListType):
            return True
        if (isinstance(t1, ListType) and isinstance(t1.elem, NoneType_)
                and isinstance(t2, ListType)):
            return self.assign_compat(NoneType_(), t2.elem)
        return False

    # ----------------------------------------------------------
    # Join (LUB): t1 join t2
    # ----------------------------------------------------------

    def join(self, t1: CType, t2: CType) -> CType:
        if self.assign_compat(t1, t2):
            return t2
        if self.assign_compat(t2, t1):
            return t1
        n1 = self._class_name(t1)
        n2 = self._class_name(t2)
        if n1 is not None and n2 is not None:
            a1 = self._ancestors(n1)
            cur = n2
            while cur is not None:
                if cur in a1:
                    return self._name_to_type(cur)
                ci = self.classes.get(cur)
                cur = ci.superclass if ci else None
        return ObjectType()

    # ----------------------------------------------------------
    # Function signature extraction
    # ----------------------------------------------------------

    def _func_sig(self, node: ast.FunctionDef) -> Optional[FuncType]:
        params = []
        names = []
        for arg in node.args.args:
            if arg.annotation is None:
                self._err(f"Parameter '{arg.arg}' missing type annotation")
                return None
            params.append(self._resolve_type(arg.annotation))
            names.append(arg.arg)
        ret = NoneType_()
        if node.returns is not None:
            ret = self._resolve_type(node.returns)
        return FuncType(tuple(params), ret, tuple(names))

    # ----------------------------------------------------------
    # Phase 1: Collect class definitions (two-pass)
    # ----------------------------------------------------------

    def _collect_classes(self, tree: ast.Module):
        # Pass 1: register all class names with empty bodies
        class_nodes = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            name = node.name
            if name in self.classes:
                self._err(f"Class '{name}' already defined")
                continue
            if not node.bases or len(node.bases) != 1:
                self._err(f"Class '{name}' must have exactly one superclass")
                continue
            base = node.bases[0]
            if not isinstance(base, ast.Name):
                self._err(f"Superclass of '{name}' must be an identifier")
                continue
            super_name = base.id
            if super_name not in self.classes:
                self._err(f"Superclass '{super_name}' of '{name}' not defined")
                continue
            if super_name in ("int", "bool", "str"):
                self._err(f"Cannot extend special class '{super_name}'")
                continue
            # Register with empty attrs/methods — filled in pass 2
            self.classes[name] = ClassInfo(name, super_name, {}, {})
            class_nodes.append(node)

        if self.errors:
            return

        # Pass 2: fill in attributes and methods, validate overrides
        for node in class_nodes:
            name = node.name
            ci = self.classes[name]
            inherited_attrs = self._all_attrs(ci.superclass)

            for item in node.body:
                if isinstance(item, ast.Pass):
                    continue
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    aname = item.target.id
                    atype = self._resolve_type(item.annotation)
                    if aname in inherited_attrs:
                        self._err(f"Cannot redefine inherited attribute '{aname}' in class '{name}'")
                    ci.attrs[aname] = atype
                elif isinstance(item, ast.FunctionDef):
                    mname = item.name
                    mtype = self._func_sig(item)
                    if mtype is not None:
                        inherited_methods = self._all_methods(ci.superclass)
                        if mname in inherited_methods:
                            old = inherited_methods[mname]
                            if mtype.ret != old.ret:
                                self._err(
                                    f"Method '{mname}' in '{name}' overrides with "
                                    f"different return type: {mtype.ret} vs {old.ret}")
                            if mtype.params[1:] != old.params[1:]:
                                self._err(
                                    f"Method '{mname}' in '{name}' overrides with "
                                    f"different parameter types")
                        ci.methods[mname] = mtype

    # ----------------------------------------------------------
    # Phase 2: Collect global definitions
    # ----------------------------------------------------------

    def _collect_globals(self, tree: ast.Module, scope: Scope):
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                vtype = self._resolve_type(node.annotation)
                scope.define(node.target.id, vtype)
            elif isinstance(node, ast.FunctionDef):
                sig = self._func_sig(node)
                if sig:
                    scope.define(node.name, sig)

    # ----------------------------------------------------------
    # Phase 3: Type check
    # ----------------------------------------------------------

    def _check_program(self, tree: ast.Module, scope: Scope):
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._check_class_body(node, scope)
            elif isinstance(node, ast.FunctionDef):
                self._check_func_def(node, scope, None)
            elif isinstance(node, ast.AnnAssign):
                self._check_var_def(node, scope, None)
            else:
                self._check_stmt(node, scope, None, None)

    def _check_class_body(self, node: ast.ClassDef, global_scope: Scope):
        cname = node.name
        if cname not in self.classes:
            return
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                self._check_method_def(item, global_scope, cname)
            elif isinstance(item, ast.AnnAssign):
                if item.value is not None:
                    val_type = self._infer_literal(item.value)
                    ann_type = self._resolve_type(item.annotation)
                    if not self.assign_compat(val_type, ann_type):
                        self._err(f"Cannot initialize attribute with {val_type}")

    def _infer_literal(self, node) -> CType:
        if isinstance(node, ast.Constant):
            if node.value is None: return NoneType_()
            if isinstance(node.value, bool): return BoolType()
            if isinstance(node.value, int): return IntType()
            if isinstance(node.value, str): return StrType()
        if isinstance(node, ast.List) and len(node.elts) == 0:
            return EmptyType()
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return IntType()
        return ObjectType()

    def _check_method_def(self, node: ast.FunctionDef, global_scope: Scope, class_name: str):
        sig = self._all_methods(class_name).get(node.name)
        if sig is None:
            return
        func_scope = Scope(parent=global_scope)
        for arg, ptype in zip(node.args.args, sig.params):
            func_scope.define(arg.arg, ptype)
        self._collect_local_defs(node.body, func_scope)
        for stmt in node.body:
            if isinstance(stmt, (ast.Global, ast.Nonlocal, ast.AnnAssign, ast.FunctionDef)):
                if isinstance(stmt, ast.AnnAssign):
                    self._check_var_def(stmt, func_scope, class_name)
                elif isinstance(stmt, ast.FunctionDef):
                    self._check_func_def(stmt, func_scope, class_name)
                continue
            self._check_stmt(stmt, func_scope, class_name, sig.ret)

    def _check_func_def(self, node: ast.FunctionDef, parent_scope: Scope,
                        class_name: Optional[str]):
        sig_type = parent_scope.lookup(node.name)
        if not isinstance(sig_type, FuncType):
            return
        func_scope = Scope(parent=parent_scope)

        # Handle global/nonlocal declarations
        globals_set = set()
        nonlocals_set = set()
        for stmt in node.body:
            if isinstance(stmt, ast.Global):
                globals_set.update(stmt.names)
            elif isinstance(stmt, ast.Nonlocal):
                nonlocals_set.update(stmt.names)

        # Bind globals from top-level scope
        top = parent_scope
        while top.parent is not None:
            top = top.parent
        for gn in globals_set:
            gt = top.lookup(gn)
            if gt is not None:
                func_scope.define(gn, gt)

        # Bind nonlocals from enclosing scope
        for nl in nonlocals_set:
            nt = parent_scope.lookup(nl)
            if nt is not None:
                func_scope.define(nl, nt)

        # Parameters
        for arg, ptype in zip(node.args.args, sig_type.params):
            func_scope.define(arg.arg, ptype)

        # Local definitions
        self._collect_local_defs(node.body, func_scope)

        for stmt in node.body:
            if isinstance(stmt, (ast.Global, ast.Nonlocal)):
                continue
            if isinstance(stmt, ast.AnnAssign):
                self._check_var_def(stmt, func_scope, class_name)
                continue
            if isinstance(stmt, ast.FunctionDef):
                self._check_func_def(stmt, func_scope, class_name)
                continue
            self._check_stmt(stmt, func_scope, class_name, sig_type.ret)

    def _collect_local_defs(self, body, func_scope: Scope):
        for stmt in body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                vtype = self._resolve_type(stmt.annotation)
                func_scope.define(stmt.target.id, vtype)
            elif isinstance(stmt, ast.FunctionDef):
                sig = self._func_sig(stmt)
                if sig:
                    func_scope.define(stmt.name, sig)

    def _check_var_def(self, node: ast.AnnAssign, scope: Scope,
                       class_name: Optional[str]):
        ann_type = self._resolve_type(node.annotation)
        if node.value is not None:
            val_type = self._check_expr(node.value, scope, class_name)
            if not self.assign_compat(val_type, ann_type):
                self._err(f"Cannot initialize variable with {val_type} for type {ann_type}")

    # ----------------------------------------------------------
    # Statement checking
    # ----------------------------------------------------------

    def _check_stmt(self, node, scope: Scope, class_name: Optional[str],
                    ret_type: Optional[CType]):
        if isinstance(node, ast.Pass):
            return

        if isinstance(node, ast.Expr):
            self._check_expr(node.value, scope, class_name)
            return

        if isinstance(node, ast.Assign):
            rhs_type = self._check_expr(node.value, scope, class_name)
            for target in node.targets:
                self._check_assign_target(target, rhs_type, scope, class_name)
            return

        if isinstance(node, ast.Return):
            if ret_type is None:
                self._err("Return outside function")
                return
            if node.value is None:
                if not self.assign_compat(NoneType_(), ret_type):
                    self._err(f"Cannot return None for type {ret_type}")
            else:
                val_type = self._check_expr(node.value, scope, class_name)
                if not self.assign_compat(val_type, ret_type):
                    self._err(f"Return type {val_type} not compatible with {ret_type}")
            return

        if isinstance(node, ast.If):
            ct = self._check_expr(node.test, scope, class_name)
            if not isinstance(ct, BoolType):
                self._err(f"If condition must be bool, got {ct}")
            for s in node.body:
                self._check_stmt(s, scope, class_name, ret_type)
            for s in node.orelse:
                self._check_stmt(s, scope, class_name, ret_type)
            return

        if isinstance(node, ast.While):
            ct = self._check_expr(node.test, scope, class_name)
            if not isinstance(ct, BoolType):
                self._err(f"While condition must be bool, got {ct}")
            for s in node.body:
                self._check_stmt(s, scope, class_name, ret_type)
            return

        if isinstance(node, ast.For):
            if not isinstance(node.target, ast.Name):
                self._err("For target must be identifier")
                return
            iter_type = self._check_expr(node.iter, scope, class_name)
            vname = node.target.id
            vtype = scope.lookup(vname)
            if vtype is None:
                self._err(f"For variable '{vname}' not declared")
                return
            if isinstance(iter_type, ListType):
                if not self.assign_compat(iter_type.elem, vtype):
                    self._err(f"List element type {iter_type.elem} not compatible "
                              f"with loop variable type {vtype}")
            elif isinstance(iter_type, StrType):
                if not self.assign_compat(StrType(), vtype):
                    self._err(f"str not compatible with loop variable type {vtype}")
            else:
                self._err(f"Cannot iterate over {iter_type}")
            for s in node.body:
                self._check_stmt(s, scope, class_name, ret_type)
            return

    def _check_assign_target(self, target, rhs_type: CType, scope: Scope,
                             class_name: Optional[str]):
        if isinstance(target, ast.Name):
            vt = scope.lookup(target.id)
            if vt is None:
                self._err(f"Undefined variable '{target.id}'")
                return
            if isinstance(vt, FuncType):
                self._err(f"Cannot assign to function '{target.id}'")
                return
            if not self.assign_compat(rhs_type, vt):
                self._err(f"Cannot assign {rhs_type} to variable of type {vt}")
            return

        if isinstance(target, ast.Attribute):
            obj_t = self._check_expr(target.value, scope, class_name)
            cn = self._class_name(obj_t)
            if cn is None:
                self._err(f"Cannot access attribute on {obj_t}")
                return
            aa = self._all_attrs(cn)
            if target.attr not in aa:
                self._err(f"'{cn}' has no attribute '{target.attr}'")
                return
            if not self.assign_compat(rhs_type, aa[target.attr]):
                self._err(f"Cannot assign {rhs_type} to attribute of type {aa[target.attr]}")
            return

        if isinstance(target, ast.Subscript):
            obj_t = self._check_expr(target.value, scope, class_name)
            self._check_expr(target.slice, scope, class_name)
            if isinstance(obj_t, ListType):
                if not self.assign_compat(rhs_type, obj_t.elem):
                    self._err(f"Cannot assign {rhs_type} to list element of type {obj_t.elem}")
            else:
                self._err(f"Cannot index-assign to {obj_t}")
            return

    # ----------------------------------------------------------
    # Expression checking
    # ----------------------------------------------------------

    def _check_expr(self, node, scope: Scope, class_name: Optional[str]) -> CType:
        if isinstance(node, ast.Constant):
            if node.value is None: return NoneType_()
            if isinstance(node.value, bool): return BoolType()
            if isinstance(node.value, int): return IntType()
            if isinstance(node.value, str): return StrType()
            return ObjectType()

        if isinstance(node, ast.Name):
            t = scope.lookup(node.id)
            if t is None:
                if node.id in self.classes:
                    return ClassType(node.id)
                self._err(f"Undefined name '{node.id}'")
                return ObjectType()
            if isinstance(t, FuncType):
                self._err(f"Cannot use function '{node.id}' as value")
                return ObjectType()
            return t

        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                t = self._check_expr(node.operand, scope, class_name)
                if not isinstance(t, IntType):
                    self._err(f"Cannot negate {t}")
                return IntType()
            if isinstance(node.op, ast.Not):
                t = self._check_expr(node.operand, scope, class_name)
                if not isinstance(t, BoolType):
                    self._err(f"Cannot apply 'not' to {t}")
                return BoolType()
            return ObjectType()

        if isinstance(node, ast.BoolOp):
            for v in node.values:
                t = self._check_expr(v, scope, class_name)
                if not isinstance(t, BoolType):
                    self._err(f"Logical operand must be bool, got {t}")
            return BoolType()

        if isinstance(node, ast.BinOp):
            t1 = self._check_expr(node.left, scope, class_name)
            t2 = self._check_expr(node.right, scope, class_name)
            if isinstance(node.op, ast.Add):
                if isinstance(t1, IntType) and isinstance(t2, IntType): return IntType()
                if isinstance(t1, StrType) and isinstance(t2, StrType): return StrType()
                if isinstance(t1, ListType) and isinstance(t2, ListType):
                    return ListType(self.join(t1.elem, t2.elem))
                self._err(f"Cannot apply '+' to {t1} and {t2}")
                return ObjectType()
            if isinstance(node.op, (ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
                if not isinstance(t1, IntType) or not isinstance(t2, IntType):
                    self._err(f"Arithmetic operands must be int, got {t1} and {t2}")
                return IntType()
            return ObjectType()

        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                self._err("Chained comparisons not allowed")
                return BoolType()
            t1 = self._check_expr(node.left, scope, class_name)
            t2 = self._check_expr(node.comparators[0], scope, class_name)
            op = node.ops[0]
            if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                if not isinstance(t1, IntType) or not isinstance(t2, IntType):
                    self._err("Comparison operands must be int")
                return BoolType()
            if isinstance(op, (ast.Eq, ast.NotEq)):
                ok = ((isinstance(t1, IntType) and isinstance(t2, IntType)) or
                      (isinstance(t1, BoolType) and isinstance(t2, BoolType)) or
                      (isinstance(t1, StrType) and isinstance(t2, StrType)))
                if not ok:
                    self._err(f"Cannot compare {t1} and {t2} with ==/!=")
                return BoolType()
            if isinstance(op, ast.Is):
                if self._is_primitive(t1) or self._is_primitive(t2):
                    self._err(f"Cannot use 'is' with {t1} and {t2}")
                return BoolType()
            return BoolType()

        if isinstance(node, ast.IfExp):
            ct = self._check_expr(node.test, scope, class_name)
            if not isinstance(ct, BoolType):
                self._err(f"Condition must be bool, got {ct}")
            t1 = self._check_expr(node.body, scope, class_name)
            t2 = self._check_expr(node.orelse, scope, class_name)
            return self.join(t1, t2)

        if isinstance(node, ast.Call):
            return self._check_call(node, scope, class_name)

        if isinstance(node, ast.Attribute):
            obj_t = self._check_expr(node.value, scope, class_name)
            cn = self._class_name(obj_t)
            if cn is None:
                self._err(f"Cannot access attribute on {obj_t}")
                return ObjectType()
            if cn not in self.classes:
                self._err(f"Unknown class {cn}")
                return ObjectType()
            aa = self._all_attrs(cn)
            if node.attr in aa:
                return aa[node.attr]
            am = self._all_methods(cn)
            if node.attr in am:
                self._err("Cannot reference method without calling it")
                return ObjectType()
            self._err(f"'{cn}' has no attribute '{node.attr}'")
            return ObjectType()

        if isinstance(node, ast.Subscript):
            obj_t = self._check_expr(node.value, scope, class_name)
            idx_t = self._check_expr(node.slice, scope, class_name)
            if not isinstance(idx_t, IntType):
                self._err(f"Index must be int, got {idx_t}")
            if isinstance(obj_t, StrType): return StrType()
            if isinstance(obj_t, ListType): return obj_t.elem
            self._err(f"Cannot index {obj_t}")
            return ObjectType()

        if isinstance(node, ast.List):
            if len(node.elts) == 0:
                return EmptyType()
            types = [self._check_expr(e, scope, class_name) for e in node.elts]
            result = types[0]
            for t in types[1:]:
                result = self.join(result, t)
            return ListType(result)

        self._err(f"Unsupported expression: {type(node).__name__}")
        return ObjectType()

    def _check_call(self, node: ast.Call, scope: Scope,
                    class_name: Optional[str]) -> CType:
        if isinstance(node.func, ast.Name):
            name = node.func.id
            # Constructor call
            if name in self.classes:
                all_m = self._all_methods(name)
                init_m = all_m.get("__init__")
                if init_m:
                    expected = len(init_m.params) - 1
                    actual = len(node.args)
                    if actual != expected:
                        self._err(f"Expected {expected} arguments for {name}(), got {actual}")
                    for i, arg in enumerate(node.args):
                        at = self._check_expr(arg, scope, class_name)
                        if i + 1 < len(init_m.params):
                            if not self.assign_compat(at, init_m.params[i + 1]):
                                self._err(f"Argument type mismatch in {name}()")
                if name == "int": return IntType()
                if name == "bool": return BoolType()
                if name == "str": return StrType()
                return ClassType(name)

            # Regular function call
            ft = scope.lookup(name)
            if ft is None:
                self._err(f"Undefined function '{name}'")
                return ObjectType()
            if not isinstance(ft, FuncType):
                self._err(f"'{name}' is not callable")
                return ObjectType()
            expected = len(ft.params)
            actual = len(node.args)
            if actual != expected:
                self._err(f"Expected {expected} arguments for {name}(), got {actual}")
                return ft.ret
            for i, arg in enumerate(node.args):
                at = self._check_expr(arg, scope, class_name)
                if not self.assign_compat(at, ft.params[i]):
                    self._err(f"Argument type mismatch in call to {name}()")
            return ft.ret

        if isinstance(node.func, ast.Attribute):
            obj_t = self._check_expr(node.func.value, scope, class_name)
            mname = node.func.attr
            cn = self._class_name(obj_t)
            if cn is None:
                self._err(f"Cannot call method on {obj_t}")
                return ObjectType()
            if cn not in self.classes:
                self._err(f"Unknown class {cn}")
                return ObjectType()
            am = self._all_methods(cn)
            if mname not in am:
                self._err(f"'{cn}' has no method '{mname}'")
                return ObjectType()
            mt = am[mname]
            expected = len(mt.params) - 1
            actual = len(node.args)
            if actual != expected:
                self._err(f"Expected {expected} args for {cn}.{mname}(), got {actual}")
                return mt.ret
            if not self.assign_compat(obj_t, mt.params[0]):
                self._err("Self type mismatch")
            for i, arg in enumerate(node.args):
                at = self._check_expr(arg, scope, class_name)
                if not self.assign_compat(at, mt.params[i + 1]):
                    self._err(f"Arg type mismatch in {cn}.{mname}()")
            return mt.ret

        self._err("Unsupported call expression")
        return ObjectType()

    # ----------------------------------------------------------
    # JSON result builder
    # ----------------------------------------------------------

    def _build_result(self) -> dict:
        result = {
            "well_typed": len(self.errors) == 0,
            "globals": {},
            "classes": {},
            "errors": [{"message": e} for e in self.errors]
        }
        builtins = {"print", "input", "len"}
        for name, typ in self.global_scope.bindings.items():
            if name in builtins:
                continue
            kind = "func" if isinstance(typ, FuncType) else "var"
            result["globals"][name] = {"type": str(typ), "kind": kind}
        builtin_classes = {"object", "int", "bool", "str"}
        for name, ci in self.classes.items():
            if name in builtin_classes:
                continue
            cls_data = {
                "superclass": ci.superclass or "object",
                "attributes": {k: str(v) for k, v in ci.attrs.items()},
                "methods": {}
            }
            for mname, mtype in ci.methods.items():
                cls_data["methods"][mname] = str(mtype)
            result["classes"][name] = cls_data
        return result

    # ----------------------------------------------------------
    # Main entry
    # ----------------------------------------------------------

    def check(self, source: str) -> dict:
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self.errors = [f"Syntax error: {e}"]
            self.global_scope = Scope()
            return self._build_result()

        self.errors = []
        self.classes = {}
        self._init_builtins()

        self.global_scope = Scope()
        self.global_scope.define("print", FuncType((ObjectType(),), NoneType_(), ("arg",)))
        self.global_scope.define("input", FuncType((), StrType(), ()))
        self.global_scope.define("len", FuncType((ObjectType(),), IntType(), ("arg",)))

        self._collect_classes(tree)
        if not self.errors:
            self._collect_globals(tree, self.global_scope)
        if not self.errors:
            self._check_program(tree, self.global_scope)

        return self._build_result()


def type_check(source: str) -> dict:
    tc = TypeChecker()
    return tc.check(source)
