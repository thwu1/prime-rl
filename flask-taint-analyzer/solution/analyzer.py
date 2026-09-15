#!/usr/bin/env python3
"""
Static taint analyzer for Flask web applications.
Detects CWE-078, CWE-079, CWE-089, CWE-022, CWE-918 via AST-based
source-to-sink dataflow tracking with sanitizer recognition and
basic interprocedural analysis.
"""

import ast
import sys
import json


class FlaskTaintAnalyzer:
    def __init__(self, source):
        self.tree = ast.parse(source)
        self.funcs = {}            # name -> FunctionDef
        self.class_methods = {}    # "Class.method" -> FunctionDef
        self.classes = {}          # name -> ClassDef
        self.instance_types = {}   # var_name -> class_name
        self.import_aliases = {}   # alias -> real_module_name
        self.findings = []

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    def run(self):
        self._collect_defs()
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.FunctionDef) and self._is_route(node):
                self._analyze_route(node)
        return {"findings": self.findings}

    # ------------------------------------------------------------------
    # Phase 1: collect definitions
    # ------------------------------------------------------------------

    def _collect_defs(self):
        for node in ast.iter_child_nodes(self.tree):
            if isinstance(node, ast.FunctionDef):
                self.funcs[node.name] = node
            elif isinstance(node, ast.ClassDef):
                self.classes[node.name] = node
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        self.class_methods[f"{node.name}.{item.name}"] = item
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Name)
                            and isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Name)
                            and node.value.func.id in self.classes):
                        self.instance_types[t.id] = node.value.func.id
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self._track_import(node)

    def _track_import(self, node):
        if isinstance(node, ast.Import):
            for alias in node.names:
                self.import_aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                self.import_aliases[alias.asname or alias.name] = alias.name

    # ------------------------------------------------------------------
    # Route detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_route(func):
        for d in getattr(func, "decorator_list", []):
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                if d.func.attr == "route":
                    return True
        return False

    # ------------------------------------------------------------------
    # Phase 2: analyse a single route function
    # ------------------------------------------------------------------

    def _analyze_route(self, func):
        ctx = {"tainted": set(), "sanitized": False}
        self._trace_block(func.body, ctx, func.name)

    def _trace_block(self, stmts, ctx, route):
        for stmt in stmts:
            self._trace_stmt(stmt, ctx, route)

    def _trace_stmt(self, stmt, ctx, route):
        t = ctx["tainted"]

        # --- assignments: propagate taint ---
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    if self._is_source(stmt.value):
                        t.add(target.id)
                    elif self._expr_tainted(stmt.value, t):
                        t.add(target.id)
            # also check sinks inside the RHS expression
            if not ctx["sanitized"]:
                self._check_expr_sinks(stmt.value, t, route)
            return

        # --- if-statements: detect validation guards ---
        if isinstance(stmt, ast.If):
            if self._is_validation(stmt, t):
                ctx["sanitized"] = True
            self._trace_block(stmt.body, ctx, route)
            self._trace_block(stmt.orelse, ctx, route)
            return

        # --- with-statements: check context_expr + recurse body ---
        if isinstance(stmt, ast.With):
            if not ctx["sanitized"]:
                for item in stmt.items:
                    self._check_expr_sinks(item.context_expr, t, route)
            self._trace_block(stmt.body, ctx, route)
            return

        # --- expression statements ---
        if isinstance(stmt, ast.Expr):
            if not ctx["sanitized"]:
                self._check_expr_sinks(stmt.value, t, route)
            return

        # --- return statements ---
        if isinstance(stmt, ast.Return) and stmt.value:
            if not ctx["sanitized"]:
                self._check_expr_sinks(stmt.value, t, route)
            return

    # ------------------------------------------------------------------
    # Taint source detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_source(node):
        """request.args.get / request.form.get / etc."""
        if not isinstance(node, ast.Call):
            return False
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "get":
            v = f.value
            if isinstance(v, ast.Attribute) and v.attr in (
                "args", "form", "values", "json", "data", "cookies",
            ):
                if isinstance(v.value, ast.Name) and v.value.id == "request":
                    return True
        return False

    # ------------------------------------------------------------------
    # Taint propagation through expressions
    # ------------------------------------------------------------------

    def _expr_tainted(self, node, tainted):
        if isinstance(node, ast.Name):
            return node.id in tainted
        if isinstance(node, ast.BinOp):
            return (self._expr_tainted(node.left, tainted)
                    or self._expr_tainted(node.right, tainted))
        if isinstance(node, ast.JoinedStr):
            return any(
                isinstance(v, ast.FormattedValue)
                and self._expr_tainted(v.value, tainted)
                for v in node.values
            )
        if isinstance(node, ast.Call):
            if self._is_source(node):
                return True
            return any(self._expr_tainted(a, tainted) for a in node.args)
        if isinstance(node, ast.Subscript):
            return self._expr_tainted(node.value, tainted)
        if isinstance(node, ast.Attribute):
            return self._expr_tainted(node.value, tainted)
        return False

    # ------------------------------------------------------------------
    # Sink checking — walk an expression tree looking for dangerous calls
    # ------------------------------------------------------------------

    def _check_expr_sinks(self, expr, tainted, route):
        for node in ast.walk(expr):
            if isinstance(node, ast.Call):
                self._check_sink(node, tainted, route)
                self._check_interproc(node, tainted, route)

    def _check_sink(self, call, tainted, route):
        f = call.func

        # SQL injection: *.execute(tainted_query, ...)
        if isinstance(f, ast.Attribute) and f.attr == "execute":
            if call.args and self._expr_tainted(call.args[0], tainted):
                self._add(route, "CWE-089", "sql_injection")

        # Command injection: os.popen / os.system
        if isinstance(f, ast.Attribute) and f.attr in ("popen", "system"):
            if isinstance(f.value, ast.Name) and f.value.id == "os":
                if call.args and self._expr_tainted(call.args[0], tainted):
                    self._add(route, "CWE-078", "command_injection")

        # Command injection: subprocess.{call,run,...}(cmd, shell=True)
        if isinstance(f, ast.Attribute) and f.attr in (
            "call", "run", "Popen", "check_call", "check_output",
        ):
            if isinstance(f.value, ast.Name) and f.value.id == "subprocess":
                if call.args and self._expr_tainted(call.args[0], tainted):
                    has_shell = any(
                        kw.arg == "shell"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True
                        for kw in call.keywords
                    )
                    if has_shell:
                        self._add(route, "CWE-078", "command_injection")

        # Path traversal: open(tainted_path)
        if isinstance(f, ast.Name) and f.id == "open":
            if call.args and self._expr_tainted(call.args[0], tainted):
                self._add(route, "CWE-022", "path_traversal")

        # XSS: render_template_string(tainted)
        if isinstance(f, ast.Name) and f.id == "render_template_string":
            if call.args and self._expr_tainted(call.args[0], tainted):
                self._add(route, "CWE-079", "xss")

        # SSRF: requests.get(tainted) / alias.get(tainted)
        if isinstance(f, ast.Attribute) and f.attr in (
            "get", "post", "put", "delete", "head", "patch", "request",
        ):
            if isinstance(f.value, ast.Name):
                resolved = self.import_aliases.get(f.value.id, f.value.id)
                if resolved == "requests":
                    if call.args and self._expr_tainted(call.args[0], tainted):
                        self._add(route, "CWE-918", "ssrf")

    # ------------------------------------------------------------------
    # Interprocedural: trace into called helpers / class methods
    # ------------------------------------------------------------------

    def _check_interproc(self, call, tainted, route):
        f = call.func
        target = None
        param_offset = 0

        if isinstance(f, ast.Name) and f.id in self.funcs:
            target = self.funcs[f.id]
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            inst = f.value.id
            if inst in self.instance_types:
                cls = self.instance_types[inst]
                key = f"{cls}.{f.attr}"
                if key in self.class_methods:
                    target = self.class_methods[key]
                    param_offset = 1  # skip self

        if target is None:
            return

        for i, arg in enumerate(call.args):
            if self._expr_tainted(arg, tainted):
                pidx = i + param_offset
                params = target.args.args
                if pidx < len(params):
                    pname = params[pidx].arg
                    inner = {pname}
                    self._trace_inner(target.body, inner, route)

    def _trace_inner(self, stmts, tainted, route):
        for stmt in stmts:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name):
                        if self._expr_tainted(stmt.value, tainted):
                            tainted.add(t.id)
                self._check_expr_sinks(stmt.value, tainted, route)
            elif isinstance(stmt, ast.With):
                for item in stmt.items:
                    self._check_expr_sinks(item.context_expr, tainted, route)
                self._trace_inner(stmt.body, tainted, route)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                self._check_expr_sinks(stmt.value, tainted, route)
            elif isinstance(stmt, ast.Return) and stmt.value:
                self._check_expr_sinks(stmt.value, tainted, route)

    # ------------------------------------------------------------------
    # Sanitizer / validation detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_validation(if_stmt, tainted):
        """Detect input-validation guards with early return."""
        has_return = any(isinstance(s, ast.Return) for s in if_stmt.body)
        if not has_return:
            return False
        for node in ast.walk(if_stmt.test):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("isalnum", "isdigit", "isalpha", "startswith"):
                    return True
            if isinstance(node, ast.Name) and node.id == "all":
                return True
        return False

    # ------------------------------------------------------------------
    # Finding management
    # ------------------------------------------------------------------

    def _add(self, func_name, cwe, sink_type):
        entry = {"cwe": cwe, "function": func_name, "sink_type": sink_type}
        if entry not in self.findings:
            self.findings.append(entry)


# ======================================================================
# CLI
# ======================================================================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.py> <output.json>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    analyzer = FlaskTaintAnalyzer(source)
    result = analyzer.run()
    with open(sys.argv[2], "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
