#!/usr/bin/env python3
"""
Lox-to-Python transpiler built on ANTLR4-generated parser.
Parses .lox source via ANTLR4, converts parse tree to Lox AST nodes,
then generates equivalent standalone Python 3 code.
"""

import sys
import os

sys.path.insert(0, "/app")

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from gen.LoxLexer import LoxLexer
from gen.LoxParser import LoxParser
from gen.LoxVisitor import LoxVisitor

from lox.tokens import Token, TokenType
from lox.ast_nodes import (
    Literal, Grouping, Unary, Binary, Variable, Assign, Logical, Call,
    Get, Set, This, Super, ExpressionStmt, PrintStmt, VarStmt, BlockStmt,
    IfStmt, WhileStmt, FunctionStmt, ReturnStmt, ClassStmt,
)


# ── ANTLR4 Error Listener ──────────────────────────────────────────────

class LoxErrorListener(ErrorListener):
    def __init__(self):
        super().__init__()
        self.has_error = False

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        print(f"[line {line}] Error: {msg}", file=sys.stderr)
        self.has_error = True


# ── AST Builder: ANTLR4 Parse Tree → Lox AST Nodes ─────────────────────

class ASTBuilder(LoxVisitor):
    """Converts ANTLR4 parse tree contexts into lox.ast_nodes objects."""

    def _tok(self, node, ttype):
        """Create a lox Token from an ANTLR4 terminal node."""
        if node is None:
            return Token(ttype, "", None, 0)
        text = node.getText() if hasattr(node, "getText") else str(node)
        line = node.symbol.line if hasattr(node, "symbol") else 0
        return Token(ttype, text, None, line)

    # ── Program / Declarations ──

    def visitProgram(self, ctx):
        stmts = []
        for d in ctx.declaration():
            r = self.visit(d)
            if r is not None:
                stmts.append(r)
        return stmts

    def visitDeclaration(self, ctx):
        return self.visit(ctx.getChild(0))

    def visitClassDecl(self, ctx):
        ids = ctx.IDENTIFIER()
        name = self._tok(ids[0], TokenType.IDENTIFIER)
        superclass = (
            Variable(self._tok(ids[1], TokenType.IDENTIFIER))
            if len(ids) > 1
            else None
        )
        methods = [self._build_function(f) for f in ctx.function()]
        return ClassStmt(name, superclass, methods)

    def visitFunDecl(self, ctx):
        return self._build_function(ctx.function())

    def _build_function(self, ctx):
        name = self._tok(ctx.IDENTIFIER(), TokenType.IDENTIFIER)
        params = []
        if ctx.parameters():
            params = [
                self._tok(i, TokenType.IDENTIFIER)
                for i in ctx.parameters().IDENTIFIER()
            ]
        body = self._block_stmts(ctx.block())
        return FunctionStmt(name, params, body)

    def _block_stmts(self, ctx):
        stmts = []
        for d in ctx.declaration():
            r = self.visit(d)
            if r is not None:
                stmts.append(r)
        return stmts

    def visitVarDecl(self, ctx):
        name = self._tok(ctx.IDENTIFIER(), TokenType.IDENTIFIER)
        init = self.visit(ctx.expression()) if ctx.expression() else None
        return VarStmt(name, init)

    # ── Statements ──

    def visitStatement(self, ctx):
        return self.visit(ctx.getChild(0))

    def visitExprStmt(self, ctx):
        return ExpressionStmt(self.visit(ctx.expression()))

    def visitPrintStmt(self, ctx):
        return PrintStmt(self.visit(ctx.expression()))

    def visitIfStmt(self, ctx):
        cond = self.visit(ctx.expression())
        then_br = self.visit(ctx.statement(0))
        else_br = (
            self.visit(ctx.statement(1)) if len(ctx.statement()) > 1 else None
        )
        return IfStmt(cond, then_br, else_br)

    def visitWhileStmt(self, ctx):
        return WhileStmt(
            self.visit(ctx.expression()), self.visit(ctx.statement())
        )

    def visitForStmt(self, ctx):
        init = self.visit(ctx.forInit())
        cond_ctx = ctx.forCond()
        cond = (
            self.visit(cond_ctx.expression())
            if cond_ctx.expression()
            else None
        )
        incr_ctx = ctx.forIncr()
        incr = (
            self.visit(incr_ctx.expression())
            if incr_ctx.expression()
            else None
        )
        body = self.visit(ctx.statement())

        # Desugar for-loop into while
        if incr is not None:
            body = BlockStmt([body, ExpressionStmt(incr)])
        if cond is None:
            cond = Literal(True)
        body = WhileStmt(cond, body)
        if init is not None:
            body = BlockStmt([init, body])
        return body

    def visitForInit(self, ctx):
        if ctx.varDecl():
            return self.visit(ctx.varDecl())
        if ctx.exprStmt():
            return self.visit(ctx.exprStmt())
        return None

    def visitForCond(self, ctx):
        return self.visitChildren(ctx)

    def visitForIncr(self, ctx):
        return self.visitChildren(ctx)

    def visitReturnStmt(self, ctx):
        kw = Token(TokenType.RETURN, "return", None, 0)
        val = self.visit(ctx.expression()) if ctx.expression() else None
        return ReturnStmt(kw, val)

    def visitBlock(self, ctx):
        return BlockStmt(self._block_stmts(ctx))

    # ── Expressions ──

    def visitExpression(self, ctx):
        return self.visit(ctx.assignment())

    def visitAssignment(self, ctx):
        if ctx.assignment():
            val = self.visit(ctx.assignment())
            target = self.visit(ctx.logic_or())
            if isinstance(target, Variable):
                return Assign(target.name, val)
            elif isinstance(target, Get):
                return Set(target.obj, target.name, val)
            return Assign(Token(TokenType.IDENTIFIER, "", None, 0), val)
        return self.visit(ctx.logic_or())

    def visitLogic_or(self, ctx):
        expr = self.visit(ctx.logic_and(0))
        for i in range(1, len(ctx.logic_and())):
            expr = Logical(
                expr,
                Token(TokenType.OR, "or", None, 0),
                self.visit(ctx.logic_and(i)),
            )
        return expr

    def visitLogic_and(self, ctx):
        expr = self.visit(ctx.equality(0))
        for i in range(1, len(ctx.equality())):
            expr = Logical(
                expr,
                Token(TokenType.AND, "and", None, 0),
                self.visit(ctx.equality(i)),
            )
        return expr

    def visitEquality(self, ctx):
        expr = self.visit(ctx.comparison(0))
        for i in range(1, len(ctx.comparison())):
            op_text = ctx.getChild(2 * i - 1).getText()
            ttype = (
                TokenType.BANG_EQUAL
                if op_text == "!="
                else TokenType.EQUAL_EQUAL
            )
            expr = Binary(
                expr,
                Token(ttype, op_text, None, 0),
                self.visit(ctx.comparison(i)),
            )
        return expr

    def visitComparison(self, ctx):
        expr = self.visit(ctx.term(0))
        tmap = {
            ">": TokenType.GREATER,
            ">=": TokenType.GREATER_EQUAL,
            "<": TokenType.LESS,
            "<=": TokenType.LESS_EQUAL,
        }
        for i in range(1, len(ctx.term())):
            op_text = ctx.getChild(2 * i - 1).getText()
            expr = Binary(
                expr,
                Token(tmap[op_text], op_text, None, 0),
                self.visit(ctx.term(i)),
            )
        return expr

    def visitTerm(self, ctx):
        expr = self.visit(ctx.factor(0))
        for i in range(1, len(ctx.factor())):
            op_text = ctx.getChild(2 * i - 1).getText()
            ttype = TokenType.PLUS if op_text == "+" else TokenType.MINUS
            expr = Binary(
                expr,
                Token(ttype, op_text, None, 0),
                self.visit(ctx.factor(i)),
            )
        return expr

    def visitFactor(self, ctx):
        expr = self.visit(ctx.unary(0))
        for i in range(1, len(ctx.unary())):
            op_text = ctx.getChild(2 * i - 1).getText()
            ttype = TokenType.STAR if op_text == "*" else TokenType.SLASH
            expr = Binary(
                expr,
                Token(ttype, op_text, None, 0),
                self.visit(ctx.unary(i)),
            )
        return expr

    def visitUnary(self, ctx):
        if ctx.unary():
            op_text = ctx.getChild(0).getText()
            ttype = TokenType.BANG if op_text == "!" else TokenType.MINUS
            return Unary(
                Token(ttype, op_text, None, 0), self.visit(ctx.unary())
            )
        return self.visit(ctx.call())

    def visitCall(self, ctx):
        expr = self.visit(ctx.primary())
        for child in ctx.children[1:]:
            if isinstance(child, LoxParser.FnCallContext):
                args = []
                if child.arguments():
                    args = [
                        self.visit(e) for e in child.arguments().expression()
                    ]
                paren = Token(TokenType.RIGHT_PAREN, ")", None, 0)
                expr = Call(expr, paren, args)
            elif isinstance(child, LoxParser.PropAccessContext):
                expr = Get(
                    expr,
                    self._tok(child.IDENTIFIER(), TokenType.IDENTIFIER),
                )
        return expr

    # ── Primary (labeled alternatives) ──

    def visitTrueExpr(self, ctx):
        return Literal(True)

    def visitFalseExpr(self, ctx):
        return Literal(False)

    def visitNilExpr(self, ctx):
        return Literal(None)

    def visitThisExpr(self, ctx):
        return This(Token(TokenType.THIS, "this", None, 0))

    def visitNumberExpr(self, ctx):
        return Literal(float(ctx.NUMBER().getText()))

    def visitStringExpr(self, ctx):
        raw = ctx.STRING().getText()
        return Literal(raw[1:-1])  # strip surrounding quotes

    def visitIdentifierExpr(self, ctx):
        return Variable(self._tok(ctx.IDENTIFIER(), TokenType.IDENTIFIER))

    def visitGroupExpr(self, ctx):
        return Grouping(self.visit(ctx.expression()))

    def visitSuperExpr(self, ctx):
        return Super(
            Token(TokenType.SUPER, "super", None, 0),
            self._tok(ctx.IDENTIFIER(), TokenType.IDENTIFIER),
        )


