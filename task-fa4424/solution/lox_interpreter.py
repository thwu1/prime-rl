#!/usr/bin/env python3
"""Complete Lox tree-walk interpreter."""
import sys
import time
from enum import Enum, auto

# ===== TOKEN TYPES =====
class TT(Enum):
    LEFT_PAREN=auto(); RIGHT_PAREN=auto(); LEFT_BRACE=auto(); RIGHT_BRACE=auto()
    COMMA=auto(); DOT=auto(); MINUS=auto(); PLUS=auto(); SEMICOLON=auto()
    SLASH=auto(); STAR=auto()
    BANG=auto(); BANG_EQUAL=auto(); EQUAL=auto(); EQUAL_EQUAL=auto()
    GREATER=auto(); GREATER_EQUAL=auto(); LESS=auto(); LESS_EQUAL=auto()
    IDENTIFIER=auto(); STRING=auto(); NUMBER=auto()
    AND=auto(); CLASS=auto(); ELSE=auto(); FALSE=auto(); FUN=auto(); FOR=auto()
    IF=auto(); NIL=auto(); OR=auto(); PRINT=auto(); RETURN=auto()
    SUPER=auto(); THIS=auto(); TRUE=auto(); VAR=auto(); WHILE=auto()
    EOF=auto()

class Token:
    __slots__ = ('type','lexeme','literal','line')
    def __init__(self, type, lexeme, literal, line):
        self.type=type; self.lexeme=lexeme; self.literal=literal; self.line=line

KEYWORDS = {"and":TT.AND,"class":TT.CLASS,"else":TT.ELSE,"false":TT.FALSE,
    "for":TT.FOR,"fun":TT.FUN,"if":TT.IF,"nil":TT.NIL,"or":TT.OR,
    "print":TT.PRINT,"return":TT.RETURN,"super":TT.SUPER,"this":TT.THIS,
    "true":TT.TRUE,"var":TT.VAR,"while":TT.WHILE}

# ===== ERROR HANDLING =====
had_error = False
had_runtime_error = False

def error(line, message):
    report(line, "", message)

def report(line, where, message):
    global had_error
    print(f"[line {line}] Error{where}: {message}", file=sys.stderr)
    had_error = True

def error_token(token, message):
    if token.type == TT.EOF:
        report(token.line, " at end", message)
    else:
        report(token.line, f" at '{token.lexeme}'", message)

class LoxRuntimeError(RuntimeError):
    def __init__(self, token, message):
        super().__init__(message)
        self.token = token

def runtime_error(err):
    global had_runtime_error
    print(f"{err.args[0]}\n[line {err.token.line}]", file=sys.stderr)
    had_runtime_error = True

# ===== SCANNER =====
class Scanner:
    def __init__(self, source):
        self.source = source
        self.tokens = []
        self.start = 0
        self.current = 0
        self.line = 1

    def scan_tokens(self):
        while self.current < len(self.source):
            self.start = self.current
            self._scan_token()
        self.tokens.append(Token(TT.EOF, "", None, self.line))
        return self.tokens

    def _scan_token(self):
        c = self.source[self.current]; self.current += 1
        if c == '(': self._add(TT.LEFT_PAREN)
        elif c == ')': self._add(TT.RIGHT_PAREN)
        elif c == '{': self._add(TT.LEFT_BRACE)
        elif c == '}': self._add(TT.RIGHT_BRACE)
        elif c == ',': self._add(TT.COMMA)
        elif c == '.': self._add(TT.DOT)
        elif c == '-': self._add(TT.MINUS)
        elif c == '+': self._add(TT.PLUS)
        elif c == ';': self._add(TT.SEMICOLON)
        elif c == '*': self._add(TT.STAR)
        elif c == '!': self._add(TT.BANG_EQUAL if self._match('=') else TT.BANG)
        elif c == '=': self._add(TT.EQUAL_EQUAL if self._match('=') else TT.EQUAL)
        elif c == '<': self._add(TT.LESS_EQUAL if self._match('=') else TT.LESS)
        elif c == '>': self._add(TT.GREATER_EQUAL if self._match('=') else TT.GREATER)
        elif c == '/':
            if self._match('/'):
                while self.current < len(self.source) and self.source[self.current] != '\n':
                    self.current += 1
            else:
                self._add(TT.SLASH)
        elif c in ' \r\t': pass
        elif c == '\n': self.line += 1
        elif c == '"': self._string()
        elif c.isdigit(): self._number()
        elif c.isalpha() or c == '_': self._identifier()
        else: error(self.line, f"Unexpected character: {c}")

    def _match(self, expected):
        if self.current < len(self.source) and self.source[self.current] == expected:
            self.current += 1; return True
        return False

    def _add(self, type, literal=None):
        self.tokens.append(Token(type, self.source[self.start:self.current], literal, self.line))

    def _string(self):
        while self.current < len(self.source) and self.source[self.current] != '"':
            if self.source[self.current] == '\n': self.line += 1
            self.current += 1
        if self.current >= len(self.source):
            error(self.line, "Unterminated string."); return
        self.current += 1
        self._add(TT.STRING, self.source[self.start+1:self.current-1])

    def _number(self):
        while self.current < len(self.source) and self.source[self.current].isdigit(): self.current += 1
        if (self.current < len(self.source) and self.source[self.current] == '.' and
            self.current+1 < len(self.source) and self.source[self.current+1].isdigit()):
            self.current += 1
            while self.current < len(self.source) and self.source[self.current].isdigit(): self.current += 1
        self._add(TT.NUMBER, float(self.source[self.start:self.current]))

    def _identifier(self):
        while self.current < len(self.source) and (self.source[self.current].isalnum() or self.source[self.current] == '_'):
            self.current += 1
        text = self.source[self.start:self.current]
        self._add(KEYWORDS.get(text, TT.IDENTIFIER))

