#!/usr/bin/env python3
"""Lox-to-JavaScript transpiler.

Reads a .lox file, emits semantically equivalent JavaScript to stdout.
The generated JS is runnable with Node.js and produces identical output
(stdout, stderr, exit code) to the reference tree-walk interpreter.
"""
import sys
import json
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

# ===== RESOLVER =====
# Tracks which Variable/Assign expressions are local vs global.
# Also detects static errors (same as reference interpreter).
class Resolver:
    def __init__(self):
        self.scopes = []
        self.current_function = "NONE"
        self.current_class = "NONE"
        self.locals = set()  # set of id(expr) for locally-resolved expressions

    def resolve(self, stmts_or_stmt):
        if isinstance(stmts_or_stmt, list):
            for s in stmts_or_stmt:
                self._resolve_stmt(s)
        else:
            self._resolve_stmt(stmts_or_stmt)

    def _resolve_stmt(self, s):
        m = getattr(self, f'_visit_{type(s).__name__}', None)
        if m: m(s)

    def _resolve_expr(self, e):
        m = getattr(self, f'_visit_{type(e).__name__}', None)
        if m: m(e)

    def _begin_scope(self): self.scopes.append({})
    def _end_scope(self): self.scopes.pop()

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
                self.locals.add(id(expr))
                return

    def _resolve_function(self, func, ftype):
        enclosing = self.current_function
        self.current_function = ftype
        self._begin_scope()
        for p in func.params:
            self._declare(p)
            self._define(p)
        self.resolve(func.body)
        self._end_scope()
        self.current_function = enclosing

    # Statement visitors
    def _visit_BlockStmt(self, s):
        self._begin_scope(); self.resolve(s.statements); self._end_scope()

    def _visit_VarStmt(self, s):
        self._declare(s.name)
        if s.initializer is not None:
            self._resolve_expr(s.initializer)
        self._define(s.name)

    def _visit_FunctionStmt(self, s):
        self._declare(s.name); self._define(s.name)
        self._resolve_function(s, "FUNCTION")

    def _visit_ExpressionStmt(self, s): self._resolve_expr(s.expr)
    def _visit_PrintStmt(self, s): self._resolve_expr(s.expr)

    def _visit_IfStmt(self, s):
        self._resolve_expr(s.condition)
        self._resolve_stmt(s.then_branch)
        if s.else_branch: self._resolve_stmt(s.else_branch)

    def _visit_ReturnStmt(self, s):
        if self.current_function == "NONE":
            error_token(s.keyword, "Can't return from top-level code.")
        if s.value is not None:
            if self.current_function == "INITIALIZER":
                error_token(s.keyword, "Can't return a value from an initializer.")
            self._resolve_expr(s.value)

    def _visit_WhileStmt(self, s):
        self._resolve_expr(s.condition)
        self._resolve_stmt(s.body)

    def _visit_ClassStmt(self, s):
        enclosing = self.current_class
        self.current_class = "CLASS"
        self._declare(s.name); self._define(s.name)
        if s.superclass:
            if s.name.lexeme == s.superclass.name.lexeme:
                error_token(s.superclass.name, "A class can't inherit from itself.")
            self.current_class = "SUBCLASS"
            self._resolve_expr(s.superclass)
            self._begin_scope()
            self.scopes[-1]["super"] = True
        self._begin_scope()
        self.scopes[-1]["this"] = True
        for m in s.methods:
            decl = "INITIALIZER" if m.name.lexeme == "init" else "METHOD"
            self._resolve_function(m, decl)
        self._end_scope()
        if s.superclass: self._end_scope()
        self.current_class = enclosing

    # Expression visitors
    def _visit_Variable(self, e):
        if self.scopes and self.scopes[-1].get(e.name.lexeme) is False:
            error_token(e.name, "Can't read local variable in its own initializer.")
        self._resolve_local(e, e.name)

    def _visit_Assign(self, e):
        self._resolve_expr(e.value)
        self._resolve_local(e, e.name)

    def _visit_Binary(self, e):
        self._resolve_expr(e.left); self._resolve_expr(e.right)

    def _visit_Call(self, e):
        self._resolve_expr(e.callee)
        for a in e.arguments: self._resolve_expr(a)

    def _visit_Grouping(self, e): self._resolve_expr(e.expr)
    def _visit_Literal(self, e): pass

    def _visit_Logical(self, e):
        self._resolve_expr(e.left); self._resolve_expr(e.right)

    def _visit_Unary(self, e): self._resolve_expr(e.right)
    def _visit_Get(self, e): self._resolve_expr(e.obj)

    def _visit_Set(self, e):
        self._resolve_expr(e.value); self._resolve_expr(e.obj)

    def _visit_This(self, e):
        if self.current_class == "NONE":
            error_token(e.keyword, "Can't use 'this' outside of a class.")
            return
        self._resolve_local(e, e.keyword)

    def _visit_Super(self, e):
        if self.current_class == "NONE":
            error_token(e.keyword, "Can't use 'super' outside of a class.")
        elif self.current_class != "SUBCLASS":
            error_token(e.keyword, "Can't use 'super' in a class with no superclass.")
        self._resolve_local(e, e.keyword)


