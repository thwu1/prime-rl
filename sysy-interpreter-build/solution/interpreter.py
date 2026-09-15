#!/usr/bin/env python3
"""Complete SysY Language Interpreter."""
import sys


# ── Control flow signals ──────────────────────────────────────────────
class BreakSignal(Exception):
    pass

class ContinueSignal(Exception):
    pass

class ReturnSignal(Exception):
    def __init__(self, val=None):
        self.val = val


# ── Lexer ─────────────────────────────────────────────────────────────
KEYWORDS = frozenset(
    ['int', 'void', 'const', 'if', 'else', 'while',
     'break', 'continue', 'return']
)


class Token:
    __slots__ = ('ty', 'val', 'line')

    def __init__(self, ty, val, line):
        self.ty = ty
        self.val = val
        self.line = line


def tokenize(source):
    tokens = []
    i, n, line = 0, len(source), 1
    while i < n:
        c = source[i]
        # Whitespace
        if c in ' \t\r':
            i += 1
            continue
        if c == '\n':
            i += 1
            line += 1
            continue
        # Preprocessor directives – skip entire line
        if c == '#':
            while i < n and source[i] != '\n':
                i += 1
            continue
        # Comments
        if c == '/' and i + 1 < n:
            if source[i + 1] == '/':
                i += 2
                while i < n and source[i] != '\n':
                    i += 1
                continue
            if source[i + 1] == '*':
                i += 2
                while i + 1 < n:
                    if source[i] == '*' and source[i + 1] == '/':
                        i += 2
                        break
                    if source[i] == '\n':
                        line += 1
                    i += 1
                continue
        # Integer literals
        if c.isdigit():
            start = i
            if c == '0' and i + 1 < n and source[i + 1] in 'xX':
                i += 2
                while i < n and source[i] in '0123456789abcdefABCDEF':
                    i += 1
                tokens.append(Token('NUM', int(source[start:i], 16), line))
            elif c == '0' and i + 1 < n and source[i + 1] in '01234567':
                i += 1
                while i < n and source[i] in '01234567':
                    i += 1
                tokens.append(Token('NUM', int(source[start:i], 8), line))
            else:
                while i < n and source[i].isdigit():
                    i += 1
                tokens.append(Token('NUM', int(source[start:i]), line))
            continue
        # Identifiers / keywords
        if c.isalpha() or c == '_':
            start = i
            while i < n and (source[i].isalnum() or source[i] == '_'):
                i += 1
            word = source[start:i]
            tokens.append(
                Token(word if word in KEYWORDS else 'ID', word, line)
            )
            continue
        # Two-character operators
        if i + 1 < n and source[i:i + 2] in (
            '<=', '>=', '==', '!=', '&&', '||'
        ):
            op = source[i:i + 2]
            tokens.append(Token(op, op, line))
            i += 2
            continue
        # Single-character token
        tokens.append(Token(c, c, line))
        i += 1
    tokens.append(Token('EOF', None, line))
    return tokens