# ===== AST NODES =====
class Expr: pass
class Binary(Expr):
    def __init__(self, left, op, right): self.left=left; self.op=op; self.right=right
class Grouping(Expr):
    def __init__(self, expr): self.expr=expr
class Literal(Expr):
    def __init__(self, value): self.value=value
class Unary(Expr):
    def __init__(self, op, right): self.op=op; self.right=right
class Variable(Expr):
    def __init__(self, name): self.name=name
class Assign(Expr):
    def __init__(self, name, value): self.name=name; self.value=value
class Logical(Expr):
    def __init__(self, left, op, right): self.left=left; self.op=op; self.right=right
class Call(Expr):
    def __init__(self, callee, paren, arguments): self.callee=callee; self.paren=paren; self.arguments=arguments
class Get(Expr):
    def __init__(self, obj, name): self.obj=obj; self.name=name
class Set(Expr):
    def __init__(self, obj, name, value): self.obj=obj; self.name=name; self.value=value
class This(Expr):
    def __init__(self, keyword): self.keyword=keyword
class Super(Expr):
    def __init__(self, keyword, method): self.keyword=keyword; self.method=method

class Stmt: pass
class ExpressionStmt(Stmt):
    def __init__(self, expr): self.expr=expr
class PrintStmt(Stmt):
    def __init__(self, expr): self.expr=expr
class VarStmt(Stmt):
    def __init__(self, name, initializer): self.name=name; self.initializer=initializer
class BlockStmt(Stmt):
    def __init__(self, statements): self.statements=statements
class IfStmt(Stmt):
    def __init__(self, condition, then_branch, else_branch):
        self.condition=condition; self.then_branch=then_branch; self.else_branch=else_branch
class WhileStmt(Stmt):
    def __init__(self, condition, body): self.condition=condition; self.body=body
class FunctionStmt(Stmt):
    def __init__(self, name, params, body): self.name=name; self.params=params; self.body=body
class ReturnStmt(Stmt):
    def __init__(self, keyword, value): self.keyword=keyword; self.value=value
class ClassStmt(Stmt):
    def __init__(self, name, superclass, methods): self.name=name; self.superclass=superclass; self.methods=methods

