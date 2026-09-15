"""
Parser for the IR language used in the abstract interpretation task.


IR Syntax:
  program    := func_def*
  func_def   := 'func' NAME '(' params ')' '{' stmts '}'
  params     := NAME (',' NAME)* | empty
  stmts      := stmt*
  stmt       := assign | if_stmt | while_stmt | return_stmt
  assign     := NAME ':=' expr
  expr       := INTEGER | NAME | NAME OP NAME | 'call' NAME '(' args ')'
  OP         := '+' | '-' | '*'
  if_stmt    := 'if' cond '{' stmts '}' ('else' '{' stmts '}')?
  while_stmt := 'while' cond '{' stmts '}'
  return_stmt:= 'return' NAME
  cond       := NAME CMPOP (NAME | INTEGER)
  CMPOP      := '<' | '<=' | '>' | '>=' | '==' | '!='
  args       := NAME (',' NAME)* | empty

AST Schema:
  Program = {"functions": {name: Function, ...}}
  Function = {"name": str, "params": [str], "body": [Stmt]}

  Stmt is one of:
    {"type": "assign", "target": str, "expr": Expr, "line": int}
    {"type": "if", "cond": Cond, "then_body": [Stmt], "else_body": [Stmt], "line": int}
    {"type": "while", "cond": Cond, "body": [Stmt], "line": int}
    {"type": "return", "var": str, "line": int}

  Expr is one of:
    {"type": "const", "value": int}
    {"type": "var", "name": str}
    {"type": "binop", "op": str, "left": str, "right": str}
    {"type": "call", "func": str, "args": [str]}

  Cond = {"left": str, "op": str, "right": {"type":"var","name":str} | {"type":"const","value":int}}
"""

import sys
import json


class Token:
    __slots__ = ('type', 'value', 'line')

    def __init__(self, type, value, line):
        self.type = type
        self.value = value
        self.line = line

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, line={self.line})"


