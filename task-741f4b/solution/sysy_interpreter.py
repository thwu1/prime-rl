#!/usr/bin/env python3
"""
SysY Language Interpreter - Reference Solution

A complete tree-walking interpreter for the SysY programming language,
including lexer, recursive descent parser, and evaluator.

"""
import sys


# ============================================================
# Control flow exceptions
# ============================================================

class BreakSignal(Exception):
    pass

class ContinueSignal(Exception):
    pass

class ReturnSignal(Exception):
    def __init__(self, value=None):
        self.value = value


# ============================================================
# Lexer
# ============================================================

KEYWORDS = frozenset([
    'const', 'int', 'void', 'if', 'else',
    'while', 'break', 'continue', 'return',
])

TWO_CHAR_OPS = frozenset(['<=', '>=', '==', '!=', '&&', '||'])

class Token:
    __slots__ = ('type', 'value', 'line')
    def __init__(self, tp, val, line):
        self.type = tp
        self.value = val
        self.line = line
    def __repr__(self):
        return f'Token({self.type!r}, {self.value!r}, L{self.line})'


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1

    while i < n:
        ch = source[i]

        # Whitespace
        if ch in ' \t\r':
            i += 1
            continue
        if ch == '\n':
            line += 1
            i += 1
            continue

        # Line comment
        if ch == '/' and i + 1 < n and source[i + 1] == '/':
            i += 2
            while i < n and source[i] != '\n':
                i += 1
            continue

        # Block comment
        if ch == '/' and i + 1 < n and source[i + 1] == '*':
            i += 2
            while i < n - 1:
                if source[i] == '\n':
                    line += 1
                if source[i] == '*' and source[i + 1] == '/':
                    i += 2
                    break
                i += 1
            else:
                i = n  # unterminated comment
            continue

        # Two-character operators
        if i + 1 < n and source[i:i+2] in TWO_CHAR_OPS:
            tok = source[i:i+2]
            tokens.append(Token(tok, tok, line))
            i += 2
            continue

        # Single-character operators / delimiters
        if ch in '+-*/%<>=!()[]{}.,;':
            tokens.append(Token(ch, ch, line))
            i += 1
            continue

        # Integer constants
        if ch.isdigit():
            start = i
            if ch == '0' and i + 1 < n and source[i + 1] in 'xX':
                # Hexadecimal
                i += 2
                while i < n and source[i] in '0123456789abcdefABCDEF':
                    i += 1
                tokens.append(Token('INT', int(source[start:i], 16), line))
            elif ch == '0' and i + 1 < n and source[i + 1] in '01234567':
                # Octal
                i += 1
                while i < n and source[i] in '01234567':
                    i += 1
                tokens.append(Token('INT', int(source[start:i], 8), line))
            else:
                # Decimal
                while i < n and source[i].isdigit():
                    i += 1
                tokens.append(Token('INT', int(source[start:i]), line))
            continue

        # Identifiers and keywords
        if ch.isalpha() or ch == '_':
            start = i
            i += 1
            while i < n and (source[i].isalnum() or source[i] == '_'):
                i += 1
            word = source[start:i]
            if word in KEYWORDS:
                tokens.append(Token(word, word, line))
            else:
                tokens.append(Token('IDENT', word, line))
            continue

        raise SyntaxError(f"Unexpected character '{ch}' at line {line}")

    tokens.append(Token('EOF', None, line))
    return tokens