# ===== PARSER =====
class ParseError(Exception): pass

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.current = 0

    def parse(self):
        statements = []
        while not self._is_at_end():
            decl = self._declaration()
            if decl is not None:
                statements.append(decl)
        return statements

    def _declaration(self):
        try:
            if self._match(TT.CLASS): return self._class_declaration()
            if self._match(TT.FUN): return self._function("function")
            if self._match(TT.VAR): return self._var_declaration()
            return self._statement()
        except ParseError:
            self._synchronize()
            return None

    def _class_declaration(self):
        name = self._consume(TT.IDENTIFIER, "Expect class name.")
        superclass = None
        if self._match(TT.LESS):
            self._consume(TT.IDENTIFIER, "Expect superclass name.")
            superclass = Variable(self._previous())
        self._consume(TT.LEFT_BRACE, "Expect '{' before class body.")
        methods = []
        while not self._check(TT.RIGHT_BRACE) and not self._is_at_end():
            methods.append(self._function("method"))
        self._consume(TT.RIGHT_BRACE, "Expect '}' after class body.")
        return ClassStmt(name, superclass, methods)

    def _function(self, kind):
        name = self._consume(TT.IDENTIFIER, f"Expect {kind} name.")
        self._consume(TT.LEFT_PAREN, f"Expect '(' after {kind} name.")
        params = []
        if not self._check(TT.RIGHT_PAREN):
            params.append(self._consume(TT.IDENTIFIER, "Expect parameter name."))
            while self._match(TT.COMMA):
                if len(params) >= 255:
                    self._error(self._peek(), "Can't have more than 255 parameters.")
                params.append(self._consume(TT.IDENTIFIER, "Expect parameter name."))
        self._consume(TT.RIGHT_PAREN, "Expect ')' after parameters.")
        self._consume(TT.LEFT_BRACE, f"Expect '{{' before {kind} body.")
        body = self._block()
        return FunctionStmt(name, params, body)

    def _var_declaration(self):
        name = self._consume(TT.IDENTIFIER, "Expect variable name.")
        initializer = None
        if self._match(TT.EQUAL):
            initializer = self._expression()
        self._consume(TT.SEMICOLON, "Expect ';' after variable declaration.")
        return VarStmt(name, initializer)

    def _statement(self):
        if self._match(TT.FOR): return self._for_statement()
        if self._match(TT.IF): return self._if_statement()
        if self._match(TT.PRINT): return self._print_statement()
        if self._match(TT.RETURN): return self._return_statement()
        if self._match(TT.WHILE): return self._while_statement()
        if self._match(TT.LEFT_BRACE): return BlockStmt(self._block())
        return self._expression_statement()

    def _for_statement(self):
        self._consume(TT.LEFT_PAREN, "Expect '(' after 'for'.")
        if self._match(TT.SEMICOLON):
            initializer = None
        elif self._match(TT.VAR):
            initializer = self._var_declaration()
        else:
            initializer = self._expression_statement()
        condition = None
        if not self._check(TT.SEMICOLON):
            condition = self._expression()
        self._consume(TT.SEMICOLON, "Expect ';' after loop condition.")
        increment = None
        if not self._check(TT.RIGHT_PAREN):
            increment = self._expression()
        self._consume(TT.RIGHT_PAREN, "Expect ')' after for clauses.")
        body = self._statement()
        if increment is not None:
            body = BlockStmt([body, ExpressionStmt(increment)])
        if condition is None:
            condition = Literal(True)
        body = WhileStmt(condition, body)
        if initializer is not None:
            body = BlockStmt([initializer, body])
        return body

    def _if_statement(self):
        self._consume(TT.LEFT_PAREN, "Expect '(' after 'if'.")
        condition = self._expression()
        self._consume(TT.RIGHT_PAREN, "Expect ')' after if condition.")
        then_branch = self._statement()
        else_branch = None
        if self._match(TT.ELSE):
            else_branch = self._statement()
        return IfStmt(condition, then_branch, else_branch)

    def _print_statement(self):
        value = self._expression()
        self._consume(TT.SEMICOLON, "Expect ';' after value.")
        return PrintStmt(value)

    def _return_statement(self):
        keyword = self._previous()
        value = None
        if not self._check(TT.SEMICOLON):
            value = self._expression()
        self._consume(TT.SEMICOLON, "Expect ';' after return value.")
        return ReturnStmt(keyword, value)

    def _while_statement(self):
        self._consume(TT.LEFT_PAREN, "Expect '(' after 'while'.")
        condition = self._expression()
        self._consume(TT.RIGHT_PAREN, "Expect ')' after condition.")
        body = self._statement()
        return WhileStmt(condition, body)

    def _block(self):
        statements = []
        while not self._check(TT.RIGHT_BRACE) and not self._is_at_end():
            decl = self._declaration()
            if decl is not None:
                statements.append(decl)
        self._consume(TT.RIGHT_BRACE, "Expect '}' after block.")
        return statements

    def _expression_statement(self):
        expr = self._expression()
        self._consume(TT.SEMICOLON, "Expect ';' after expression.")
        return ExpressionStmt(expr)

    def _expression(self):
        return self._assignment()

    def _assignment(self):
        expr = self._or()
        if self._match(TT.EQUAL):
            equals = self._previous()
            value = self._assignment()
            if isinstance(expr, Variable):
                return Assign(expr.name, value)
            elif isinstance(expr, Get):
                return Set(expr.obj, expr.name, value)
            self._error(equals, "Invalid assignment target.")
        return expr

    def _or(self):
        expr = self._and()
        while self._match(TT.OR):
            op = self._previous(); right = self._and()
            expr = Logical(expr, op, right)
        return expr

    def _and(self):
        expr = self._equality()
        while self._match(TT.AND):
            op = self._previous(); right = self._equality()
            expr = Logical(expr, op, right)
        return expr

    def _equality(self):
        expr = self._comparison()
        while self._match(TT.BANG_EQUAL, TT.EQUAL_EQUAL):
            op = self._previous(); right = self._comparison()
            expr = Binary(expr, op, right)
        return expr

    def _comparison(self):
        expr = self._term()
        while self._match(TT.GREATER, TT.GREATER_EQUAL, TT.LESS, TT.LESS_EQUAL):
            op = self._previous(); right = self._term()
            expr = Binary(expr, op, right)
        return expr

    def _term(self):
        expr = self._factor()
        while self._match(TT.MINUS, TT.PLUS):
            op = self._previous(); right = self._factor()
            expr = Binary(expr, op, right)
        return expr

    def _factor(self):
        expr = self._unary()
        while self._match(TT.SLASH, TT.STAR):
            op = self._previous(); right = self._unary()
            expr = Binary(expr, op, right)
        return expr

    def _unary(self):
        if self._match(TT.BANG, TT.MINUS):
            op = self._previous(); right = self._unary()
            return Unary(op, right)
        return self._call()

    def _call(self):
        expr = self._primary()
        while True:
            if self._match(TT.LEFT_PAREN):
                expr = self._finish_call(expr)
            elif self._match(TT.DOT):
                name = self._consume(TT.IDENTIFIER, "Expect property name after '.'.")
                expr = Get(expr, name)
            else:
                break
        return expr

    def _finish_call(self, callee):
        arguments = []
        if not self._check(TT.RIGHT_PAREN):
            arguments.append(self._expression())
            while self._match(TT.COMMA):
                if len(arguments) >= 255:
                    self._error(self._peek(), "Can't have more than 255 arguments.")
                arguments.append(self._expression())
        paren = self._consume(TT.RIGHT_PAREN, "Expect ')' after arguments.")
        return Call(callee, paren, arguments)

    def _primary(self):
        if self._match(TT.FALSE): return Literal(False)
        if self._match(TT.TRUE): return Literal(True)
        if self._match(TT.NIL): return Literal(None)
        if self._match(TT.NUMBER, TT.STRING): return Literal(self._previous().literal)
        if self._match(TT.SUPER):
            keyword = self._previous()
            self._consume(TT.DOT, "Expect '.' after 'super'.")
            method = self._consume(TT.IDENTIFIER, "Expect superclass method name.")
            return Super(keyword, method)
        if self._match(TT.THIS): return This(self._previous())
        if self._match(TT.IDENTIFIER): return Variable(self._previous())
        if self._match(TT.LEFT_PAREN):
            expr = self._expression()
            self._consume(TT.RIGHT_PAREN, "Expect ')' after expression.")
            return Grouping(expr)
        raise self._error(self._peek(), "Expect expression.")

    def _match(self, *types):
        for t in types:
            if self._check(t):
                self._advance(); return True
        return False

    def _check(self, type):
        return not self._is_at_end() and self._peek().type == type

    def _advance(self):
        if not self._is_at_end(): self.current += 1
        return self._previous()

    def _is_at_end(self):
        return self._peek().type == TT.EOF

    def _peek(self):
        return self.tokens[self.current]

    def _previous(self):
        return self.tokens[self.current - 1]

    def _consume(self, type, message):
        if self._check(type): return self._advance()
        raise self._error(self._peek(), message)

    def _error(self, token, message):
        error_token(token, message)
        return ParseError()

    def _synchronize(self):
        self._advance()
        while not self._is_at_end():
            if self._previous().type == TT.SEMICOLON: return
            if self._peek().type in (TT.CLASS, TT.FUN, TT.VAR, TT.FOR, TT.IF, TT.WHILE, TT.PRINT, TT.RETURN):
                return
            self._advance()