# ── Runtime Preamble ────────────────────────────────────────────────────

RUNTIME_PREAMBLE = '''import time as _time
import sys as _sys

class _Env:
    __slots__ = ('_v', '_p')
    def __init__(self, p=None):
        self._v = {}
        self._p = p
    def define(self, n, v):
        self._v[n] = v
    def get(self, n):
        e = self
        while e is not None:
            if n in e._v:
                return e._v[n]
            e = e._p
        raise RuntimeError(f"Undefined variable \\'{n}\\'.")
    def assign(self, n, v):
        e = self
        while e is not None:
            if n in e._v:
                e._v[n] = v
                return v
            e = e._p
        raise RuntimeError(f"Undefined variable \\'{n}\\'.")
    def child(self):
        return _Env(self)

class _Return(Exception):
    __slots__ = ('v',)
    def __init__(self, v):
        self.v = v

def _truthy(v):
    return v is not None and v is not False

def _stringify(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    return str(v)

def _lox_print(v):
    print(_stringify(v))

def _lox_add(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return a + b
    if isinstance(a, str) and isinstance(b, str):
        return a + b
    raise RuntimeError("Operands must be two numbers or two strings.")

def _lox_sub(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a - b

def _lox_mul(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a * b

def _lox_div(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a / b

def _lox_neg(a):
    if not isinstance(a, float):
        raise RuntimeError("Operand must be a number.")
    return -a

def _lox_gt(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a > b

def _lox_gte(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a >= b

def _lox_lt(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a < b

def _lox_lte(a, b):
    if not isinstance(a, float) or not isinstance(b, float):
        raise RuntimeError("Operands must be numbers.")
    return a <= b

def _lox_eq(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if type(a) != type(b):
        return False
    return a == b

def _lox_or(lf, rf):
    l = lf()
    return l if _truthy(l) else rf()

def _lox_and(lf, rf):
    l = lf()
    return rf() if _truthy(l) else l

def _lox_call(callee, args):
    if not hasattr(callee, 'arity'):
        raise RuntimeError("Can only call functions and classes.")
    if callee.arity != len(args):
        raise RuntimeError(f"Expected {callee.arity} arguments but got {len(args)}.")
    return callee(*args)

def _lox_get(obj, name):
    if isinstance(obj, _LoxInstance):
        return obj.get(name)
    raise RuntimeError("Only instances have properties.")

def _lox_set(obj, name, val):
    if not isinstance(obj, _LoxInstance):
        raise RuntimeError("Only instances have fields.")
    obj.set(name, val)
    return val

def _lox_super(env, method_name):
    sup = env.get("super")
    this = env.get("this")
    m = sup.find_method(method_name)
    if m is None:
        raise RuntimeError(f"Undefined property \\'{method_name}\\'.")
    return m.bind(this)

class _LoxFn:
    __slots__ = ('name', 'params', 'closure', 'body', 'is_init', 'arity')
    def __init__(self, name, params, closure, body, is_init=False):
        self.name = name
        self.params = params
        self.closure = closure
        self.body = body
        self.is_init = is_init
        self.arity = len(params)
    def __call__(self, *args):
        env = self.closure.child()
        for i, p in enumerate(self.params):
            env.define(p, args[i])
        try:
            self.body(env)
        except _Return as r:
            if self.is_init:
                return self.closure.get("this")
            return r.v
        if self.is_init:
            return self.closure.get("this")
        return None
    def bind(self, instance):
        env = self.closure.child()
        env.define("this", instance)
        return _LoxFn(self.name, self.params, env, self.body, self.is_init)
    def __str__(self):
        return f"<fn {self.name}>"

class _LoxClass:
    __slots__ = ('name', 'superclass', 'methods', 'arity')
    def __init__(self, name, superclass, methods):
        self.name = name
        self.superclass = superclass
        self.methods = methods
        init = self.find_method("init")
        self.arity = init.arity if init else 0
    def find_method(self, name):
        if name in self.methods:
            return self.methods[name]
        if self.superclass is not None:
            return self.superclass.find_method(name)
        return None
    def __call__(self, *args):
        inst = _LoxInstance(self)
        init = self.find_method("init")
        if init is not None:
            init.bind(inst)(*args)
        return inst
    def __str__(self):
        return self.name

class _LoxInstance:
    __slots__ = ('klass', 'fields')
    def __init__(self, klass):
        self.klass = klass
        self.fields = {}
    def get(self, name):
        if name in self.fields:
            return self.fields[name]
        m = self.klass.find_method(name)
        if m is not None:
            return m.bind(self)
        raise RuntimeError(f"Undefined property \\'{name}\\'.")
    def set(self, name, value):
        self.fields[name] = value
    def __str__(self):
        return f"{self.klass.name} instance"

class _ClockFn:
    arity = 0
    def __call__(self):
        return float(_time.time())
    def __str__(self):
        return "<native fn>"

_e = _Env()
_e.define("clock", _ClockFn())
'''