def tokenize(source):
    tokens = []
    line = 1
    i = 0
    while i < len(source):
        if source[i] in ' \t\r':
            i += 1
            continue
        if source[i] == '\n':
            line += 1
            i += 1
            continue
        if source[i] == '#':
            while i < len(source) and source[i] != '\n':
                i += 1
            continue
        if source[i:i+2] == ':=':
            tokens.append(Token('ASSIGN', ':=', line))
            i += 2
            continue
        if source[i:i+2] in ('<=', '>=', '==', '!='):
            tokens.append(Token('CMPOP', source[i:i+2], line))
            i += 2
            continue
        if source[i] in '+-*':
            tokens.append(Token('OP', source[i], line))
            i += 1
            continue
        if source[i] in '<>':
            tokens.append(Token('CMPOP', source[i], line))
            i += 1
            continue
        if source[i] == '(':
            tokens.append(Token('LPAREN', '(', line))
            i += 1
            continue
        if source[i] == ')':
            tokens.append(Token('RPAREN', ')', line))
            i += 1
            continue
        if source[i] == '{':
            tokens.append(Token('LBRACE', '{', line))
            i += 1
            continue
        if source[i] == '}':
            tokens.append(Token('RBRACE', '}', line))
            i += 1
            continue
        if source[i] == ',':
            tokens.append(Token('COMMA', ',', line))
            i += 1
            continue
        if source[i].isdigit():
            j = i
            while i < len(source) and source[i].isdigit():
                i += 1
            tokens.append(Token('INT', int(source[j:i]), line))
            continue
        if source[i].isalpha() or source[i] == '_':
            j = i
            while i < len(source) and (source[i].isalnum() or source[i] == '_'):
                i += 1
            word = source[j:i]
            if word in ('func', 'if', 'else', 'while', 'return', 'call'):
                tokens.append(Token(word.upper(), word, line))
            else:
                tokens.append(Token('NAME', word, line))
            continue
        raise SyntaxError(f"Unexpected character {source[i]!r} at line {line}")

    tokens.append(Token('EOF', None, line))
    return tokens


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

    def expect(self, type):
        tok = self.advance()
        if tok.type != type:
            raise SyntaxError(
                f"Expected {type}, got {tok.type} ({tok.value!r}) at line {tok.line}"
            )
        return tok

    def parse_program(self):
        functions = {}
        while self.peek().type != 'EOF':
            func = self.parse_func_def()
            functions[func['name']] = func
        return {"functions": functions}

    def parse_func_def(self):
        self.expect('FUNC')
        name = self.expect('NAME').value
        self.expect('LPAREN')
        params = self.parse_params()
        self.expect('RPAREN')
        self.expect('LBRACE')
        body = self.parse_stmts()
        self.expect('RBRACE')
        return {"name": name, "params": params, "body": body}

    def parse_params(self):
        params = []
        if self.peek().type == 'NAME':
            params.append(self.advance().value)
            while self.peek().type == 'COMMA':
                self.advance()
                params.append(self.expect('NAME').value)
        return params

    def parse_stmts(self):
        stmts = []
        while self.peek().type not in ('RBRACE', 'EOF'):
            stmts.append(self.parse_stmt())
        return stmts

    def parse_stmt(self):
        tok = self.peek()
        if tok.type == 'NAME':
            return self.parse_assign()
        elif tok.type == 'IF':
            return self.parse_if()
        elif tok.type == 'WHILE':
            return self.parse_while()
        elif tok.type == 'RETURN':
            return self.parse_return()
        else:
            raise SyntaxError(
                f"Unexpected token {tok.type} ({tok.value!r}) at line {tok.line}"
            )

    def parse_assign(self):
        line = self.peek().line
        target = self.expect('NAME').value
        self.expect('ASSIGN')
        expr = self.parse_expr()
        return {"type": "assign", "target": target, "expr": expr, "line": line}

    def parse_expr(self):
        tok = self.peek()
        if tok.type == 'INT':
            self.advance()
            return {"type": "const", "value": tok.value}
        elif tok.type == 'CALL':
            return self.parse_call()
        elif tok.type == 'NAME':
            name = self.advance().value
            if self.peek().type == 'OP':
                op = self.advance().value
                right = self.expect('NAME').value
                return {"type": "binop", "op": op, "left": name, "right": right}
            else:
                return {"type": "var", "name": name}
        else:
            raise SyntaxError(
                f"Unexpected token in expression: {tok.type} at line {tok.line}"
            )

    def parse_call(self):
        self.expect('CALL')
        func_name = self.expect('NAME').value
        self.expect('LPAREN')
        args = []
        if self.peek().type == 'NAME':
            args.append(self.advance().value)
            while self.peek().type == 'COMMA':
                self.advance()
                args.append(self.expect('NAME').value)
        self.expect('RPAREN')
        return {"type": "call", "func": func_name, "args": args}

    def parse_cond(self):
        left = self.expect('NAME').value
        op = self.expect('CMPOP').value
        tok = self.peek()
        if tok.type == 'INT':
            self.advance()
            right = {"type": "const", "value": tok.value}
        elif tok.type == 'NAME':
            self.advance()
            right = {"type": "var", "name": tok.value}
        else:
            raise SyntaxError(
                f"Expected NAME or INT in condition, got {tok.type} at line {tok.line}"
            )
        return {"left": left, "op": op, "right": right}

    def parse_if(self):
        line = self.peek().line
        self.expect('IF')
        cond = self.parse_cond()
        self.expect('LBRACE')
        then_body = self.parse_stmts()
        self.expect('RBRACE')
        else_body = []
        if self.peek().type == 'ELSE':
            self.advance()
            self.expect('LBRACE')
            else_body = self.parse_stmts()
            self.expect('RBRACE')
        return {
            "type": "if", "cond": cond,
            "then_body": then_body, "else_body": else_body, "line": line
        }

    def parse_while(self):
        line = self.peek().line
        self.expect('WHILE')
        cond = self.parse_cond()
        self.expect('LBRACE')
        body = self.parse_stmts()
        self.expect('RBRACE')
        return {"type": "while", "cond": cond, "body": body, "line": line}

    def parse_return(self):
        line = self.peek().line
        self.expect('RETURN')
        var = self.expect('NAME').value
        return {"type": "return", "var": var, "line": line}


def parse_file(filename):
    """Parse an IR file and return the AST."""
    with open(filename) as f:
        source = f.read()
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse_program()


def parse_string(source):
    """Parse an IR string and return the AST."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse_program()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python ir_parser.py <file.ir>")
        sys.exit(1)
    ast = parse_file(sys.argv[1])
    print(json.dumps(ast, indent=2))
