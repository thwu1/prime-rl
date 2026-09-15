"""Lexer for the MiniCalc language."""


class TokenType:
    INT = 'INT'
    IDENT = 'IDENT'
    PLUS = '+'
    MINUS = '-'
    STAR = '*'
    SLASH = '/'
    PERCENT = '%'
    EQ_EQ = '=='
    BANG_EQ = '!='
    LT = '<'
    LE = '<='
    GT = '>'
    GE = '>='
    AND = '&&'
    OR = '||'
    BANG = '!'
    ASSIGN = '='
    LPAREN = '('
    RPAREN = ')'
    LBRACE = '{'
    RBRACE = '}'
    SEMI = ';'
    COMMA = ','
    IF = 'if'
    ELSE = 'else'
    WHILE = 'while'
    FUNC = 'func'
    RETURN = 'return'
    PRINT = 'print'
    EOF = 'EOF'


class Token:
    def __init__(self, type_, value, line):
        self.type = type_
        self.value = value
        self.line = line

    def __repr__(self):
        return f'Token({self.type}, {self.value!r}, line={self.line})'


KEYWORDS = {'if', 'else', 'while', 'func', 'return', 'print'}


class LexerError(Exception):
    pass


class Lexer:
    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.line = 1

    def _skip_ws_comments(self):
        while self.pos < len(self.source):
            c = self.source[self.pos]
            if c in ' \t\r':
                self.pos += 1
            elif c == '\n':
                self.pos += 1
                self.line += 1
            elif (self.pos + 1 < len(self.source) and
                  self.source[self.pos:self.pos + 2] == '//'):
                while self.pos < len(self.source) and self.source[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def next_token(self):
        self._skip_ws_comments()
        if self.pos >= len(self.source):
            return Token(TokenType.EOF, None, self.line)

        c = self.source[self.pos]

        # Two-character tokens (must check before single-char)
        if self.pos + 1 < len(self.source):
            two = self.source[self.pos:self.pos + 2]
            if two == '==':
                self.pos += 2
                return Token(TokenType.EQ_EQ, '==', self.line)
            if two == '!=':
                self.pos += 2
                return Token(TokenType.BANG_EQ, '!=', self.line)
            if two == '<=':
                self.pos += 2
                return Token(TokenType.LE, '<=', self.line)
            if two == '>=':
                self.pos += 2
                return Token(TokenType.GE, '>=', self.line)
            if two == '&&':
                self.pos += 2
                return Token(TokenType.AND, '&&', self.line)
            if two == '||':
                self.pos += 2
                return Token(TokenType.OR, '||', self.line)

        # Single-character tokens
        singles = {
            '+': TokenType.PLUS, '-': TokenType.MINUS, '*': TokenType.STAR,
            '/': TokenType.SLASH, '%': TokenType.PERCENT, '<': TokenType.LT,
            '>': TokenType.GT, '!': TokenType.BANG, '=': TokenType.ASSIGN,
            '(': TokenType.LPAREN, ')': TokenType.RPAREN,
            '{': TokenType.LBRACE, '}': TokenType.RBRACE,
            ';': TokenType.SEMI, ',': TokenType.COMMA,
        }
        if c in singles:
            self.pos += 1
            return Token(singles[c], c, self.line)

        # Integer literal
        if c.isdigit():
            start = self.pos
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                self.pos += 1
            return Token(TokenType.INT, int(self.source[start:self.pos]), self.line)

        # Identifier or keyword
        if c.isalpha() or c == '_':
            start = self.pos
            while (self.pos < len(self.source) and
                   (self.source[self.pos].isalnum() or self.source[self.pos] == '_')):
                self.pos += 1
            word = self.source[start:self.pos]
            if word in KEYWORDS:
                return Token(word, word, self.line)
            return Token(TokenType.IDENT, word, self.line)

        raise LexerError(f"Unexpected character '{c}' at line {self.line}")

    def tokenize(self):
        tokens = []
        while True:
            tok = self.next_token()
            tokens.append(tok)
            if tok.type == TokenType.EOF:
                break
        return tokens