# ── Parser (recursive descent, tuple-based AST) ──────────────────────
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # Helpers
    def cur(self):
        return self.tokens[self.pos]

    def eat(self, ty=None):
        tok = self.tokens[self.pos]
        if ty and tok.ty != ty:
            raise SyntaxError(
                f"Line {tok.line}: expected '{ty}', got '{tok.ty}'"
            )
        self.pos += 1
        return tok

    def at(self, ty):
        return self.tokens[self.pos].ty == ty

    def maybe(self, ty):
        if self.at(ty):
            return self.eat()
        return None

    # Top-level
    def parse(self):
        decls, funcs = [], []
        while not self.at('EOF'):
            saved = self.pos
            is_const = bool(self.maybe('const'))
            self.eat()   # type keyword
            self.eat('ID')
            if not is_const and self.at('('):
                self.pos = saved
                funcs.append(self.parse_func())
            else:
                self.pos = saved
                decls.append(self.parse_decl())
        return ('unit', decls, funcs)

    # Declarations
    def parse_decl(self):
        is_const = bool(self.maybe('const'))
        self.eat()  # type
        defs = [self.parse_vardef()]
        while self.maybe(','):
            defs.append(self.parse_vardef())
        self.eat(';')
        return ('decl', is_const, defs)

    def parse_vardef(self):
        name = self.eat('ID').val
        dims = []
        while self.maybe('['):
            dims.append(self.parse_expr())
            self.eat(']')
        init = None
        if self.maybe('='):
            init = self.parse_initval()
        return ('vardef', name, dims, init)

    def parse_initval(self):
        if self.at('{'):
            self.eat('{')
            if self.at('}'):
                self.eat('}')
                return ('initlist', [])
            children = [self.parse_initval()]
            while self.maybe(','):
                if self.at('}'):
                    break
                children.append(self.parse_initval())
            self.eat('}')
            return ('initlist', children)
        return ('initexpr', self.parse_expr())

    # Functions
    def parse_func(self):
        ret_type = self.eat().val
        name = self.eat('ID').val
        self.eat('(')
        params = []
        if not self.at(')'):
            params.append(self.parse_param())
            while self.maybe(','):
                params.append(self.parse_param())
        self.eat(')')
        body = self.parse_block()
        return ('func', ret_type, name, params, body)

    def parse_param(self):
        self.eat()  # type
        name = self.eat('ID').val
        is_array = False
        extra_dims = []
        if self.maybe('['):
            is_array = True
            self.eat(']')
            while self.maybe('['):
                extra_dims.append(self.parse_expr())
                self.eat(']')
        return ('param', name, is_array, extra_dims)

    # Blocks & statements
    def parse_block(self):
        self.eat('{')
        items = []
        while not self.at('}'):
            if self.at('const') or (self.at('int') and self._is_decl()):
                items.append(self.parse_decl())
            else:
                items.append(self.parse_stmt())
        self.eat('}')
        return ('block', items)

    def _is_decl(self):
        saved = self.pos
        self.eat()
        result = self.at('ID')
        self.pos = saved
        return result

    def parse_stmt(self):
        if self.at('{'):
            return self.parse_block()
        if self.at('if'):
            self.eat()
            self.eat('(')
            cond = self.parse_expr()
            self.eat(')')
            then_s = self.parse_stmt()
            else_s = self.parse_stmt() if self.maybe('else') else None
            return ('if', cond, then_s, else_s)
        if self.at('while'):
            self.eat()
            self.eat('(')
            cond = self.parse_expr()
            self.eat(')')
            body = self.parse_stmt()
            return ('while', cond, body)
        if self.at('break'):
            self.eat()
            self.eat(';')
            return ('break',)
        if self.at('continue'):
            self.eat()
            self.eat(';')
            return ('continue',)
        if self.at('return'):
            self.eat()
            expr = None if self.at(';') else self.parse_expr()
            self.eat(';')
            return ('return', expr)
        if self.at(';'):
            self.eat()
            return ('nop',)
        # Assignment or expression statement
        expr = self.parse_expr()
        if self.at('=') and expr[0] == 'lval':
            self.eat()
            rhs = self.parse_expr()
            self.eat(';')
            return ('assign', expr, rhs)
        self.eat(';')
        return ('exprstmt', expr)

    # Expressions (precedence climbing)
    def parse_expr(self):
        return self._lor()

    def _lor(self):
        node = self._land()
        while self.at('||'):
            self.eat()
            node = ('||', node, self._land())
        return node

    def _land(self):
        node = self._eq()
        while self.at('&&'):
            self.eat()
            node = ('&&', node, self._eq())
        return node

    def _eq(self):
        node = self._rel()
        while self.cur().ty in ('==', '!='):
            op = self.eat().ty
            node = (op, node, self._rel())
        return node

    def _rel(self):
        node = self._add()
        while self.cur().ty in ('<', '>', '<=', '>='):
            op = self.eat().ty
            node = (op, node, self._add())
        return node

    def _add(self):
        node = self._mul()
        while self.cur().ty in ('+', '-'):
            op = self.eat().ty
            node = (op, node, self._mul())
        return node

    def _mul(self):
        node = self._unary()
        while self.cur().ty in ('*', '/', '%'):
            op = self.eat().ty
            node = (op, node, self._unary())
        return node

    def _unary(self):
        if self.cur().ty in ('+', '-', '!'):
            op = self.eat().ty
            return ('unary_' + op, self._unary())
        return self._primary()

    def _primary(self):
        if self.at('('):
            self.eat()
            expr = self.parse_expr()
            self.eat(')')
            return expr
        if self.at('NUM'):
            return ('num', self.eat().val)
        if self.at('ID'):
            name = self.eat().val
            # Function call
            if self.at('('):
                self.eat()
                args = []
                if not self.at(')'):
                    args.append(self.parse_expr())
                    while self.maybe(','):
                        args.append(self.parse_expr())
                self.eat(')')
                return ('call', name, args)
            # L-value (variable or array element)
            indices = []
            while self.at('['):
                self.eat()
                indices.append(self.parse_expr())
                self.eat(']')
            return ('lval', name, indices)
        raise SyntaxError(
            f"Line {self.cur().line}: unexpected '{self.cur().val}'"
        )


