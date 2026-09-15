"""
Cool language type checker (semantic analyzer).
Reads dict-based ASTs produced by cool_parser.py and performs full type checking.
"""


class TypeChecker:
    def __init__(self):
        self.classes = {}      # name -> class info dict
        self.errors = []
        self.current_class = None
        self.scopes = []       # stack of {name: type} dicts

    # ---- Error reporting ----

    def error(self, msg, line=0):
        self.errors.append({"message": msg, "line": line})

    # ---- Scope management ----

    def push_scope(self):
        self.scopes.append({})

    def pop_scope(self):
        self.scopes.pop()

    def add_binding(self, name, type_):
        self.scopes[-1][name] = type_

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    # ---- Built-in classes ----

    def install_basic_classes(self):
        self.classes['Object'] = {
            'parent': None,
            'methods': {
                'abort': {'formals': [], 'return_type': 'Object'},
                'type_name': {'formals': [], 'return_type': 'String'},
                'copy': {'formals': [], 'return_type': 'SELF_TYPE'},
            },
            'attrs': {},
            'line': 0,
            'builtin': True,
        }
        self.classes['IO'] = {
            'parent': 'Object',
            'methods': {
                'out_string': {'formals': [('x', 'String')], 'return_type': 'SELF_TYPE'},
                'out_int': {'formals': [('x', 'Int')], 'return_type': 'SELF_TYPE'},
                'in_string': {'formals': [], 'return_type': 'String'},
                'in_int': {'formals': [], 'return_type': 'Int'},
            },
            'attrs': {},
            'line': 0,
            'builtin': True,
        }
        self.classes['Int'] = {
            'parent': 'Object',
            'methods': {},
            'attrs': {},
            'line': 0,
            'builtin': True,
        }
        self.classes['String'] = {
            'parent': 'Object',
            'methods': {
                'length': {'formals': [], 'return_type': 'Int'},
                'concat': {'formals': [('s', 'String')], 'return_type': 'String'},
                'substr': {'formals': [('i', 'Int'), ('l', 'Int')], 'return_type': 'String'},
            },
            'attrs': {},
            'line': 0,
            'builtin': True,
        }
        self.classes['Bool'] = {
            'parent': 'Object',
            'methods': {},
            'attrs': {},
            'line': 0,
            'builtin': True,
        }

    # ---- Class collection ----

    def collect_classes(self, program):
        for cls in program['classes']:
            name = cls['name']
            if name in ('Object', 'IO', 'Int', 'String', 'Bool', 'SELF_TYPE'):
                self.error(f"Cannot redefine basic class {name}", cls.get('line', 0))
                continue
            if name in self.classes:
                self.error(f"Class {name} already defined", cls.get('line', 0))
                continue

            parent = cls.get('parent') or 'Object'
            methods = {}
            attrs = {}
            for feature in cls.get('features', []):
                if feature['kind'] == 'method':
                    methods[feature['name']] = {
                        'formals': [(f['name'], f['type']) for f in feature.get('formals', [])],
                        'return_type': feature['return_type'],
                        'body': feature.get('body'),
                        'line': feature.get('line', 0),
                    }
                elif feature['kind'] == 'attr':
                    if feature['name'] == 'self':
                        self.error("Cannot have attribute named self", feature.get('line', 0))
                        continue
                    attrs[feature['name']] = {
                        'type_decl': feature['type_decl'],
                        'init': feature.get('init'),
                        'line': feature.get('line', 0),
                    }

            self.classes[name] = {
                'parent': parent,
                'methods': methods,
                'attrs': attrs,
                'line': cls.get('line', 0),
                'builtin': False,
            }

    # ---- Hierarchy validation ----

    def check_hierarchy(self):
        for name, info in self.classes.items():
            if info['builtin'] or info['parent'] is None:
                continue
            if info['parent'] not in self.classes:
                self.error(
                    f"Class {name} inherits from undefined class {info['parent']}",
                    info['line']
                )
            elif info['parent'] in ('Int', 'String', 'Bool'):
                self.error(
                    f"Class {name} cannot inherit from {info['parent']}",
                    info['line']
                )

        # Cycle detection
        for name in list(self.classes.keys()):
            info = self.classes[name]
            if info['builtin'] or info['parent'] is None:
                continue
            visited = set()
            current = name
            while current is not None:
                if current in visited:
                    self.error(
                        f"Inheritance cycle involving {name}",
                        self.classes[name]['line']
                    )
                    break
                visited.add(current)
                parent = self.classes.get(current, {}).get('parent')
                if parent and parent not in self.classes:
                    break
                current = parent

    # ---- Main class check ----

    def check_main(self):
        if 'Main' not in self.classes:
            self.error("No Main class defined")
            return
        all_methods = self.get_all_methods('Main')
        if 'main' not in all_methods:
            self.error("Main class must have a main() method",
                       self.classes['Main']['line'])
            return
        main_method = all_methods['main']
        if len(main_method['formals']) > 0:
            self.error("Main.main() must take no arguments",
                       self.classes['Main']['line'])

    # ---- Ancestor / method / attr helpers ----

    def get_ancestors(self, type_name):
        if type_name == 'SELF_TYPE':
            type_name = self.current_class
        ancestors = []
        current = type_name
        visited = set()
        while current is not None:
            if current in visited:
                break
            visited.add(current)
            ancestors.append(current)
            current = self.classes.get(current, {}).get('parent')
        return ancestors

    def get_all_methods(self, class_name):
        methods = {}
        for ancestor in reversed(self.get_ancestors(class_name)):
            if ancestor in self.classes:
                methods.update(self.classes[ancestor]['methods'])
        return methods

    def get_all_attrs(self, class_name):
        attrs = {}
        for ancestor in reversed(self.get_ancestors(class_name)):
            if ancestor in self.classes:
                attrs.update(self.classes[ancestor]['attrs'])
        return attrs

    def find_method(self, class_name, method_name):
        return self.get_all_methods(class_name).get(method_name)

    # ---- Conformance and LUB ----

    def conforms(self, t1, t2):
        if t1 == t2:
            return True
        if t2 == 'SELF_TYPE':
            return False
        actual_t1 = self.current_class if t1 == 'SELF_TYPE' else t1
        return t2 in self.get_ancestors(actual_t1)

    def lub(self, t1, t2):
        a1 = t1 if t1 != 'SELF_TYPE' else self.current_class
        a2 = t2 if t2 != 'SELF_TYPE' else self.current_class
        ancestors2 = set(self.get_ancestors(a2))
        for a in self.get_ancestors(a1):
            if a in ancestors2:
                return a
        return 'Object'

    def resolve_self_type(self, t):
        return self.current_class if t == 'SELF_TYPE' else t

    # ---- Override and attribute redefinition checks ----

    def check_overrides(self):
        for name, info in self.classes.items():
            if info['builtin'] or info['parent'] is None:
                continue
            parent = info['parent']
            if parent not in self.classes:
                continue
            parent_methods = self.get_all_methods(parent)
            for method_name, method in info['methods'].items():
                if method_name in parent_methods:
                    pm = parent_methods[method_name]
                    if len(method['formals']) != len(pm['formals']):
                        self.error(
                            f"Method {method_name} in {name} has different number "
                            f"of parameters than in parent",
                            method['line']
                        )
                        continue
                    for i, ((_, t1), (_, t2)) in enumerate(
                            zip(method['formals'], pm['formals'])):
                        if t1 != t2:
                            self.error(
                                f"Method {method_name} in {name}: parameter {i+1} "
                                f"has type {t1}, expected {t2}",
                                method['line']
                            )
                    if method['return_type'] != pm['return_type']:
                        self.error(
                            f"Method {method_name} in {name}: return type "
                            f"{method['return_type']} differs from parent's "
                            f"{pm['return_type']}",
                            method['line']
                        )

    def check_attr_redefinition(self):
        for name, info in self.classes.items():
            if info['builtin'] or info['parent'] is None:
                continue
            parent = info['parent']
            if parent not in self.classes:
                continue
            parent_attrs = self.get_all_attrs(parent)
            for attr_name in info['attrs']:
                if attr_name in parent_attrs:
                    self.error(
                        f"Attribute {attr_name} is redefined in class {name}",
                        info['attrs'][attr_name]['line']
                    )

    # ---- Class topological order ----

    def class_order(self):
        order = []
        visited = set()

        def visit(name):
            if name in visited:
                return
            visited.add(name)
            parent = self.classes.get(name, {}).get('parent')
            if parent and parent in self.classes:
                visit(parent)
            order.append(name)

        for name in self.classes:
            visit(name)
        return order

    # ---- Type checking per class ----

    def type_check_class(self, class_name):
        info = self.classes[class_name]
        if info['builtin']:
            return

        self.current_class = class_name
        self.push_scope()
        self.add_binding('self', 'SELF_TYPE')

        # Add all attributes to scope
        all_attrs = self.get_all_attrs(class_name)
        for attr_name, attr in all_attrs.items():
            self.add_binding(attr_name, attr['type_decl'])

        # Validate attribute declared types
        for attr_name, attr in info['attrs'].items():
            tdecl = attr['type_decl']
            if tdecl != 'SELF_TYPE' and tdecl not in self.classes:
                self.error(
                    f"Attribute {attr_name} has undefined type {tdecl}",
                    attr['line']
                )

        # Validate method signatures
        for method_name, method in info['methods'].items():
            rt = method['return_type']
            if rt != 'SELF_TYPE' and rt not in self.classes:
                self.error(
                    f"Method {method_name} has undefined return type {rt}",
                    method['line']
                )
            for formal_name, formal_type in method['formals']:
                if formal_type == 'SELF_TYPE':
                    self.error(
                        f"Formal parameter {formal_name} cannot have type SELF_TYPE",
                        method['line']
                    )
                elif formal_type not in self.classes:
                    self.error(
                        f"Formal parameter {formal_name} has undefined type {formal_type}",
                        method['line']
                    )

        # Type check attribute initializers
        for attr_name, attr in info['attrs'].items():
            if attr['init'] is not None:
                init_type = self.infer_type(attr['init'])
                if not self.conforms(init_type, attr['type_decl']):
                    self.error(
                        f"Attribute {attr_name} initializer has type {init_type}, "
                        f"expected {attr['type_decl']}",
                        attr['line']
                    )

        # Type check method bodies
        for method_name, method in info['methods'].items():
            self._type_check_method(method_name, method)

        self.pop_scope()

    def _type_check_method(self, method_name, method):
        self.push_scope()
        for formal_name, formal_type in method['formals']:
            if formal_name == 'self':
                self.error("Cannot use self as formal parameter name",
                           method['line'])
            self.add_binding(formal_name, formal_type)

        if method['body'] is not None:
            body_type = self.infer_type(method['body'])
            if not self.conforms(body_type, method['return_type']):
                self.error(
                    f"Method {method_name} body has type {body_type}, "
                    f"declared return type is {method['return_type']}",
                    method['line']
                )
        self.pop_scope()

    # ---- Expression type inference ----

    def infer_type(self, expr):
        if expr is None:
            return 'Object'

        kind = expr.get('kind')
        line = expr.get('line', 0)

        if kind == 'int_const':
            expr['static_type'] = 'Int'
            return 'Int'

        if kind == 'string_const':
            expr['static_type'] = 'String'
            return 'String'

        if kind == 'bool_const':
            expr['static_type'] = 'Bool'
            return 'Bool'

        if kind == 'self':
            expr['static_type'] = 'SELF_TYPE'
            return 'SELF_TYPE'

        if kind == 'identifier':
            name = expr['name']
            t = self.lookup(name)
            if t is None:
                self.error(f"Undeclared identifier {name}", line)
                expr['static_type'] = 'Object'
                return 'Object'
            expr['static_type'] = t
            return t

        if kind == 'assign':
            name = expr['name']
            if name == 'self':
                self.error("Cannot assign to self", line)
            rhs_type = self.infer_type(expr['expr'])
            if name != 'self':
                declared = self.lookup(name)
                if declared is not None and not self.conforms(rhs_type, declared):
                    self.error(
                        f"Type {rhs_type} does not conform to declared type "
                        f"{declared} in assignment to {name}",
                        line
                    )
            expr['static_type'] = rhs_type
            return rhs_type

        if kind == 'new':
            tname = expr['type_name']
            if tname != 'SELF_TYPE' and tname not in self.classes:
                self.error(f"Undefined type {tname} in new expression", line)
                expr['static_type'] = 'Object'
                return 'Object'
            expr['static_type'] = tname
            return tname

        if kind == 'dispatch':
            obj_type = self.infer_type(expr['object'])
            dispatch_type = self.resolve_self_type(obj_type)

            if dispatch_type not in self.classes:
                self.error(f"Dispatch on undefined type {dispatch_type}", line)
                for arg in expr.get('args', []):
                    self.infer_type(arg)
                expr['static_type'] = 'Object'
                return 'Object'

            method = self.find_method(dispatch_type, expr['method'])
            if method is None:
                self.error(
                    f"Method {expr['method']} not found in class {dispatch_type}",
                    line
                )
                for arg in expr.get('args', []):
                    self.infer_type(arg)
                expr['static_type'] = 'Object'
                return 'Object'

            self._check_args(method, expr.get('args', []), expr['method'], line)

            if method['return_type'] == 'SELF_TYPE':
                expr['static_type'] = obj_type
                return obj_type
            expr['static_type'] = method['return_type']
            return method['return_type']

        if kind == 'static_dispatch':
            obj_type = self.infer_type(expr['object'])
            dispatch_type = expr['type_name']

            if dispatch_type not in self.classes:
                self.error(
                    f"Static dispatch on undefined type {dispatch_type}", line
                )
                for arg in expr.get('args', []):
                    self.infer_type(arg)
                expr['static_type'] = 'Object'
                return 'Object'

            if not self.conforms(obj_type, dispatch_type):
                self.error(
                    f"Object type {obj_type} does not conform to static "
                    f"dispatch type {dispatch_type}",
                    line
                )

            method = self.find_method(dispatch_type, expr['method'])
            if method is None:
                self.error(
                    f"Method {expr['method']} not found in class {dispatch_type}",
                    line
                )
                for arg in expr.get('args', []):
                    self.infer_type(arg)
                expr['static_type'] = 'Object'
                return 'Object'

            self._check_args(method, expr.get('args', []), expr['method'], line)

            if method['return_type'] == 'SELF_TYPE':
                expr['static_type'] = obj_type
                return obj_type
            expr['static_type'] = method['return_type']
            return method['return_type']

        if kind == 'self_dispatch':
            method = self.find_method(self.current_class, expr['method'])
            if method is None:
                self.error(
                    f"Method {expr['method']} not found in class "
                    f"{self.current_class}",
                    line
                )
                for arg in expr.get('args', []):
                    self.infer_type(arg)
                expr['static_type'] = 'Object'
                return 'Object'

            self._check_args(method, expr.get('args', []), expr['method'], line)

            if method['return_type'] == 'SELF_TYPE':
                expr['static_type'] = 'SELF_TYPE'
                return 'SELF_TYPE'
            expr['static_type'] = method['return_type']
            return method['return_type']

        if kind == 'cond':
            pred_type = self.infer_type(expr['predicate'])
            if self.resolve_self_type(pred_type) != 'Bool':
                self.error("Predicate of if must have type Bool", line)
            then_type = self.infer_type(expr['then_expr'])
            else_type = self.infer_type(expr['else_expr'])
            result = self.lub(then_type, else_type)
            expr['static_type'] = result
            return result

        if kind == 'loop':
            pred_type = self.infer_type(expr['predicate'])
            if self.resolve_self_type(pred_type) != 'Bool':
                self.error("Predicate of while must have type Bool", line)
            self.infer_type(expr['body'])
            expr['static_type'] = 'Object'
            return 'Object'

        if kind == 'block':
            result_type = 'Object'
            for sub_expr in expr.get('body', []):
                result_type = self.infer_type(sub_expr)
            expr['static_type'] = result_type
            return result_type

        if kind == 'let':
            binding = expr['binding']
            bname = binding['name']
            btype = binding['type_decl']

            if bname == 'self':
                self.error("Cannot bind self in let", line)

            if btype != 'SELF_TYPE' and btype not in self.classes:
                self.error(f"Undefined type {btype} in let binding", line)

            if binding.get('init') is not None:
                init_type = self.infer_type(binding['init'])
                if not self.conforms(init_type, btype):
                    self.error(
                        f"Let binding init has type {init_type}, expected {btype}",
                        line
                    )

            self.push_scope()
            self.add_binding(bname, btype)
            body_type = self.infer_type(expr['body'])
            self.pop_scope()

            expr['static_type'] = body_type
            return body_type

        if kind == 'case':
            self.infer_type(expr['expr'])
            branch_types = []
            seen_types = set()

            for branch in expr.get('branches', []):
                bdecl = branch['type_decl']
                if bdecl in seen_types:
                    self.error(
                        f"Duplicate branch type {bdecl} in case", line
                    )
                seen_types.add(bdecl)

                if bdecl == 'SELF_TYPE':
                    self.error(
                        "SELF_TYPE not allowed as case branch type", line
                    )
                elif bdecl not in self.classes:
                    self.error(
                        f"Undefined type {bdecl} in case branch", line
                    )

                self.push_scope()
                self.add_binding(branch['name'], bdecl)
                bt = self.infer_type(branch['body'])
                branch_types.append(bt)
                self.pop_scope()

            if branch_types:
                result = branch_types[0]
                for t in branch_types[1:]:
                    result = self.lub(result, t)
                expr['static_type'] = result
                return result

            expr['static_type'] = 'Object'
            return 'Object'

        if kind == 'isvoid':
            self.infer_type(expr['expr'])
            expr['static_type'] = 'Bool'
            return 'Bool'

        if kind in ('plus', 'sub', 'mul', 'div'):
            left_type = self.infer_type(expr['left'])
            right_type = self.infer_type(expr['right'])
            if self.resolve_self_type(left_type) != 'Int':
                self.error(
                    f"Left operand of {kind} must be Int, got {left_type}", line
                )
            if self.resolve_self_type(right_type) != 'Int':
                self.error(
                    f"Right operand of {kind} must be Int, got {right_type}", line
                )
            expr['static_type'] = 'Int'
            return 'Int'

        if kind == 'neg':
            sub_type = self.infer_type(expr['expr'])
            if self.resolve_self_type(sub_type) != 'Int':
                self.error(f"Operand of ~ must be Int, got {sub_type}", line)
            expr['static_type'] = 'Int'
            return 'Int'

        if kind in ('lt', 'le'):
            left_type = self.infer_type(expr['left'])
            right_type = self.infer_type(expr['right'])
            if self.resolve_self_type(left_type) != 'Int':
                self.error(
                    f"Left operand of comparison must be Int, got {left_type}",
                    line
                )
            if self.resolve_self_type(right_type) != 'Int':
                self.error(
                    f"Right operand of comparison must be Int, got {right_type}",
                    line
                )
            expr['static_type'] = 'Bool'
            return 'Bool'

        if kind == 'eq':
            left_type = self.infer_type(expr['left'])
            right_type = self.infer_type(expr['right'])
            basic = {'Int', 'String', 'Bool'}
            lt = self.resolve_self_type(left_type)
            rt = self.resolve_self_type(right_type)
            if lt in basic or rt in basic:
                if lt != rt:
                    self.error(
                        f"Cannot compare {left_type} and {right_type} with =",
                        line
                    )
            expr['static_type'] = 'Bool'
            return 'Bool'

        if kind == 'not':
            sub_type = self.infer_type(expr['expr'])
            if self.resolve_self_type(sub_type) != 'Bool':
                self.error(
                    f"Operand of not must be Bool, got {sub_type}", line
                )
            expr['static_type'] = 'Bool'
            return 'Bool'

        self.error(f"Unknown expression kind: {kind}", line)
        expr['static_type'] = 'Object'
        return 'Object'

    def _check_args(self, method, args, method_name, line):
        arg_types = [self.infer_type(arg) for arg in args]
        formals = method['formals']
        if len(arg_types) != len(formals):
            self.error(
                f"Method {method_name} expects {len(formals)} arguments, "
                f"got {len(arg_types)}",
                line
            )
        else:
            for i, (at, (_, ft)) in enumerate(zip(arg_types, formals)):
                if not self.conforms(at, ft):
                    self.error(
                        f"Argument {i+1} of method {method_name} has type "
                        f"{at}, expected {ft}",
                        line
                    )

    # ---- Main entry point ----

    def run(self, program_ast):
        self.install_basic_classes()
        self.collect_classes(program_ast)
        if self.errors:
            return {"status": "error", "errors": self.errors}

        self.check_hierarchy()
        if self.errors:
            return {"status": "error", "errors": self.errors}

        self.check_main()
        self.check_overrides()
        self.check_attr_redefinition()
        if self.errors:
            return {"status": "error", "errors": self.errors}

        for class_name in self.class_order():
            self.type_check_class(class_name)

        if self.errors:
            return {"status": "error", "errors": self.errors}

        return {"status": "ok", "annotated_ast": program_ast}


def check_program(program_ast):
    """Main entry point for type checking a Cool program AST."""
    tc = TypeChecker()
    return tc.run(program_ast)
