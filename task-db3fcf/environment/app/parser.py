"""Recursive-descent parser for MiniCalc with operator precedence."""

from lexer import TokenType
from ast_nodes import (
    Program, FuncDef, AssignStmt, IfStmt, WhileStmt, ReturnStmt,
    PrintStmt, IntLit, VarRef, BinOp, UnaryOp, FuncCall,
)


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, type_):
        tok = self.advance()
        if tok.type != type_:
            raise ParseError(
                f"Expected {type_}, got {tok.type} ({tok.value!r}) at line {tok.line}")
        return tok

    def parse(self):
        functions = []
        main_body = []
        while self.peek().type != TokenType.EOF:
            if self.peek().type == TokenType.FUNC:
                functions.append(self._parse_func())
            else:
                main_body.append(self._parse_stmt())
        return Program(functions, main_body)

    def _parse_func(self):
        self.expect(TokenType.FUNC)
        name = self.expect(TokenType.IDENT).value
        self.expect(TokenType.LPAREN)
        params = []
        if self.peek().type != TokenType.RPAREN:
            params.append(self.expect(TokenType.IDENT).value)
            while self.peek().type == TokenType.COMMA:
                self.advance()
                params.append(self.expect(TokenType.IDENT).value)
        self.expect(TokenType.RPAREN)
        body = self._parse_block()
        return FuncDef(name, params, body)

    def _parse_block(self):
        self.expect(TokenType.LBRACE)
        stmts = []
        while self.peek().type != TokenType.RBRACE:
            stmts.append(self._parse_stmt())
        self.expect(TokenType.RBRACE)
        return stmts

    def _parse_stmt(self):
        tok = self.peek()
        if tok.type == TokenType.IF:
            return self._parse_if()
        if tok.type == TokenType.WHILE:
            return self._parse_while()
        if tok.type == TokenType.RETURN:
            return self._parse_return()
        if tok.type == TokenType.PRINT:
            return self._parse_print()
        if tok.type == TokenType.IDENT:
            return self._parse_assign()
        raise ParseError(f"Unexpected token {tok.type} at line {tok.line}")

    def _parse_if(self):
        self.expect(TokenType.IF)
        self.expect(TokenType.LPAREN)
        cond = self._parse_expr()
        self.expect(TokenType.RPAREN)
        then_body = self._parse_block()
        else_body = None
        if self.peek().type == TokenType.ELSE:
            self.advance()
            if self.peek().type == TokenType.IF:
                else_body = [self._parse_if()]
            else:
                else_body = self._parse_block()
        return IfStmt(cond, then_body, else_body)

    def _parse_while(self):
        self.expect(TokenType.WHILE)
        self.expect(TokenType.LPAREN)
        cond = self._parse_expr()
        self.expect(TokenType.RPAREN)
        body = self._parse_block()
        return WhileStmt(cond, body)

    def _parse_return(self):
        self.expect(TokenType.RETURN)
        expr = self._parse_expr()
        self.expect(TokenType.SEMI)
        return ReturnStmt(expr)

    def _parse_print(self):
        self.expect(TokenType.PRINT)
        exprs = [self._parse_expr()]
        while self.peek().type == TokenType.COMMA:
            self.advance()
            exprs.append(self._parse_expr())
        self.expect(TokenType.SEMI)
        return PrintStmt(exprs)

    def _parse_assign(self):
        name = self.expect(TokenType.IDENT).value
        self.expect(TokenType.ASSIGN)
        expr = self._parse_expr()
        self.expect(TokenType.SEMI)
        return AssignStmt(name, expr)

    # Expression parsing with operator precedence (lowest to highest)

    def _parse_expr(self):
        return self._parse_or()

    def _parse_or(self):
        left = self._parse_and()
        while self.peek().type == TokenType.OR:
            self.advance()
            right = self._parse_and()
            left = BinOp('||', left, right)
        return left

    def _parse_and(self):
        left = self._parse_equality()
        while self.peek().type == TokenType.AND:
            self.advance()
            right = self._parse_equality()
            left = BinOp('&&', left, right)
        return left

    def _parse_equality(self):
        left = self._parse_comparison()
        while self.peek().type in (TokenType.EQ_EQ, TokenType.BANG_EQ):
            op = self.advance().value
            right = self._parse_comparison()
            left = BinOp(op, left, right)
        return left

    def _parse_comparison(self):
        left = self._parse_addition()
        while self.peek().type in (TokenType.LT, TokenType.LE, TokenType.GT, TokenType.GE):
            op = self.advance().value
            right = self._parse_addition()
            left = BinOp(op, left, right)
        return left

    def _parse_addition(self):
        left = self._parse_multiplication()
        while self.peek().type in (TokenType.PLUS, TokenType.MINUS):
            op = self.advance().value
            right = self._parse_multiplication()
            left = BinOp(op, left, right)
        return left

    def _parse_multiplication(self):
        left = self._parse_unary()
        while self.peek().type in (TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self.advance().value
            right = self._parse_unary()
            left = BinOp(op, left, right)
        return left

    def _parse_unary(self):
        if self.peek().type == TokenType.MINUS:
            self.advance()
            operand = self._parse_unary()
            return UnaryOp('-', operand)
        if self.peek().type == TokenType.BANG:
            self.advance()
            operand = self._parse_unary()
            return UnaryOp('!', operand)
        return self._parse_primary()

    def _parse_primary(self):
        tok = self.peek()
        if tok.type == TokenType.INT:
            self.advance()
            return IntLit(tok.value)
        if tok.type == TokenType.IDENT:
            self.advance()
            if self.peek().type == TokenType.LPAREN:
                self.advance()
                args = []
                if self.peek().type != TokenType.RPAREN:
                    args.append(self._parse_expr())
                    while self.peek().type == TokenType.COMMA:
                        self.advance()
                        args.append(self._parse_expr())
                self.expect(TokenType.RPAREN)
                return FuncCall(tok.value, args)
            return VarRef(tok.value)
        if tok.type == TokenType.LPAREN:
            self.advance()
            expr = self._parse_expr()
            self.expect(TokenType.RPAREN)
            return expr
        raise ParseError(f"Unexpected token {tok.type} ({tok.value!r}) at line {tok.line}")
