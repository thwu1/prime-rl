import sys
from .tokens import Token, TokenType, KEYWORDS


class Scanner:
    def __init__(self, source):
        self.source = source
        self.tokens = []
        self.start = 0
        self.current = 0
        self.line = 1
        self.had_error = False

    def scan_tokens(self):
        while not self.is_at_end():
            self.start = self.current
            self.scan_token()
        self.tokens.append(Token(TokenType.EOF, "", None, self.line))
        return self.tokens

    def scan_token(self):
        c = self.advance()
        if c == '(':
            self.add_token(TokenType.LEFT_PAREN)
        elif c == ')':
            self.add_token(TokenType.RIGHT_PAREN)
        elif c == '{':
            self.add_token(TokenType.LEFT_BRACE)
        elif c == '}':
            self.add_token(TokenType.RIGHT_BRACE)
        elif c == ',':
            self.add_token(TokenType.COMMA)
        elif c == '.':
            self.add_token(TokenType.DOT)
        elif c == '-':
            self.add_token(TokenType.MINUS)
        elif c == '+':
            self.add_token(TokenType.PLUS)
        elif c == ';':
            self.add_token(TokenType.SEMICOLON)
        elif c == '*':
            self.add_token(TokenType.STAR)
        elif c == '!':
            self.add_token(TokenType.BANG_EQUAL if self.match('=') else TokenType.BANG)
        elif c == '=':
            self.add_token(TokenType.EQUAL_EQUAL if self.match('=') else TokenType.EQUAL)
        elif c == '<':
            self.add_token(TokenType.LESS_EQUAL if self.match('=') else TokenType.LESS)
        elif c == '>':
            self.add_token(TokenType.GREATER_EQUAL if self.match('=') else TokenType.GREATER)
        elif c == '/':
            if self.match('/'):
                while self.peek() != '\n' and not self.is_at_end():
                    self.advance()
            else:
                self.add_token(TokenType.SLASH)
        elif c in (' ', '\r', '\t'):
            pass
        elif c == '\n':
            self.line += 1
        elif c == '"':
            self.scan_string()
        elif self.is_digit(c):
            self.scan_number()
        elif self.is_alpha(c):
            self.scan_identifier()
        else:
            self.report_error(f"Unexpected character: {c}")

    def scan_string(self):
        while self.peek() != '"' and not self.is_at_end():
            if self.peek() == '\n':
                self.line += 1
            self.advance()
        if self.is_at_end():
            self.report_error("Unterminated string.")
            return
        self.advance()
        value = self.source[self.start + 1:self.current - 1]
        self.add_token_literal(TokenType.STRING, value)

    def scan_number(self):
        while self.is_digit(self.peek()):
            self.advance()
        if self.peek() == '.' and self.is_digit(self.peek_next()):
            self.advance()
            while self.is_digit(self.peek()):
                self.advance()
        self.add_token_literal(TokenType.NUMBER, float(self.source[self.start:self.current]))

    def scan_identifier(self):
        while self.is_alpha_numeric(self.peek()):
            self.advance()
        text = self.source[self.start:self.current]
        ttype = KEYWORDS.get(text, TokenType.IDENTIFIER)
        self.add_token(ttype)

    def add_token(self, ttype):
        self.add_token_literal(ttype, None)

    def add_token_literal(self, ttype, literal):
        text = self.source[self.start:self.current]
        self.tokens.append(Token(ttype, text, literal, self.line))

    def advance(self):
        c = self.source[self.current]
        self.current += 1
        return c

    def match(self, expected):
        if self.is_at_end():
            return False
        if self.source[self.current] != expected:
            return False
        self.current += 1
        return True

    def peek(self):
        if self.is_at_end():
            return '\0'
        return self.source[self.current]

    def peek_next(self):
        if self.current + 1 >= len(self.source):
            return '\0'
        return self.source[self.current + 1]

    def is_digit(self, c):
        return '0' <= c <= '9'

    def is_alpha(self, c):
        return ('a' <= c <= 'z') or ('A' <= c <= 'Z') or c == '_'

    def is_alpha_numeric(self, c):
        return self.is_alpha(c) or self.is_digit(c)

    def is_at_end(self):
        return self.current >= len(self.source)

    def report_error(self, message):
        print(f"[line {self.line}] Error: {message}", file=sys.stderr)
        self.had_error = True