# ===== ENVIRONMENT =====
class Environment:
    def __init__(self, enclosing=None):
        self.values = {}
        self.enclosing = enclosing

    def define(self, name, value):
        self.values[name] = value

    def get(self, name):
        if name.lexeme in self.values:
            return self.values[name.lexeme]
        if self.enclosing is not None:
            return self.enclosing.get(name)
        raise LoxRuntimeError(name, f"Undefined variable '{name.lexeme}'.")

    def assign(self, name, value):
        if name.lexeme in self.values:
            self.values[name.lexeme] = value
            return
        if self.enclosing is not None:
            self.enclosing.assign(name, value)
            return
        raise LoxRuntimeError(name, f"Undefined variable '{name.lexeme}'.")

    def get_at(self, distance, name):
        return self._ancestor(distance).values.get(name)

    def assign_at(self, distance, name, value):
        self._ancestor(distance).values[name] = value

    def _ancestor(self, distance):
        env = self
        for _ in range(distance):
            env = env.enclosing
        return env

# ===== RUNTIME TYPES =====
class Return(Exception):
    def __init__(self, value):
        self.value = value

class LoxCallable:
    def call(self, interpreter, arguments): raise NotImplementedError
    def arity(self): raise NotImplementedError

class ClockNative(LoxCallable):
    def arity(self): return 0
    def call(self, interpreter, arguments): return float(time.time())
    def __str__(self): return "<native fn>"