# ===== JAVASCRIPT RUNTIME PREAMBLE =====
JS_RUNTIME = r""""use strict";
function lox_truthy(v){return v!==null&&v!==false}
function lox_equal(a,b){
  if(a===null&&b===null)return true;
  if(a===null||b===null)return false;
  if(typeof a!==typeof b)return false;
  return a===b;
}
function lox_stringify(v){
  if(v===null)return"nil";
  if(typeof v==="boolean")return v?"true":"false";
  if(typeof v==="number"){
    let s=String(v);
    if(/\.0$/.test(s))return s.slice(0,-2);
    return s;
  }
  if(v instanceof LoxClass)return v._name;
  if(v instanceof LoxInstance)return v._klass._name+" instance";
  if(typeof v==="function")return v._isNative?"<native fn>":"<fn "+(v._loxName||"")+">";
  return String(v);
}
function lox_print(v){process.stdout.write(lox_stringify(v)+"\n")}
function lox_runtime_error(msg,line){
  process.stderr.write(msg+"\n[line "+line+"]\n");
  process.exit(70);
}
function lox_negate(v,line){
  if(typeof v!=="number")lox_runtime_error("Operand must be a number.",line);
  return -v;
}
function _ck2(l,r,line){
  if(typeof l!=="number"||typeof r!=="number")lox_runtime_error("Operands must be numbers.",line);
}
function lox_sub(l,r,ln){_ck2(l,r,ln);return l-r}
function lox_mul(l,r,ln){_ck2(l,r,ln);return l*r}
function lox_div(l,r,ln){_ck2(l,r,ln);return l/r}
function lox_gt(l,r,ln){_ck2(l,r,ln);return l>r}
function lox_ge(l,r,ln){_ck2(l,r,ln);return l>=r}
function lox_lt(l,r,ln){_ck2(l,r,ln);return l<r}
function lox_le(l,r,ln){_ck2(l,r,ln);return l<=r}
function lox_add(l,r,ln){
  if(typeof l==="number"&&typeof r==="number")return l+r;
  if(typeof l==="string"&&typeof r==="string")return l+r;
  lox_runtime_error("Operands must be two numbers or two strings.",ln);
}
class LoxClass{
  constructor(name,superclass,methods){this._name=name;this._super=superclass;this._methods=methods}
  _findMethod(name){
    if(this._methods.hasOwnProperty(name))return this._methods[name];
    if(this._super)return this._super._findMethod(name);
    return null;
  }
}
class LoxInstance{
  constructor(klass){this._klass=klass;this._fields={}}
  _get(name,line){
    if(this._fields.hasOwnProperty(name))return this._fields[name];
    let m=this._klass._findMethod(name);
    if(m!==null)return m.bind(this);
    lox_runtime_error("Undefined property '"+name+"'.",line);
  }
  _set(name,value){this._fields[name]=value;return value}
}
function lox_call(callee,args,line){
  if(callee instanceof LoxClass){
    let init=callee._findMethod("init");
    let arity=init?(init._loxArity!==undefined?init._loxArity:init.length):0;
    if(args.length!==arity)lox_runtime_error("Expected "+arity+" arguments but got "+args.length+".",line);
    let inst=new LoxInstance(callee);
    if(init)init.call(inst,...args);
    return inst;
  }
  if(typeof callee==="function"){
    let arity=callee._loxArity!==undefined?callee._loxArity:callee.length;
    if(args.length!==arity)lox_runtime_error("Expected "+arity+" arguments but got "+args.length+".",line);
    return callee(...args);
  }
  lox_runtime_error("Can only call functions and classes.",line);
}
function lox_get_prop(obj,name,line){
  if(obj instanceof LoxInstance)return obj._get(name,line);
  lox_runtime_error("Only instances have properties.",line);
}
function lox_set_prop(obj,name,value,line){
  if(!(obj instanceof LoxInstance))lox_runtime_error("Only instances have fields.",line);
  return obj._set(name,value);
}
function lox_super(sc,inst,name,line){
  let m=sc._findMethod(name);
  if(m===null)lox_runtime_error("Undefined property '"+name+"'.",line);
  return m.bind(inst);
}
let _globals={};
_globals["clock"]=function clock(){return Date.now()/1000};
_globals["clock"]._loxArity=0;_globals["clock"]._loxName="clock";_globals["clock"]._isNative=true;
function _gget(n,l){if(!(n in _globals))lox_runtime_error("Undefined variable '"+n+"'.",l);return _globals[n]}
function _gset(n,v,l){if(!(n in _globals))lox_runtime_error("Undefined variable '"+n+"'.",l);_globals[n]=v;return v}
"""