# ── Transpiler: AST → Python Code ──────────────────────────────────────

class Transpiler:
    def __init__(self):
        self.lines = []
        self.indent = 0
        self.uid = 0

    def fresh(self, prefix="_t"):
        self.uid += 1
        return f"{prefix}{self.uid}"

    def emit(self, line=""):
        if line:
            self.lines.append("    " * self.indent + line)
        else:
            self.lines.append("")

    def transpile_stmts(self, stmts):
        """Generate Python from pre-parsed AST statements."""
        self.lines.append(RUNTIME_PREAMBLE)
        self.emit("try:")
        self.indent += 1
        self.gen_stmts(stmts)
        self.emit("pass")
        self.indent -= 1
        self.emit("except RuntimeError as _err:")
        self.indent += 1
        self.emit("print(str(_err), file=_sys.stderr)")
        self.emit("_sys.exit(70)")
        self.indent -= 1
        return "\n".join(self.lines) + "\n"

    def gen_stmts(self, stmts):
        for s in stmts:
            self.gen_stmt(s)

    def gen_stmt(self, s):
        if isinstance(s, PrintStmt):
            self.emit(f"_lox_print({self.gen_expr(s.expression)})")

        elif isinstance(s, ExpressionStmt):
            self.emit(self.gen_expr(s.expression))

        elif isinstance(s, VarStmt):
            if s.initializer is not None:
                val = self.gen_expr(s.initializer)
                self.emit(f'_e.define({repr(s.name.lexeme)}, {val})')
            else:
                self.emit(f'_e.define({repr(s.name.lexeme)}, None)')

        elif isinstance(s, BlockStmt):
            self.emit("_e = _e.child()")
            self.gen_stmts(s.statements)
            self.emit("_e = _e._p")

        elif isinstance(s, IfStmt):
            self.emit(f"if _truthy({self.gen_expr(s.condition)}):")
            self.indent += 1
            self.gen_stmt(s.then_branch)
            self.indent -= 1
            if s.else_branch is not None:
                self.emit("else:")
                self.indent += 1
                self.gen_stmt(s.else_branch)
                self.indent -= 1

        elif isinstance(s, WhileStmt):
            self.emit(f"while _truthy({self.gen_expr(s.condition)}):")
            self.indent += 1
            self.gen_stmt(s.body)
            self.indent -= 1

        elif isinstance(s, FunctionStmt):
            self.gen_function(s)

        elif isinstance(s, ReturnStmt):
            if s.value is not None:
                self.emit(f"raise _Return({self.gen_expr(s.value)})")
            else:
                self.emit("raise _Return(None)")

        elif isinstance(s, ClassStmt):
            self.gen_class(s)

    def gen_function(self, s, is_method=False):
        fn_name = self.fresh("_body")
        params = [p.lexeme for p in s.params]
        is_init = is_method and s.name.lexeme == "init"

        self.emit(f"def {fn_name}(_e):")
        self.indent += 1
        if s.body:
            self.gen_stmts(s.body)
        else:
            self.emit("pass")
        self.indent -= 1

        if is_method:
            return fn_name, params, is_init
        else:
            self.emit(
                f'_e.define({repr(s.name.lexeme)}, '
                f'_LoxFn({repr(s.name.lexeme)}, {repr(params)}, _e, {fn_name}))'
            )

    def gen_class(self, s):
        has_super = s.superclass is not None

        if has_super:
            super_expr = self.gen_expr(s.superclass)
            tmp = self.fresh("_sup")
            self.emit(f"{tmp} = {super_expr}")
            self.emit(f"if not isinstance({tmp}, _LoxClass):")
            self.indent += 1
            self.emit('raise RuntimeError("Superclass must be a class.")')
            self.indent -= 1

        self.emit(f'_e.define({repr(s.name.lexeme)}, None)')

        if has_super:
            self.emit("_e = _e.child()")
            self.emit(f'_e.define("super", {tmp})')

        methods_var = self.fresh("_meths")
        self.emit(f"{methods_var} = {{}}")

        for method in s.methods:
            fn_name, params, is_init = self.gen_function(method, is_method=True)
            init_str = "True" if is_init else "False"
            self.emit(
                f'{methods_var}[{repr(method.name.lexeme)}] = '
                f'_LoxFn({repr(method.name.lexeme)}, {repr(params)}, _e, {fn_name}, {init_str})'
            )

        klass_var = self.fresh("_cls")
        if has_super:
            self.emit(
                f'{klass_var} = _LoxClass({repr(s.name.lexeme)}, {tmp}, {methods_var})'
            )
            self.emit("_e = _e._p")
        else:
            self.emit(
                f'{klass_var} = _LoxClass({repr(s.name.lexeme)}, None, {methods_var})'
            )

        self.emit(f'_e.assign({repr(s.name.lexeme)}, {klass_var})')

    def gen_expr(self, e):
        if isinstance(e, Literal):
            if e.value is None:
                return "None"
            if e.value is True:
                return "True"
            if e.value is False:
                return "False"
            if isinstance(e.value, float):
                return repr(e.value)
            if isinstance(e.value, str):
                return repr(e.value)

        elif isinstance(e, Grouping):
            return f"({self.gen_expr(e.expression)})"

        elif isinstance(e, Variable):
            return f'_e.get({repr(e.name.lexeme)})'

        elif isinstance(e, Assign):
            val = self.gen_expr(e.value)
            return f'_e.assign({repr(e.name.lexeme)}, {val})'

        elif isinstance(e, Unary):
            right = self.gen_expr(e.right)
            if e.operator.ttype == TokenType.MINUS:
                return f"_lox_neg({right})"
            elif e.operator.ttype == TokenType.BANG:
                return f"(not _truthy({right}))"

        elif isinstance(e, Binary):
            left = self.gen_expr(e.left)
            right = self.gen_expr(e.right)
            op = e.operator.ttype

            if op == TokenType.PLUS:
                return f"_lox_add({left}, {right})"
            elif op == TokenType.MINUS:
                return f"_lox_sub({left}, {right})"
            elif op == TokenType.STAR:
                return f"_lox_mul({left}, {right})"
            elif op == TokenType.SLASH:
                return f"_lox_div({left}, {right})"
            elif op == TokenType.GREATER:
                return f"_lox_gt({left}, {right})"
            elif op == TokenType.GREATER_EQUAL:
                return f"_lox_gte({left}, {right})"
            elif op == TokenType.LESS:
                return f"_lox_lt({left}, {right})"
            elif op == TokenType.LESS_EQUAL:
                return f"_lox_lte({left}, {right})"
            elif op == TokenType.EQUAL_EQUAL:
                return f"_lox_eq({left}, {right})"
            elif op == TokenType.BANG_EQUAL:
                return f"(not _lox_eq({left}, {right}))"

        elif isinstance(e, Logical):
            left = self.gen_expr(e.left)
            right = self.gen_expr(e.right)
            if e.operator.ttype == TokenType.OR:
                return f"_lox_or(lambda: {left}, lambda: {right})"
            else:
                return f"_lox_and(lambda: {left}, lambda: {right})"

        elif isinstance(e, Call):
            callee = self.gen_expr(e.callee)
            args = ", ".join(self.gen_expr(a) for a in e.arguments)
            return f"_lox_call({callee}, [{args}])"

        elif isinstance(e, Get):
            obj = self.gen_expr(e.obj)
            return f'_lox_get({obj}, {repr(e.name.lexeme)})'

        elif isinstance(e, Set):
            obj = self.gen_expr(e.obj)
            val = self.gen_expr(e.value)
            return f'_lox_set({obj}, {repr(e.name.lexeme)}, {val})'

        elif isinstance(e, This):
            return '_e.get("this")'

        elif isinstance(e, Super):
            return f'_lox_super(_e, {repr(e.method.lexeme)})'

        return "None"


# ── Main Entry Point ────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 transpile.py <file.lox>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    # Parse with ANTLR4
    input_stream = InputStream(source)
    lexer = LoxLexer(input_stream)
    error_listener = LoxErrorListener()
    lexer.removeErrorListeners()
    lexer.addErrorListener(error_listener)

    stream = CommonTokenStream(lexer)
    parser = LoxParser(stream)
    parser.removeErrorListeners()
    parser.addErrorListener(error_listener)

    tree = parser.program()

    if error_listener.has_error:
        sys.exit(65)

    # Convert ANTLR4 parse tree to Lox AST
    builder = ASTBuilder()
    stmts = builder.visit(tree)

    # Generate Python code from AST
    transpiler = Transpiler()
    python_code = transpiler.transpile_stmts(stmts)
    print(python_code, end="")


if __name__ == "__main__":
    main()
