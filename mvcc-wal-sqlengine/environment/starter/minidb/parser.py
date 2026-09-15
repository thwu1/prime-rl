from dataclasses import dataclass
from typing import Any, Optional, List
from .types import Token, TokenType, ColumnType, ColumnDef


@dataclass
class CreateTableStmt:
    table_name: str
    columns: List[ColumnDef]


@dataclass
class InsertStmt:
    table_name: str
    columns: Optional[List[str]]
    values: List[Any]


@dataclass
class SelectStmt:
    table_name: str
    columns: List[str]
    where: Optional[Any] = None


@dataclass
class UpdateStmt:
    table_name: str
    assignments: List[tuple]
    where: Optional[Any] = None


@dataclass
class DeleteStmt:
    table_name: str
    where: Optional[Any] = None


@dataclass
class BinaryExpr:
    column: str
    op: str
    value: Any


@dataclass
class LogicalExpr:
    left: Any
    op: str
    right: Any


class Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, tt: TokenType) -> Token:
        t = self.advance()
        if t.type != tt:
            raise SyntaxError(f"Expected {tt.name}, got {t.type.name} ('{t.value}')")
        return t

    def parse(self):
        t = self.peek()
        if t.type == TokenType.CREATE:
            return self._create_table()
        elif t.type == TokenType.INSERT:
            return self._insert()
        elif t.type == TokenType.SELECT:
            return self._select()
        elif t.type == TokenType.UPDATE:
            return self._update()
        elif t.type == TokenType.DELETE:
            return self._delete()
        else:
            raise SyntaxError(f"Unexpected token: {t.type.name} ('{t.value}')")

    def _create_table(self):
        self.expect(TokenType.CREATE)
        self.expect(TokenType.TABLE)
        name = self.expect(TokenType.IDENT).value
        self.expect(TokenType.LPAREN)
        cols = []
        while True:
            col_name = self.expect(TokenType.IDENT).value
            type_tok = self.advance()
            type_map = {
                TokenType.INT_TYPE: ColumnType.INTEGER,
                TokenType.TEXT_TYPE: ColumnType.TEXT,
                TokenType.BOOLEAN_TYPE: ColumnType.BOOLEAN,
            }
            if type_tok.type not in type_map:
                raise SyntaxError(f"Unknown column type: {type_tok.value}")
            cols.append(ColumnDef(col_name, type_map[type_tok.type]))
            if self.peek().type == TokenType.COMMA:
                self.advance()
            else:
                break
        self.expect(TokenType.RPAREN)
        return CreateTableStmt(name, cols)

    def _insert(self):
        self.expect(TokenType.INSERT)
        self.expect(TokenType.INTO)
        table = self.expect(TokenType.IDENT).value
        columns = None
        if self.peek().type == TokenType.LPAREN:
            self.advance()
            columns = [self.expect(TokenType.IDENT).value]
            while self.peek().type == TokenType.COMMA:
                self.advance()
                columns.append(self.expect(TokenType.IDENT).value)
            self.expect(TokenType.RPAREN)
        self.expect(TokenType.VALUES)
        self.expect(TokenType.LPAREN)
        values = [self._literal()]
        while self.peek().type == TokenType.COMMA:
            self.advance()
            values.append(self._literal())
        self.expect(TokenType.RPAREN)
        return InsertStmt(table, columns, values)

    def _select(self):
        self.expect(TokenType.SELECT)
        cols = []
        if self.peek().type == TokenType.STAR:
            self.advance()
            cols = ['*']
        else:
            cols = [self.expect(TokenType.IDENT).value]
            while self.peek().type == TokenType.COMMA:
                self.advance()
                cols.append(self.expect(TokenType.IDENT).value)
        self.expect(TokenType.FROM)
        table = self.expect(TokenType.IDENT).value
        where = None
        if self.peek().type == TokenType.WHERE:
            self.advance()
            where = self._where_expr()
        return SelectStmt(table, cols, where)

    def _update(self):
        self.expect(TokenType.UPDATE)
        table = self.expect(TokenType.IDENT).value
        self.expect(TokenType.SET)
        assignments = []
        col = self.expect(TokenType.IDENT).value
        self.expect(TokenType.EQ)
        val = self._literal()
        assignments.append((col, val))
        while self.peek().type == TokenType.COMMA:
            self.advance()
            col = self.expect(TokenType.IDENT).value
            self.expect(TokenType.EQ)
            val = self._literal()
            assignments.append((col, val))
        where = None
        if self.peek().type == TokenType.WHERE:
            self.advance()
            where = self._where_expr()
        return UpdateStmt(table, assignments, where)

    def _delete(self):
        self.expect(TokenType.DELETE)
        self.expect(TokenType.FROM)
        table = self.expect(TokenType.IDENT).value
        where = None
        if self.peek().type == TokenType.WHERE:
            self.advance()
            where = self._where_expr()
        return DeleteStmt(table, where)

    def _where_expr(self):
        left = self._comparison()
        while self.peek().type in (TokenType.AND, TokenType.OR):
            op = self.advance().value.upper()
            right = self._comparison()
            left = LogicalExpr(left, op, right)
        return left

    def _comparison(self):
        col = self.expect(TokenType.IDENT).value
        op_map = {
            TokenType.EQ: '=', TokenType.NEQ: '!=',
            TokenType.LT: '<', TokenType.GT: '>',
            TokenType.LTE: '<=', TokenType.GTE: '>=',
        }
        op_tok = self.advance()
        if op_tok.type not in op_map:
            raise SyntaxError(f"Expected comparison operator, got {op_tok.type.name}")
        return BinaryExpr(col, op_map[op_tok.type], self._literal())

    def _literal(self):
        t = self.advance()
        if t.type == TokenType.INTEGER_LIT:
            return int(t.value)
        elif t.type == TokenType.STRING_LIT:
            return t.value
        elif t.type == TokenType.TRUE:
            return True
        elif t.type == TokenType.FALSE:
            return False
        elif t.type == TokenType.NULL:
            return None
        else:
            raise SyntaxError(f"Expected literal, got {t.type.name} ('{t.value}')")


def parse(tokens: list):
    return Parser(tokens).parse()