# ===== CODE GENERATOR =====
class CodeGen:
    def __init__(self, local_set):
        self.locals = local_set
        self.depth = 0        # 0 = global scope
        self.in_method = False
        self.in_init = False
        self.super_var = None  # current superclass JS variable name
        self.super_count = 0

    def generate(self, stmts):
        parts = [JS_RUNTIME]
        for s in stmts:
            parts.append(self._stmt(s))
        return "\n".join(parts)

    def _stmt(self, s):
        return getattr(self, f'_s_{type(s).__name__}')(s)

    def _expr(self, e):
        return getattr(self, f'_e_{type(e).__name__}')(e)

    # ---- Statements ----

    def _s_PrintStmt(self, s):
        return f'lox_print({self._expr(s.expr)});'

    def _s_ExpressionStmt(self, s):
        return f'{self._expr(s.expr)};'

    def _s_VarStmt(self, s):
        init = self._expr(s.initializer) if s.initializer else 'null'
        if self.depth == 0:
            return f'_globals["{s.name.lexeme}"]={init};'
        return f'let {s.name.lexeme}={init};'

    def _s_BlockStmt(self, s):
        self.depth += 1
        lines = ['{']
        for st in s.statements:
            lines.append(self._stmt(st))
        lines.append('}')
        self.depth -= 1
        return '\n'.join(lines)

    def _s_IfStmt(self, s):
        c = self._expr(s.condition)
        t = self._stmt(s.then_branch)
        if s.else_branch:
            e = self._stmt(s.else_branch)
            return f'if(lox_truthy({c})){t}else {e}'
        return f'if(lox_truthy({c})){t}'

    def _s_WhileStmt(self, s):
        c = self._expr(s.condition)
        b = self._stmt(s.body)
        return f'while(lox_truthy({c})){b}'

    def _s_FunctionStmt(self, s):
        params = ','.join(p.lexeme for p in s.params)
        self.depth += 1
        body_lines = []
        for st in s.body:
            body_lines.append(self._stmt(st))
        body_lines.append('return null;')
        self.depth -= 1
        body = '\n'.join(body_lines)
        n = s.name.lexeme
        a = len(s.params)
        if self.depth == 0:
            return (f'_globals["{n}"]=function({params}){{\n{body}\n}};\n'
                    f'_globals["{n}"]._loxArity={a};_globals["{n}"]._loxName="{n}";')
        return (f'let {n}=function({params}){{\n{body}\n}};\n'
                f'{n}._loxArity={a};{n}._loxName="{n}";')

    def _s_ReturnStmt(self, s):
        if s.value is None:
            return 'return;' if self.in_init else 'return null;'
        return f'return {self._expr(s.value)};'

    def _s_ClassStmt(self, s):
        old_method, old_init, old_super = self.in_method, self.in_init, self.super_var
        n = s.name.lexeme
        has_super = s.superclass is not None
        lines = []

        if self.depth == 0:
            lines.append(f'_globals["{n}"]=null;')
        else:
            lines.append(f'let {n}=null;')

        lines.append('{')
        self.depth += 1

        super_expr = 'null'
        if has_super:
            sv = f'_super_{self.super_count}'
            self.super_count += 1
            sc = self._expr(s.superclass)
            lines.append(f'let {sv}={sc};')
            lines.append(f'if(!({sv} instanceof LoxClass))lox_runtime_error("Superclass must be a class.",{s.superclass.name.line});')
            super_expr = sv
            self.super_var = sv

        lines.append('let _methods={};')

        for m in s.methods:
            self.in_method = True
            self.in_init = (m.name.lexeme == "init")
            params = ','.join(p.lexeme for p in m.params)
            self.depth += 1
            body_lines = ['let _this=this;']
            for st in m.body:
                body_lines.append(self._stmt(st))
            if not self.in_init:
                body_lines.append('return null;')
            self.depth -= 1
            body = '\n'.join(body_lines)
            mn = m.name.lexeme
            lines.append(f'_methods["{mn}"]=function({params}){{')
            lines.append(body)
            lines.append('};')
            lines.append(f'_methods["{mn}"]._loxArity={len(m.params)};')

        # Assign the class
        if self.depth - 1 == 0:
            lines.append(f'_globals["{n}"]=new LoxClass("{n}",{super_expr},_methods);')
        else:
            lines.append(f'{n}=new LoxClass("{n}",{super_expr},_methods);')

        self.depth -= 1
        lines.append('}')

        self.in_method, self.in_init, self.super_var = old_method, old_init, old_super
        return '\n'.join(lines)

    # ---- Expressions ----

    def _e_Literal(self, e):
        v = e.value
        if v is None: return 'null'
        if isinstance(v, bool): return 'true' if v else 'false'
        if isinstance(v, float):
            if v == int(v) and abs(v) < 2**53:
                return str(int(v))
            return repr(v)
        if isinstance(v, str):
            return json.dumps(v)
        return str(v)

    def _e_Grouping(self, e):
        return f'({self._expr(e.expr)})'

    def _e_Unary(self, e):
        r = self._expr(e.right)
        if e.op.type == TT.MINUS: return f'lox_negate({r},{e.op.line})'
        if e.op.type == TT.BANG: return f'!lox_truthy({r})'
        return 'null'

    def _e_Binary(self, e):
        l = self._expr(e.left)
        r = self._expr(e.right)
        ln = e.op.line
        t = e.op.type
        if t == TT.PLUS: return f'lox_add({l},{r},{ln})'
        if t == TT.MINUS: return f'lox_sub({l},{r},{ln})'
        if t == TT.STAR: return f'lox_mul({l},{r},{ln})'
        if t == TT.SLASH: return f'lox_div({l},{r},{ln})'
        if t == TT.GREATER: return f'lox_gt({l},{r},{ln})'
        if t == TT.GREATER_EQUAL: return f'lox_ge({l},{r},{ln})'
        if t == TT.LESS: return f'lox_lt({l},{r},{ln})'
        if t == TT.LESS_EQUAL: return f'lox_le({l},{r},{ln})'
        if t == TT.EQUAL_EQUAL: return f'lox_equal({l},{r})'
        if t == TT.BANG_EQUAL: return f'!lox_equal({l},{r})'
        return 'null'

    def _e_Variable(self, e):
        if id(e) in self.locals:
            return e.name.lexeme
        return f'_gget("{e.name.lexeme}",{e.name.line})'

    def _e_Assign(self, e):
        v = self._expr(e.value)
        if id(e) in self.locals:
            return f'({e.name.lexeme}={v})'
        return f'_gset("{e.name.lexeme}",{v},{e.name.line})'

    def _e_Logical(self, e):
        l = self._expr(e.left)
        r = self._expr(e.right)
        if e.op.type == TT.OR:
            return f'(()=>{{let _t={l};return lox_truthy(_t)?_t:{r}}})()'
        return f'(()=>{{let _t={l};return !lox_truthy(_t)?_t:{r}}})()'

    def _e_Call(self, e):
        c = self._expr(e.callee)
        args = ','.join(self._expr(a) for a in e.arguments)
        return f'lox_call({c},[{args}],{e.paren.line})'

    def _e_Get(self, e):
        o = self._expr(e.obj)
        return f'lox_get_prop({o},"{e.name.lexeme}",{e.name.line})'

    def _e_Set(self, e):
        o = self._expr(e.obj)
        v = self._expr(e.value)
        return f'lox_set_prop({o},"{e.name.lexeme}",{v},{e.name.line})'

    def _e_This(self, e):
        return '_this'

    def _e_Super(self, e):
        return f'lox_super({self.super_var},_this,"{e.method.lexeme}",{e.keyword.line})'


# ===== MAIN =====
def main():
    global had_error
    if len(sys.argv) != 2:
        print("Usage: lox2js.py <script>", file=sys.stderr)
        sys.exit(64)
    with open(sys.argv[1]) as f:
        source = f.read()

    scanner = Scanner(source)
    tokens = scanner.scan_tokens()
    if had_error: sys.exit(65)

    parser = Parser(tokens)
    statements = parser.parse()
    if had_error: sys.exit(65)

    resolver = Resolver()
    resolver.resolve(statements)
    if had_error: sys.exit(65)

    gen = CodeGen(resolver.locals)
    print(gen.generate(statements))

if __name__ == "__main__":
    main()