class LoxFunction(LoxCallable):
    def __init__(self, declaration, closure, is_initializer):
        self.declaration = declaration
        self.closure = closure
        self.is_initializer = is_initializer

    def arity(self):
        return len(self.declaration.params)

    def call(self, interpreter, arguments):
        env = Environment(self.closure)
        for i, param in enumerate(self.declaration.params):
            env.define(param.lexeme, arguments[i])
        try:
            interpreter._execute_block(self.declaration.body, env)
        except Return as ret:
            if self.is_initializer:
                return self.closure.get_at(0, "this")
            return ret.value
        if self.is_initializer:
            return self.closure.get_at(0, "this")
        return None

    def bind(self, instance):
        env = Environment(self.closure)
        env.define("this", instance)
        return LoxFunction(self.declaration, env, self.is_initializer)

    def __str__(self):
        return f"<fn {self.declaration.name.lexeme}>"

class LoxClass(LoxCallable):
    def __init__(self, name, superclass, methods):
        self.name = name
        self.superclass = superclass
        self.methods = methods

    def call(self, interpreter, arguments):
        instance = LoxInstance(self)
        initializer = self.find_method("init")
        if initializer is not None:
            initializer.bind(instance).call(interpreter, arguments)
        return instance

    def arity(self):
        initializer = self.find_method("init")
        if initializer is None: return 0
        return initializer.arity()

    def find_method(self, name):
        if name in self.methods:
            return self.methods[name]
        if self.superclass is not None:
            return self.superclass.find_method(name)
        return None

    def __str__(self):
        return self.name

class LoxInstance:
    def __init__(self, klass):
        self.klass = klass
        self.fields = {}

    def get(self, name):
        if name.lexeme in self.fields:
            return self.fields[name.lexeme]
        method = self.klass.find_method(name.lexeme)
        if method is not None:
            return method.bind(self)
        raise LoxRuntimeError(name, f"Undefined property '{name.lexeme}'.")

    def set(self, name, value):
        self.fields[name.lexeme] = value

    def __str__(self):
        return f"{self.klass.name} instance"

# ===== RESOLVER =====
class FunctionType:
    NONE = "NONE"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    INITIALIZER = "INITIALIZER"

class ClassType:
    NONE = "NONE"
    CLASS = "CLASS"
    SUBCLASS = "SUBCLASS"