# ============================================================
# Parser  (recursive descent)
# ============================================================

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

    def expect(self, tp):
        tok = self.advance()
        if tok.type != tp:
            raise SyntaxError(
                f"Expected '{tp}', got '{tok.type}' ({tok.value!r}) "
                f"at line {tok.line}"
            )
        return tok

    def match(self, tp):
        if self.peek().type == tp:
            return self.advance()
        return None

    # ---- Top-level ----

    def parse(self):
        decls = []
        while self.peek().type != 'EOF':
            decls.append(self._parse_global())
        return ('program', decls)

    def _parse_global(self):
        if self.peek().type == 'const':
            return self._parse_const_decl()
        if self.peek().type == 'void':
            return self._parse_func_def()
        # 'int' — look ahead to distinguish FuncDef from VarDecl
        saved = self.pos
        self.expect('int')
        self.expect('IDENT')
        is_func = self.peek().type == '('
        self.pos = saved
        if is_func:
            return self._parse_func_def()
        return self._parse_var_decl()

    # ---- Declarations ----

    def _parse_const_decl(self):
        self.expect('const')
        self.expect('int')
        defs = [self._parse_const_def()]
        while self.match(','):
            defs.append(self._parse_const_def())
        self.expect(';')
        return ('const_decl', defs)

    def _parse_const_def(self):
        name = self.expect('IDENT').value
        dims = []
        while self.match('['):
            dims.append(self._parse_exp())
            self.expect(']')
        self.expect('=')
        init = self._parse_init_val(const=True)
        return ('const_def', name, dims, init)

    def _parse_var_decl(self):
        self.expect('int')
        defs = [self._parse_var_def()]
        while self.match(','):
            defs.append(self._parse_var_def())
        self.expect(';')
        return ('var_decl', defs)

    def _parse_var_def(self):
        name = self.expect('IDENT').value
        dims = []
        while self.match('['):
            dims.append(self._parse_exp())
            self.expect(']')
        init = None
        if self.match('='):
            init = self._parse_init_val(const=False)
        return ('var_def', name, dims, init)

    def _parse_init_val(self, const):
        if self.match('{'):
            vals = []
            if self.peek().type != '}':
                vals.append(self._parse_init_val(const))
                while self.match(','):
                    vals.append(self._parse_init_val(const))
            self.expect('}')
            return ('init_list', vals)
        return self._parse_exp()

    # ---- Functions ----

    def _parse_func_def(self):
        ret_type = self.advance().value  # 'int' or 'void'
        name = self.expect('IDENT').value
        self.expect('(')
        params = []
        if self.peek().type != ')':
            params.append(self._parse_func_param())
            while self.match(','):
                params.append(self._parse_func_param())
        self.expect(')')
        body = self._parse_block()
        return ('func_def', ret_type, name, params, body)

    def _parse_func_param(self):
        self.expect('int')
        name = self.expect('IDENT').value
        dims = None
        if self.match('['):
            self.expect(']')
            dims = [None]  # first dimension unknown
            while self.match('['):
                dims.append(self._parse_exp())
                self.expect(']')
        return ('param', name, dims)

    # ---- Statements ----

    def _parse_block(self):
        self.expect('{')
        items = []
        while self.peek().type != '}':
            items.append(self._parse_block_item())
        self.expect('}')
        return ('block', items)

    def _parse_block_item(self):
        if self.peek().type == 'const':
            return self._parse_const_decl()
        if self.peek().type == 'int':
            # Distinguish local var decl from expression starting with int cast
            # In SysY, 'int' always starts a declaration here
            return self._parse_var_decl()
        return self._parse_stmt()

    def _parse_stmt(self):
        tp = self.peek().type

        if tp == '{':
            return self._parse_block()

        if tp == 'if':
            self.advance()
            self.expect('(')
            cond = self._parse_exp()
            self.expect(')')
            then = self._parse_stmt()
            els = None
            if self.match('else'):
                els = self._parse_stmt()
            return ('if', cond, then, els)

        if tp == 'while':
            self.advance()
            self.expect('(')
            cond = self._parse_exp()
            self.expect(')')
            body = self._parse_stmt()
            return ('while', cond, body)

        if tp == 'break':
            self.advance()
            self.expect(';')
            return ('break',)

        if tp == 'continue':
            self.advance()
            self.expect(';')
            return ('continue',)

        if tp == 'return':
            self.advance()
            val = None
            if self.peek().type != ';':
                val = self._parse_exp()
            self.expect(';')
            return ('return', val)

        if tp == ';':
            self.advance()
            return ('empty',)

        # Expression or assignment statement
        exp = self._parse_exp()
        if self.match('='):
            rhs = self._parse_exp()
            self.expect(';')
            return ('assign', exp, rhs)
        self.expect(';')
        return ('expr_stmt', exp)

    # ---- Expressions (precedence climbing) ----

    def _parse_exp(self):
        return self._parse_lor()

    def _parse_lor(self):
        left = self._parse_land()
        while self.peek().type == '||':
            self.advance()
            right = self._parse_land()
            left = ('||', left, right)
        return left

    def _parse_land(self):
        left = self._parse_eq()
        while self.peek().type == '&&':
            self.advance()
            right = self._parse_eq()
            left = ('&&', left, right)
        return left

    def _parse_eq(self):
        left = self._parse_rel()
        while self.peek().type in ('==', '!='):
            op = self.advance().type
            right = self._parse_rel()
            left = (op, left, right)
        return left

    def _parse_rel(self):
        left = self._parse_add()
        while self.peek().type in ('<', '>', '<=', '>='):
            op = self.advance().type
            right = self._parse_add()
            left = (op, left, right)
        return left

    def _parse_add(self):
        left = self._parse_mul()
        while self.peek().type in ('+', '-'):
            op = self.advance().type
            right = self._parse_mul()
            left = (op, left, right)
        return left

    def _parse_mul(self):
        left = self._parse_unary()
        while self.peek().type in ('*', '/', '%'):
            op = self.advance().type
            right = self._parse_unary()
            left = (op, left, right)
        return left

    def _parse_unary(self):
        if self.peek().type in ('+', '-', '!'):
            op = self.advance().type
            operand = self._parse_unary()
            return ('u' + op, operand)
        # Function call: IDENT '('
        if (self.peek().type == 'IDENT'
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].type == '('):
            name = self.advance().value
            self.expect('(')
            args = []
            if self.peek().type != ')':
                args.append(self._parse_exp())
                while self.match(','):
                    args.append(self._parse_exp())
            self.expect(')')
            return ('call', name, args)
        return self._parse_primary()

    def _parse_primary(self):
        if self.match('('):
            exp = self._parse_exp()
            self.expect(')')
            return exp
        if self.peek().type == 'INT':
            return ('int', self.advance().value)
        if self.peek().type == 'IDENT':
            name = self.advance().value
            indices = []
            while self.peek().type == '[':
                self.advance()
                indices.append(self._parse_exp())
                self.expect(']')
            if indices:
                return ('index', name, indices)
            return ('var', name)
        raise SyntaxError(
            f"Unexpected token '{self.peek().type}' ({self.peek().value!r}) "
            f"at line {self.peek().line}"
        )