# ── Runtime data structures ──────────────────────────────────────────
class ArrayValue:
    """Flat representation of a multi-dimensional array."""
    __slots__ = ('data', 'dims', 'offset')

    def __init__(self, data, dims, offset=0):
        self.data = data
        self.dims = dims
        self.offset = offset

    def sub(self, index):
        """Index one dimension: returns scalar or sub-ArrayValue."""
        if len(self.dims) == 1:
            return self.data[self.offset + index]
        stride = 1
        for d in self.dims[1:]:
            stride *= d
        return ArrayValue(self.data, self.dims[1:],
                          self.offset + index * stride)


class Scope:
    """Chained variable scope for block-level scoping."""
    __slots__ = ('parent', 'bindings')

    def __init__(self, parent=None):
        self.parent = parent
        self.bindings = {}

    def define(self, name, value):
        self.bindings[name] = value

    def lookup(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.lookup(name)
        raise NameError(f"Undefined variable: {name}")

    def assign(self, name, value):
        if name in self.bindings:
            self.bindings[name] = value
            return
        if self.parent:
            self.parent.assign(name, value)
            return
        raise NameError(f"Undefined variable: {name}")


# ── Interpreter ───────────────────────────────────────────────────────
class Interpreter:
    def __init__(self):
        self.global_scope = Scope()
        self.functions = {}

    def run(self, ast):
        _, decls, funcs = ast
        for f in funcs:
            self.functions[f[2]] = f
        for d in decls:
            self.exec_decl(d, self.global_scope)
        try:
            result = self.call_func('main', [])
        except ReturnSignal as r:
            result = r.val if r.val is not None else 0
        return result if result is not None else 0

    # ── Declarations ──────────────────────────────────────────────────
    def exec_decl(self, node, scope):
        _, _is_const, defs = node
        for vdef in defs:
            _, name, dim_exprs, init = vdef
            dims = [self.eval_expr(d, scope) for d in dim_exprs]
            if not dims:
                # Scalar
                if init and init[0] == 'initexpr':
                    val = self.eval_expr(init[1], scope)
                else:
                    val = 0
                scope.define(name, val)
            else:
                # Array
                total = 1
                for d in dims:
                    total *= d
                data = [0] * total
                if init:
                    self._fill_init(data, 0, dims, init, scope)
                scope.define(name, ArrayValue(data, dims))

    def _fill_init(self, data, offset, dims, init, scope):
        """Recursively fill flat array data according to SysY brace rules."""
        if init[0] == 'initexpr':
            data[offset] = self.eval_expr(init[1], scope)
            return
        # 'initlist'
        children = init[1]
        if not dims:
            return
        if len(dims) == 1:
            # Innermost dimension: each child is a scalar
            for ci, child in enumerate(children):
                if ci >= dims[0]:
                    break
                if child[0] == 'initexpr':
                    data[offset + ci] = self.eval_expr(child[1], scope)
                elif child[0] == 'initlist' and child[1]:
                    # Braced group at scalar level – take first value
                    if child[1][0][0] == 'initexpr':
                        data[offset + ci] = self.eval_expr(
                            child[1][0][1], scope
                        )
            return
        # Multi-dimensional: process element by element
        stride = 1
        for d in dims[1:]:
            stride *= d
        pos = 0  # index in outermost dimension
        ci = 0   # index into children
        while ci < len(children) and pos < dims[0]:
            child = children[ci]
            if child[0] == 'initlist':
                # Braced group fills one sub-array
                self._fill_init(
                    data, offset + pos * stride, dims[1:], child, scope
                )
                pos += 1
                ci += 1
            else:
                # Consecutive bare values fill one sub-array
                bare = []
                while (ci < len(children)
                       and children[ci][0] == 'initexpr'
                       and len(bare) < stride):
                    bare.append(children[ci])
                    ci += 1
                self._fill_init(
                    data, offset + pos * stride, dims[1:],
                    ('initlist', bare), scope
                )
                pos += 1

    # ── Statement execution ───────────────────────────────────────────
    def exec_stmt(self, node, scope):
        tag = node[0]
        if tag == 'block':
            child_scope = Scope(scope)
            for item in node[1]:
                if item[0] == 'decl':
                    self.exec_decl(item, child_scope)
                else:
                    self.exec_stmt(item, child_scope)
        elif tag == 'assign':
            _, lval, rhs = node
            value = self.eval_expr(rhs, scope)
            self._do_assign(lval, value, scope)
        elif tag == 'exprstmt':
            self.eval_expr(node[1], scope)
        elif tag == 'if':
            _, cond, then_s, else_s = node
            if self.eval_expr(cond, scope):
                self.exec_stmt(then_s, scope)
            elif else_s:
                self.exec_stmt(else_s, scope)
        elif tag == 'while':
            _, cond, body = node
            while self.eval_expr(cond, scope):
                try:
                    self.exec_stmt(body, scope)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue
        elif tag == 'break':
            raise BreakSignal()
        elif tag == 'continue':
            raise ContinueSignal()
        elif tag == 'return':
            raise ReturnSignal(
                self.eval_expr(node[1], scope) if node[1] else None
            )
        # 'nop' – do nothing

    # ── Expression evaluation ─────────────────────────────────────────
    def eval_expr(self, node, scope):
        tag = node[0]

        if tag == 'num':
            return node[1]

        if tag == 'lval':
            _, name, indices = node
            val = scope.lookup(name)
            for idx_expr in indices:
                idx = self.eval_expr(idx_expr, scope)
                if isinstance(val, ArrayValue):
                    val = val.sub(idx)
                else:
                    raise RuntimeError(f"Cannot index non-array '{name}'")
            return val

        if tag == 'call':
            _, name, arg_exprs = node
            args = [self.eval_expr(a, scope) for a in arg_exprs]
            return self.call_func(name, args)

        # Short-circuit boolean operators
        if tag == '||':
            left = self.eval_expr(node[1], scope)
            if left:
                return 1
            return 1 if self.eval_expr(node[2], scope) else 0

        if tag == '&&':
            left = self.eval_expr(node[1], scope)
            if not left:
                return 0
            return 1 if self.eval_expr(node[2], scope) else 0

        # Binary operators
        if tag in ('==', '!=', '<', '>', '<=', '>=',
                    '+', '-', '*', '/', '%'):
            left = self.eval_expr(node[1], scope)
            right = self.eval_expr(node[2], scope)
            if tag == '==':
                return int(left == right)
            if tag == '!=':
                return int(left != right)
            if tag == '<':
                return int(left < right)
            if tag == '>':
                return int(left > right)
            if tag == '<=':
                return int(left <= right)
            if tag == '>=':
                return int(left >= right)
            if tag == '+':
                return left + right
            if tag == '-':
                return left - right
            if tag == '*':
                return left * right
            if tag == '/':
                if right == 0:
                    return 0
                # C-semantics: truncate toward zero
                sign = -1 if (left < 0) != (right < 0) else 1
                return sign * (abs(left) // abs(right))
            if tag == '%':
                if right == 0:
                    return 0
                sign = -1 if (left < 0) != (right < 0) else 1
                quotient = sign * (abs(left) // abs(right))
                return left - quotient * right

        # Unary operators
        if tag == 'unary_+':
            return self.eval_expr(node[1], scope)
        if tag == 'unary_-':
            return -self.eval_expr(node[1], scope)
        if tag == 'unary_!':
            return int(not self.eval_expr(node[1], scope))

        raise RuntimeError(f"Unknown expression node: {tag}")

    # ── Assignment ────────────────────────────────────────────────────
    def _do_assign(self, lval, value, scope):
        _, name, indices = lval
        if not indices:
            scope.assign(name, value)
            return
        arr = scope.lookup(name)
        for idx_expr in indices[:-1]:
            idx = self.eval_expr(idx_expr, scope)
            arr = arr.sub(idx)
        last_idx = self.eval_expr(indices[-1], scope)
        arr.data[arr.offset + last_idx] = value

    # ── Function calls ────────────────────────────────────────────────
    def call_func(self, name, args):
        # Built-in runtime library
        if name == 'getint':
            return self._read_int()
        if name == 'getch':
            ch = sys.stdin.read(1)
            return ord(ch) if ch else -1
        if name == 'getarray':
            arr = args[0]
            n = self._read_int()
            for i in range(n):
                arr.data[arr.offset + i] = self._read_int()
            return n
        if name == 'putint':
            sys.stdout.write(str(args[0]))
            return 0
        if name == 'putch':
            sys.stdout.write(chr(args[0]))
            return 0
        if name == 'putarray':
            n, arr = args[0], args[1]
            sys.stdout.write(f"{n}:")
            for i in range(n):
                sys.stdout.write(f" {arr.data[arr.offset + i]}")
            sys.stdout.write("\n")
            return 0
        if name in ('starttime', 'stoptime',
                     '_sysy_starttime', '_sysy_stoptime'):
            return 0

        # User-defined function
        func = self.functions.get(name)
        if not func:
            raise RuntimeError(f"Undefined function: {name}")
        _, _ret_type, _fname, params, body = func
        func_scope = Scope(self.global_scope)
        for param, arg in zip(params, args):
            func_scope.define(param[1], arg)
        try:
            self.exec_stmt(body, func_scope)
        except ReturnSignal as r:
            return r.val if r.val is not None else 0
        return 0

    # ── Stdin helpers ─────────────────────────────────────────────────
    def _read_int(self):
        """Read one whitespace-delimited integer from stdin."""
        buf = []
        # Skip leading whitespace
        while True:
            ch = sys.stdin.read(1)
            if not ch:
                return 0
            if not ch.isspace():
                buf.append(ch)
                break
        # Read until whitespace or EOF
        while True:
            ch = sys.stdin.read(1)
            if not ch or ch.isspace():
                break
            buf.append(ch)
        return int(''.join(buf))


# ── Entry point ───────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_interpreter <file.sy>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    tokens = tokenize(source)
    parser = Parser(tokens)
    ast = parser.parse()
    interp = Interpreter()
    result = interp.run(ast)
    sys.exit((result if result is not None else 0) & 0xFF)


if __name__ == '__main__':
    main()