class Resolver:
    def __init__(self, interpreter):
        self.interpreter = interpreter
        self.scopes = []
        self.current_function = FunctionType.NONE
        self.current_class = ClassType.NONE

    def resolve(self, stmts_or_stmt):
        if isinstance(stmts_or_stmt, list):
            for stmt in stmts_or_stmt:
                self._resolve_stmt(stmt)
        else:
            self._resolve_stmt(stmts_or_stmt)

    def _resolve_stmt(self, stmt):
        method = getattr(self, f'_visit_{type(stmt).__name__}', None)
        if method: method(stmt)

    def _resolve_expr(self, expr):
        method = getattr(self, f'_visit_{type(expr).__name__}', None)
        if method: method(expr)

    def _begin_scope(self):
        self.scopes.append({})

    def _end_scope(self):
        self.scopes.pop()

    def _declare(self, name):
        if not self.scopes: return
        scope = self.scopes[-1]
        if name.lexeme in scope:
            error_token(name, "Already a variable with this name in this scope.")
        scope[name.lexeme] = False

    def _define(self, name):
        if not self.scopes: return
        self.scopes[-1][name.lexeme] = True

    def _resolve_local(self, expr, name):
        for i in range(len(self.scopes) - 1, -1, -1):
            if name.lexeme in self.scopes[i]:
                self.interpreter.resolve(expr, len(self.scopes) - 1 - i)
                return

    def _resolve_function(self, function, type):
        enclosing = self.current_function
        self.current_function = type
        self._begin_scope()
        for param in function.params:
            self._declare(param)
            self._define(param)
        self.resolve(function.body)
        self._end_scope()
        self.current_function = enclosing

    # Statement visitors
    def _visit_BlockStmt(self, stmt):
        self._begin_scope()
        self.resolve(stmt.statements)
        self._end_scope()

    def _visit_VarStmt(self, stmt):
        self._declare(stmt.name)
        if stmt.initializer is not None:
            self._resolve_expr(stmt.initializer)
        self._define(stmt.name)

    def _visit_FunctionStmt(self, stmt):
        self._declare(stmt.name)
        self._define(stmt.name)
        self._resolve_function(stmt, FunctionType.FUNCTION)

    def _visit_ExpressionStmt(self, stmt):
        self._resolve_expr(stmt.expr)

    def _visit_IfStmt(self, stmt):
        self._resolve_expr(stmt.condition)
        self._resolve_stmt(stmt.then_branch)
        if stmt.else_branch is not None:
            self._resolve_stmt(stmt.else_branch)

    def _visit_PrintStmt(self, stmt):
        self._resolve_expr(stmt.expr)

    def _visit_ReturnStmt(self, stmt):
        if self.current_function == FunctionType.NONE:
            error_token(stmt.keyword, "Can't return from top-level code.")
        if stmt.value is not None:
            if self.current_function == FunctionType.INITIALIZER:
                error_token(stmt.keyword, "Can't return a value from an initializer.")
            self._resolve_expr(stmt.value)

    def _visit_WhileStmt(self, stmt):
        self._resolve_expr(stmt.condition)
        self._resolve_stmt(stmt.body)

    def _visit_ClassStmt(self, stmt):
        enclosing_class = self.current_class
        self.current_class = ClassType.CLASS
        self._declare(stmt.name)
        self._define(stmt.name)
        if stmt.superclass is not None:
            if stmt.name.lexeme == stmt.superclass.name.lexeme:
                error_token(stmt.superclass.name, "A class can't inherit from itself.")
            self.current_class = ClassType.SUBCLASS
            self._resolve_expr(stmt.superclass)
            self._begin_scope()
            self.scopes[-1]["super"] = True
        self._begin_scope()
        self.scopes[-1]["this"] = True
        for method in stmt.methods:
            declaration = FunctionType.METHOD
            if method.name.lexeme == "init":
                declaration = FunctionType.INITIALIZER
            self._resolve_function(method, declaration)
        self._end_scope()
        if stmt.superclass is not None:
            self._end_scope()
        self.current_class = enclosing_class

    # Expression visitors
    def _visit_Variable(self, expr):
        if self.scopes and self.scopes[-1].get(expr.name.lexeme) is False:
            error_token(expr.name, "Can't read local variable in its own initializer.")
        self._resolve_local(expr, expr.name)

    def _visit_Assign(self, expr):
        self._resolve_expr(expr.value)
        self._resolve_local(expr, expr.name)

    def _visit_Binary(self, expr):
        self._resolve_expr(expr.left)
        self._resolve_expr(expr.right)

    def _visit_Call(self, expr):
        self._resolve_expr(expr.callee)
        for arg in expr.arguments:
            self._resolve_expr(arg)

    def _visit_Grouping(self, expr):
        self._resolve_expr(expr.expr)

    def _visit_Literal(self, expr):
        pass

    def _visit_Logical(self, expr):
        self._resolve_expr(expr.left)
        self._resolve_expr(expr.right)

    def _visit_Unary(self, expr):
        self._resolve_expr(expr.right)

    def _visit_Get(self, expr):
        self._resolve_expr(expr.obj)

    def _visit_Set(self, expr):
        self._resolve_expr(expr.value)
        self._resolve_expr(expr.obj)

    def _visit_This(self, expr):
        if self.current_class == ClassType.NONE:
            error_token(expr.keyword, "Can't use 'this' outside of a class.")
            return
        self._resolve_local(expr, expr.keyword)

    def _visit_Super(self, expr):
        if self.current_class == ClassType.NONE:
            error_token(expr.keyword, "Can't use 'super' outside of a class.")
        elif self.current_class != ClassType.SUBCLASS:
            error_token(expr.keyword, "Can't use 'super' in a class with no superclass.")
        self._resolve_local(expr, expr.keyword)