# ============================================================
# Runtime: array representation
# ============================================================

class ArrayRef:
    """Reference into a flat integer array with dimension metadata."""
    __slots__ = ('data', 'offset', 'dims')

    def __init__(self, data, offset, dims):
        self.data = data      # list[int] — shared mutable storage
        self.offset = offset  # int — start index into data
        self.dims = dims      # list[int] — remaining dimension sizes

    def _flat(self, indices):
        """Compute flat index from a list of integer indices."""
        idx = self.offset
        for k, ix in enumerate(indices):
            stride = 1
            for d in self.dims[k + 1:]:
                stride *= d
            idx += ix * stride
        return idx

    def get(self, indices):
        if len(indices) == len(self.dims):
            return self.data[self._flat(indices)]
        # Partial indexing → sub-array reference
        flat = self._flat(indices)
        return ArrayRef(self.data, flat, self.dims[len(indices):])

    def put(self, indices, value):
        self.data[self._flat(indices)] = value


# ============================================================
# Runtime: environment (scope chain)
# ============================================================

class Env:
    __slots__ = ('bindings', 'parent')

    def __init__(self, parent=None):
        self.bindings = {}
        self.parent = parent

    def define(self, name, value):
        self.bindings[name] = value

    def lookup(self, name):
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        raise NameError(f"Undefined: '{name}'")

    def assign(self, name, value):
        if name in self.bindings:
            self.bindings[name] = value
            return
        if self.parent is not None:
            self.parent.assign(name, value)
            return
        raise NameError(f"Undefined: '{name}'")


# ============================================================
# Interpreter
# ============================================================

