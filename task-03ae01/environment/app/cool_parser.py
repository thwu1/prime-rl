"""
Cool language parser. Produces dict-based ASTs from .cl source files.
See ast_format.md for the AST node format.
"""


class Token:
    __slots__ = ('type', 'value', 'line')

    def __init__(self, type, value, line):
        self.type = type
        self.value = value
        self.line = line

    def __repr__(self):
        return f'Token({self.type}, {self.value!r}, line={self.line})'


KEYWORDS = {
    'class', 'else', 'fi', 'if', 'in', 'inherits', 'isvoid', 'let',
    'loop', 'pool', 'then', 'while', 'case', 'esac', 'new', 'of', 'not',
}


def tokenize(source):
    tokens = []
    i = 0
    line = 1
    n = len(source)

    while i < n:
        c = source[i]

        # Whitespace
        if c in ' \t\r':
            i += 1
            continue
        if c == '\n':
            line += 1
            i += 1
            continue

        # Single-line comment
        if c == '-' and i + 1 < n and source[i + 1] == '-':
            i += 2
            while i < n and source[i] != '\n':
                i += 1
            continue

        # Block comment (nested)
        if c == '(' and i + 1 < n and source[i + 1] == '*':
            depth = 1
            i += 2
            while i < n and depth > 0:
                if source[i] == '(' and i + 1 < n and source[i + 1] == '*':
                    depth += 1
                    i += 2
                elif source[i] == '*' and i + 1 < n and source[i + 1] == ')':
                    depth -= 1
                    i += 2
                else:
                    if source[i] == '\n':
                        line += 1
                    i += 1
            continue

        # String literal
        if c == '"':
            start_line = line
            i += 1
            s = ''
            while i < n and source[i] != '"':
                if source[i] == '\\' and i + 1 < n:
                    i += 1
                    esc = source[i]
                    if esc == 'n':
                        s += '\n'
                    elif esc == 't':
                        s += '\t'
                    elif esc == '\\':
                        s += '\\'
                    elif esc == '"':
                        s += '"'
                    elif esc == '\n':
                        s += '\n'
                        line += 1
                    else:
                        s += esc
                elif source[i] == '\n':
                    s += '\n'
                    line += 1
                else:
                    s += source[i]
                i += 1
            if i < n:
                i += 1  # consume closing "
            tokens.append(Token('STRING', s, start_line))
            continue

        # Integer literal
        if c.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            tokens.append(Token('INTEGER', int(source[i:j]), line))
            i = j
            continue

        # Identifier or keyword
        if c.isalpha() or c == '_':
            j = i
            while j < n and (source[j].isalnum() or source[j] == '_'):
                j += 1
            word = source[i:j]
            lower = word.lower()
            if lower == 'true':
                tokens.append(Token('BOOL_CONST', True, line))
            elif lower == 'false':
                tokens.append(Token('BOOL_CONST', False, line))
            elif lower in KEYWORDS:
                tokens.append(Token(lower.upper(), word, line))
            elif word[0].isupper():
                tokens.append(Token('TYPEID', word, line))
            else:
                tokens.append(Token('OBJECTID', word, line))
            i = j
            continue

        # Multi-character operators
        if c == '=' and i + 1 < n and source[i + 1] == '>':
            tokens.append(Token('DARROW', '=>', line))
            i += 2
            continue
        if c == '<' and i + 1 < n and source[i + 1] == '-':
            tokens.append(Token('ASSIGN', '<-', line))
            i += 2
            continue
        if c == '<' and i + 1 < n and source[i + 1] == '=':
            tokens.append(Token('LE', '<=', line))
            i += 2
            continue

        # Single-character operators and symbols
        if c in '+-*/~<>=@.;:,(){}':
            tokens.append(Token(c, c, line))
            i += 1
            continue

        # Skip unknown characters
        i += 1

    tokens.append(Token('EOF', None, line))
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, ttype):
        t = self.peek()
        if t.type != ttype:
            raise SyntaxError(
                f"Expected {ttype}, got {t.type} ({t.value!r}) at line {t.line}"
            )
        return self.advance()

    def match(self, ttype):
        if self.peek().type == ttype:
            return self.advance()
        return None

    # ---- Program ----

    def parse_program(self):
        classes = []
        while self.peek().type != 'EOF':
            classes.append(self.parse_class())
        return {"kind": "program", "classes": classes}

    def parse_class(self):
        line = self.peek().line
        self.expect('CLASS')
        name = self.expect('TYPEID').value
        parent = None
        if self.match('INHERITS'):
            parent = self.expect('TYPEID').value
        self.expect('{')
        features = []
        while self.peek().type != '}':
            features.append(self.parse_feature())
            self.expect(';')
        self.expect('}')
        self.expect(';')
        return {"kind": "class", "name": name, "parent": parent,
                "features": features, "line": line}

    def parse_feature(self):
        line = self.peek().line
        name_tok = self.expect('OBJECTID')
        if self.peek().type == '(':
            # Method
            self.advance()
            formals = []
            if self.peek().type != ')':
                formals.append(self.parse_formal())
                while self.match(','):
                    formals.append(self.parse_formal())
            self.expect(')')
            self.expect(':')
            ret_type = self.expect('TYPEID').value
            self.expect('{')
            body = self.parse_expr()
            self.expect('}')
            return {"kind": "method", "name": name_tok.value,
                    "formals": formals, "return_type": ret_type,
                    "body": body, "line": line}
        else:
            # Attribute
            self.expect(':')
            type_decl = self.expect('TYPEID').value
            init = None
            if self.match('ASSIGN'):
                init = self.parse_expr()
            return {"kind": "attr", "name": name_tok.value,
                    "type_decl": type_decl, "init": init, "line": line}

    def parse_formal(self):
        name = self.expect('OBJECTID').value
        self.expect(':')
        type_decl = self.expect('TYPEID').value
        return {"name": name, "type": type_decl}

    # ---- Expressions (precedence climbing) ----

    def parse_expr(self):
        return self.parse_assign()

    def parse_assign(self):
        if (self.peek().type == 'OBJECTID'
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].type == 'ASSIGN'):
            line = self.peek().line
            name = self.advance().value
            self.advance()  # consume <-
            rhs = self.parse_assign()
            return {"kind": "assign", "name": name, "expr": rhs, "line": line}
        return self.parse_not()

    def parse_not(self):
        if self.peek().type == 'NOT':
            line = self.peek().line
            self.advance()
            e = self.parse_not()
            return {"kind": "not", "expr": e, "line": line}
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_add()
        t = self.peek()
        if t.type == 'LE':
            self.advance()
            right = self.parse_add()
            return {"kind": "le", "left": left, "right": right, "line": t.line}
        if t.type == '<':
            self.advance()
            right = self.parse_add()
            return {"kind": "lt", "left": left, "right": right, "line": t.line}
        if t.type == '=':
            self.advance()
            right = self.parse_add()
            return {"kind": "eq", "left": left, "right": right, "line": t.line}
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.peek().type in ('+', '-'):
            line = self.peek().line
            op = self.advance().type
            right = self.parse_mul()
            kind = "plus" if op == '+' else "sub"
            left = {"kind": kind, "left": left, "right": right, "line": line}
        return left

    def parse_mul(self):
        left = self.parse_isvoid()
        while self.peek().type in ('*', '/'):
            line = self.peek().line
            op = self.advance().type
            right = self.parse_isvoid()
            kind = "mul" if op == '*' else "div"
            left = {"kind": kind, "left": left, "right": right, "line": line}
        return left

    def parse_isvoid(self):
        if self.peek().type == 'ISVOID':
            line = self.peek().line
            self.advance()
            e = self.parse_isvoid()
            return {"kind": "isvoid", "expr": e, "line": line}
        return self.parse_neg()

    def parse_neg(self):
        if self.peek().type == '~':
            line = self.peek().line
            self.advance()
            e = self.parse_neg()
            return {"kind": "neg", "expr": e, "line": line}
        return self.parse_dispatch()

    def parse_dispatch(self):
        expr = self.parse_primary()
        while True:
            line = self.peek().line
            if self.peek().type == '.':
                self.advance()
                method = self.expect('OBJECTID').value
                self.expect('(')
                args = self._parse_args()
                self.expect(')')
                expr = {"kind": "dispatch", "object": expr,
                        "method": method, "args": args, "line": line}
            elif self.peek().type == '@':
                self.advance()
                tname = self.expect('TYPEID').value
                self.expect('.')
                method = self.expect('OBJECTID').value
                self.expect('(')
                args = self._parse_args()
                self.expect(')')
                expr = {"kind": "static_dispatch", "object": expr,
                        "type_name": tname, "method": method,
                        "args": args, "line": line}
            else:
                break
        return expr

    def _parse_args(self):
        args = []
        if self.peek().type != ')':
            args.append(self.parse_expr())
            while self.match(','):
                args.append(self.parse_expr())
        return args

    def parse_primary(self):
        t = self.peek()
        line = t.line

        if t.type == 'INTEGER':
            self.advance()
            return {"kind": "int_const", "value": t.value, "line": line}

        if t.type == 'STRING':
            self.advance()
            return {"kind": "string_const", "value": t.value, "line": line}

        if t.type == 'BOOL_CONST':
            self.advance()
            return {"kind": "bool_const", "value": t.value, "line": line}

        if t.type == 'OBJECTID':
            if t.value == 'self':
                self.advance()
                return {"kind": "self", "line": line}
            # Self-dispatch: name(args)
            if (self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].type == '('):
                name = self.advance().value
                self.expect('(')
                args = self._parse_args()
                self.expect(')')
                return {"kind": "self_dispatch", "method": name,
                        "args": args, "line": line}
            self.advance()
            return {"kind": "identifier", "name": t.value, "line": line}

        if t.type == 'IF':
            self.advance()
            pred = self.parse_expr()
            self.expect('THEN')
            then_e = self.parse_expr()
            self.expect('ELSE')
            else_e = self.parse_expr()
            self.expect('FI')
            return {"kind": "cond", "predicate": pred,
                    "then_expr": then_e, "else_expr": else_e, "line": line}

        if t.type == 'WHILE':
            self.advance()
            pred = self.parse_expr()
            self.expect('LOOP')
            body = self.parse_expr()
            self.expect('POOL')
            return {"kind": "loop", "predicate": pred,
                    "body": body, "line": line}

        if t.type == '{':
            self.advance()
            exprs = [self.parse_expr()]
            self.expect(';')
            while self.peek().type != '}':
                exprs.append(self.parse_expr())
                self.expect(';')
            self.expect('}')
            return {"kind": "block", "body": exprs, "line": line}

        if t.type == 'LET':
            self.advance()
            return self._parse_let_rest(line)

        if t.type == 'CASE':
            self.advance()
            expr = self.parse_expr()
            self.expect('OF')
            branches = []
            while self.peek().type != 'ESAC':
                bname = self.expect('OBJECTID').value
                self.expect(':')
                btype = self.expect('TYPEID').value
                self.expect('DARROW')
                bbody = self.parse_expr()
                self.expect(';')
                branches.append({"name": bname, "type_decl": btype,
                                 "body": bbody})
            self.expect('ESAC')
            return {"kind": "case", "expr": expr,
                    "branches": branches, "line": line}

        if t.type == 'NEW':
            self.advance()
            tname = self.expect('TYPEID').value
            return {"kind": "new", "type_name": tname, "line": line}

        if t.type == '(':
            self.advance()
            expr = self.parse_expr()
            self.expect(')')
            return expr

        raise SyntaxError(
            f"Unexpected token {t.type} ({t.value!r}) at line {t.line}"
        )

    def _parse_let_rest(self, line):
        name = self.expect('OBJECTID').value
        self.expect(':')
        type_decl = self.expect('TYPEID').value
        init = None
        if self.match('ASSIGN'):
            init = self.parse_expr()
        if self.match(','):
            body = self._parse_let_rest(line)
        else:
            self.expect('IN')
            body = self.parse_expr()
        binding = {"name": name, "type_decl": type_decl, "init": init}
        return {"kind": "let", "binding": binding, "body": body, "line": line}


def parse(source):
    """Parse Cool source code and return a dict-based AST."""
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse_program()


def parse_file(filename):
    """Parse a Cool source file and return a dict-based AST."""
    with open(filename) as f:
        return parse(f.read())