# ===== INTERPRETER =====
class Interpreter:
    def __init__(self):
        self.globals = Environment()
        self.environment = self.globals
        self.locals = {}
        self.globals.define("clock", ClockNative())

    def interpret(self, statements):
        try:
            for stmt in statements:
                self._execute(stmt)
        except LoxRuntimeError as e:
            runtime_error(e)

    def resolve(self, expr, depth):
        self.locals[id(expr)] = depth

    def _execute(self, stmt):
        method = getattr(self, f'_exec_{type(stmt).__name__}', None)
        if method: method(stmt)

    def _evaluate(self, expr):
        method = getattr(self, f'_eval_{type(expr).__name__}', None)
        if method: return method(expr)
        return None

    def _execute_block(self, statements, environment):
        previous = self.environment
        try:
            self.environment = environment
            for stmt in statements:
                self._execute(stmt)
        finally:
            self.environment = previous

    def _stringify(self, value):
        if value is None: return "nil"
        if isinstance(value, bool): return "true" if value else "false"
        if isinstance(value, float):
            text = str(value)
            if text.endswith(".0"):
                text = text[:-2]
            return text
        return str(value)

    def _is_truthy(self, value):
        if value is None: return False
        if isinstance(value, bool): return value
        return True

    def _is_equal(self, a, b):
        if a is None and b is None: return True
        if a is None or b is None: return False
        if type(a) != type(b): return False
        return a == b

    def _check_number_operand(self, op, operand):
        if isinstance(operand, (float, int)) and not isinstance(operand, bool): return
        raise LoxRuntimeError(op, "Operand must be a number.")

    def _check_number_operands(self, op, left, right):
        if (isinstance(left, (float, int)) and not isinstance(left, bool) and
            isinstance(right, (float, int)) and not isinstance(right, bool)): return
        raise LoxRuntimeError(op, "Operands must be numbers.")

    def _look_up_variable(self, name, expr):
        distance = self.locals.get(id(expr))
        if distance is not None:
            return self.environment.get_at(distance, name.lexeme)
        return self.globals.get(name)

    # Statement executors
    def _exec_ExpressionStmt(self, stmt):
        self._evaluate(stmt.expr)

    def _exec_PrintStmt(self, stmt):
        value = self._evaluate(stmt.expr)
        print(self._stringify(value))

    def _exec_VarStmt(self, stmt):
        value = None
        if stmt.initializer is not None:
            value = self._evaluate(stmt.initializer)
        self.environment.define(stmt.name.lexeme, value)

    def _exec_BlockStmt(self, stmt):
        self._execute_block(stmt.statements, Environment(self.environment))

    def _exec_IfStmt(self, stmt):
        if self._is_truthy(self._evaluate(stmt.condition)):
            self._execute(stmt.then_branch)
        elif stmt.else_branch is not None:
            self._execute(stmt.else_branch)

    def _exec_WhileStmt(self, stmt):
        while self._is_truthy(self._evaluate(stmt.condition)):
            self._execute(stmt.body)

    def _exec_FunctionStmt(self, stmt):
        function = LoxFunction(stmt, self.environment, False)
        self.environment.define(stmt.name.lexeme, function)

    def _exec_ReturnStmt(self, stmt):
        value = None
        if stmt.value is not None:
            value = self._evaluate(stmt.value)
        raise Return(value)

    def _exec_ClassStmt(self, stmt):
        superclass = None
        if stmt.superclass is not None:
            superclass = self._evaluate(stmt.superclass)
            if not isinstance(superclass, LoxClass):
                raise LoxRuntimeError(stmt.superclass.name, "Superclass must be a class.")
        self.environment.define(stmt.name.lexeme, None)
        if stmt.superclass is not None:
            self.environment = Environment(self.environment)
            self.environment.define("super", superclass)
        methods = {}
        for method in stmt.methods:
            function = LoxFunction(method, self.environment, method.name.lexeme == "init")
            methods[method.name.lexeme] = function
        klass = LoxClass(stmt.name.lexeme, superclass, methods)
        if stmt.superclass is not None:
            self.environment = self.environment.enclosing
        self.environment.assign(stmt.name, klass)

    # Expression evaluators
    def _eval_Literal(self, expr):
        return expr.value

    def _eval_Grouping(self, expr):
        return self._evaluate(expr.expr)

    def _eval_Unary(self, expr):
        right = self._evaluate(expr.right)
        if expr.op.type == TT.MINUS:
            self._check_number_operand(expr.op, right)
            return -float(right)
        if expr.op.type == TT.BANG:
            return not self._is_truthy(right)
        return None

    def _eval_Binary(self, expr):
        left = self._evaluate(expr.left)
        right = self._evaluate(expr.right)
        t = expr.op.type
        if t == TT.MINUS:
            self._check_number_operands(expr.op, left, right); return left - right
        if t == TT.SLASH:
            self._check_number_operands(expr.op, left, right); return left / right
        if t == TT.STAR:
            self._check_number_operands(expr.op, left, right); return left * right
        if t == TT.PLUS:
            if isinstance(left, float) and isinstance(right, float): return left + right
            if isinstance(left, str) and isinstance(right, str): return left + right
            raise LoxRuntimeError(expr.op, "Operands must be two numbers or two strings.")
        if t == TT.GREATER:
            self._check_number_operands(expr.op, left, right); return left > right
        if t == TT.GREATER_EQUAL:
            self._check_number_operands(expr.op, left, right); return left >= right
        if t == TT.LESS:
            self._check_number_operands(expr.op, left, right); return left < right
        if t == TT.LESS_EQUAL:
            self._check_number_operands(expr.op, left, right); return left <= right
        if t == TT.BANG_EQUAL:
            return not self._is_equal(left, right)
        if t == TT.EQUAL_EQUAL:
            return self._is_equal(left, right)
        return None

    def _eval_Variable(self, expr):
        return self._look_up_variable(expr.name, expr)

    def _eval_Assign(self, expr):
        value = self._evaluate(expr.value)
        distance = self.locals.get(id(expr))
        if distance is not None:
            self.environment.assign_at(distance, expr.name.lexeme, value)
        else:
            self.globals.assign(expr.name, value)
        return value

    def _eval_Logical(self, expr):
        left = self._evaluate(expr.left)
        if expr.op.type == TT.OR:
            if self._is_truthy(left): return left
        else:
            if not self._is_truthy(left): return left
        return self._evaluate(expr.right)

    def _eval_Call(self, expr):
        callee = self._evaluate(expr.callee)
        arguments = [self._evaluate(arg) for arg in expr.arguments]
        if not isinstance(callee, LoxCallable):
            raise LoxRuntimeError(expr.paren, "Can only call functions and classes.")
        if len(arguments) != callee.arity():
            raise LoxRuntimeError(expr.paren,
                f"Expected {callee.arity()} arguments but got {len(arguments)}.")
        return callee.call(self, arguments)

    def _eval_Get(self, expr):
        obj = self._evaluate(expr.obj)
        if isinstance(obj, LoxInstance):
            return obj.get(expr.name)
        raise LoxRuntimeError(expr.name, "Only instances have properties.")

    def _eval_Set(self, expr):
        obj = self._evaluate(expr.obj)
        if not isinstance(obj, LoxInstance):
            raise LoxRuntimeError(expr.name, "Only instances have fields.")
        value = self._evaluate(expr.value)
        obj.set(expr.name, value)
        return value

    def _eval_This(self, expr):
        return self._look_up_variable(expr.keyword, expr)

    def _eval_Super(self, expr):
        distance = self.locals.get(id(expr))
        superclass = self.environment.get_at(distance, "super")
        obj = self.environment.get_at(distance - 1, "this")
        method = superclass.find_method(expr.method.lexeme)
        if method is None:
            raise LoxRuntimeError(expr.method, f"Undefined property '{expr.method.lexeme}'.")
        return method.bind(obj)

# ===== MAIN =====
def main():
    global had_error, had_runtime_error
    if len(sys.argv) != 2:
        print("Usage: lox.py <script>", file=sys.stderr)
        sys.exit(64)
    with open(sys.argv[1]) as f:
        source = f.read()
    scanner = Scanner(source)
    tokens = scanner.scan_tokens()
    if had_error: sys.exit(65)
    parser = Parser(tokens)
    statements = parser.parse()
    if had_error: sys.exit(65)
    interpreter = Interpreter()
    resolver = Resolver(interpreter)
    resolver.resolve(statements)
    if had_error: sys.exit(65)
    interpreter.interpret(statements)
    if had_runtime_error: sys.exit(70)

if __name__ == "__main__":
    main()