class Interpreter:
    def __init__(self):
        self.global_env = Env()
        self.functions = {}       # name → (ret_type, params, body)
        self._input_buf = []      # buffered whitespace-split tokens
        self._input_pos = 0

    # ---- I/O helpers ----

    def _read_int(self):
        while self._input_pos >= len(self._input_buf):
            line = sys.stdin.readline()
            if not line:
                raise EOFError("No more input")
            self._input_buf.extend(line.split())
        val = int(self._input_buf[self._input_pos])
        self._input_pos += 1
        return val

    def _read_char(self):
        ch = sys.stdin.read(1)
        if not ch:
            raise EOFError("No more input")
        return ord(ch)

    # ---- Array initialization helpers ----

    def _flatten_init(self, init_node, dims, env):
        total = 1
        for d in dims:
            total *= d
        flat = [0] * total
        self._fill(init_node, dims, flat, 0, env)
        return flat

    def _fill(self, node, dims, flat, offset, env):
        """Recursively fill flat array from an init_list or scalar."""
        if not dims:
            flat[offset] = self._eval(node, env)
            return 1

        if isinstance(node, tuple) and node[0] == 'init_list':
            sub_size = 1
            for d in dims[1:]:
                sub_size *= d
            pos = 0
            for v in node[1]:
                if isinstance(v, tuple) and v[0] == 'init_list':
                    self._fill(v, dims[1:], flat, offset + pos, env)
                    pos += sub_size
                else:
                    flat[offset + pos] = self._eval(v, env)
                    pos += 1
            return pos

        flat[offset] = self._eval(node, env)
        return 1

    # ---- Declaration execution ----

    def _exec_var_def(self, node, env, is_global=False):
        _, name, dim_nodes, init = node
        if dim_nodes:
            dims = [self._eval(d, env) for d in dim_nodes]
            if init:
                data = self._flatten_init(init, dims, env)
            else:
                total = 1
                for d in dims:
                    total *= d
                data = [0] * total
            env.define(name, ArrayRef(data, 0, list(dims)))
        else:
            if init:
                val = self._eval(init, env)
            else:
                val = 0  # global zero-init (local undefined but safe default)
            env.define(name, val)

    def _exec_const_def(self, node, env):
        _, name, dim_nodes, init = node
        if dim_nodes:
            dims = [self._eval(d, env) for d in dim_nodes]
            data = self._flatten_init(init, dims, env)
            env.define(name, ArrayRef(data, 0, list(dims)))
        else:
            env.define(name, self._eval(init, env))

    # ---- Statement execution ----

    def _exec(self, node, env):
        kind = node[0]

        if kind == 'block':
            child_env = Env(env)
            for item in node[1]:
                self._exec_item(item, child_env)

        elif kind == 'if':
            _, cond, then_s, else_s = node
            if self._eval(cond, env):
                self._exec(then_s, env)
            elif else_s:
                self._exec(else_s, env)

        elif kind == 'while':
            _, cond, body = node
            while self._eval(cond, env):
                try:
                    self._exec(body, env)
                except BreakSignal:
                    break
                except ContinueSignal:
                    continue

        elif kind == 'break':
            raise BreakSignal()

        elif kind == 'continue':
            raise ContinueSignal()

        elif kind == 'return':
            raise ReturnSignal(
                self._eval(node[1], env) if node[1] is not None else None
            )

        elif kind == 'assign':
            _, lval, rhs = node
            val = self._eval(rhs, env)
            self._do_assign(lval, val, env)

        elif kind == 'expr_stmt':
            self._eval(node[1], env)

        elif kind == 'empty':
            pass

    def _exec_item(self, item, env):
        kind = item[0]
        if kind == 'var_decl':
            for vd in item[1]:
                self._exec_var_def(vd, env)
        elif kind == 'const_decl':
            for cd in item[1]:
                self._exec_const_def(cd, env)
        else:
            self._exec(item, env)

    def _do_assign(self, lval, value, env):
        if lval[0] == 'var':
            env.assign(lval[1], value)
        elif lval[0] == 'index':
            _, name, idx_nodes = lval
            arr = env.lookup(name)
            indices = [self._eval(ix, env) for ix in idx_nodes]
            arr.put(indices, value)

    # ---- Expression evaluation ----

    def _eval(self, node, env):
        kind = node[0]

        if kind == 'int':
            return node[1]

        if kind == 'var':
            return env.lookup(node[1])

        if kind == 'index':
            _, name, idx_nodes = node
            arr = env.lookup(name)
            indices = [self._eval(ix, env) for ix in idx_nodes]
            return arr.get(indices)

        if kind == 'call':
            _, fname, arg_nodes = node
            args = [self._eval(a, env) for a in arg_nodes]
            return self._call(fname, args)

        # Binary arithmetic
        if kind in ('+', '-', '*', '/', '%'):
            left = self._eval(node[1], env)
            right = self._eval(node[2], env)
            if kind == '+':
                return left + right
            if kind == '-':
                return left - right
            if kind == '*':
                return left * right
            if kind == '/':
                # Truncate toward zero (C99)
                q = abs(left) // abs(right)
                return q if (left >= 0) == (right >= 0) else -q
            if kind == '%':
                q = abs(left) // abs(right)
                q = q if (left >= 0) == (right >= 0) else -q
                return left - q * right

        # Relational
        if kind in ('<', '>', '<=', '>=', '==', '!='):
            left = self._eval(node[1], env)
            right = self._eval(node[2], env)
            ops = {
                '<':  left < right,
                '>':  left > right,
                '<=': left <= right,
                '>=': left >= right,
                '==': left == right,
                '!=': left != right,
            }
            return 1 if ops[kind] else 0

        # Logical (short-circuit)
        if kind == '&&':
            left = self._eval(node[1], env)
            if not left:
                return 0
            return 1 if self._eval(node[2], env) else 0

        if kind == '||':
            left = self._eval(node[1], env)
            if left:
                return 1
            return 1 if self._eval(node[2], env) else 0

        # Unary
        if kind == 'u+':
            return self._eval(node[1], env)
        if kind == 'u-':
            return -self._eval(node[1], env)
        if kind == 'u!':
            return 0 if self._eval(node[1], env) else 1

        raise RuntimeError(f"Unknown expression kind: {kind}")

    # ---- Function calls ----

    def _call(self, name, args):
        # Built-in runtime library
        if name == 'getint':
            return self._read_int()
        if name == 'getch':
            return self._read_char()
        if name == 'getarray':
            arr = args[0]
            n = self._read_int()
            for i in range(n):
                arr.data[arr.offset + i] = self._read_int()
            return n
        if name == 'putint':
            sys.stdout.write(str(args[0]))
            return None
        if name == 'putch':
            sys.stdout.write(chr(args[0]))
            return None
        if name == 'putarray':
            n, arr = args[0], args[1]
            parts = [str(n), ':']
            for i in range(n):
                parts.append(' ')
                parts.append(str(arr.data[arr.offset + i]))
            sys.stdout.write(''.join(parts) + '\n')
            return None

        # User-defined function
        if name not in self.functions:
            raise RuntimeError(f"Undefined function: '{name}'")
        ret_type, params, body = self.functions[name]
        func_env = Env(self.global_env)
        for i, param in enumerate(params):
            _, pname, pdims = param
            func_env.define(pname, args[i])
        try:
            self._exec(body, func_env)
        except ReturnSignal as sig:
            if sig.value is not None:
                return sig.value
            return 0 if ret_type == 'int' else None
        return 0 if ret_type == 'int' else None

    # ---- Entry point ----

    def run(self, program):
        _, decls = program
        for decl in decls:
            if decl[0] == 'func_def':
                _, ret_type, name, params, body = decl
                self.functions[name] = (ret_type, params, body)
            elif decl[0] == 'var_decl':
                for vd in decl[1]:
                    self._exec_var_def(vd, self.global_env, is_global=True)
            elif decl[0] == 'const_decl':
                for cd in decl[1]:
                    self._exec_const_def(cd, self.global_env)

        if 'main' not in self.functions:
            raise RuntimeError("No 'main' function defined")
        result = self._call('main', [])
        return result if result is not None else 0


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_interp <file.sy>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        source = f.read()

    tokens = tokenize(source)
    parser = Parser(tokens)
    program = parser.parse()

    interp = Interpreter()
    result = interp.run(program)
    sys.exit(result if result is not None else 0)


if __name__ == '__main__':
    main()
