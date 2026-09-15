#!/usr/bin/env python3
"""SysY language interpreter — reference implementation."""
import sys

# ======================== Tokens ========================

KEYWORDS = {'const', 'int', 'void', 'if', 'else', 'while', 'break', 'continue', 'return'}


class Token:
    __slots__ = ('type', 'value', 'line')

    def __init__(self, tp, val, line=0):
        self.type = tp
        self.value = val
        self.line = line


# ======================== Lexer ========================

class Lexer:
    def __init__(self, source):
        self.src = source
        self.pos = 0
        self.line = 1
        self.tokens = []
        self._tokenize()

    def _ch(self):
        return self.src[self.pos] if self.pos < len(self.src) else '\0'

    def _adv(self):
        c = self.src[self.pos]
        self.pos += 1
        if c == '\n':
            self.line += 1
        return c

    def _skip(self):
        while self.pos < len(self.src):
            c = self._ch()
            if c in ' \t\n\r':
                self._adv()
            elif c == '/' and self.pos + 1 < len(self.src):
                if self.src[self.pos + 1] == '/':
                    self.pos += 2
                    while self.pos < len(self.src) and self.src[self.pos] != '\n':
                        self.pos += 1
                elif self.src[self.pos + 1] == '*':
                    self.pos += 2
                    while self.pos + 1 < len(self.src):
                        if self.src[self.pos] == '\n':
                            self.line += 1
                        if self.src[self.pos] == '*' and self.src[self.pos + 1] == '/':
                            self.pos += 2
                            break
                        self.pos += 1
                    else:
                        self.pos = len(self.src)
                else:
                    break
            else:
                break

    def _read_num(self):
        start = self.pos
        if self._ch() == '0' and self.pos + 1 < len(self.src):
            nx = self.src[self.pos + 1]
            if nx in 'xX':
                self.pos += 2
                while self.pos < len(self.src) and self.src[self.pos] in '0123456789abcdefABCDEF':
                    self.pos += 1
                return int(self.src[start:self.pos], 16)
            elif nx in '01234567':
                self.pos += 1
                while self.pos < len(self.src) and self.src[self.pos] in '01234567':
                    self.pos += 1
                return int(self.src[start:self.pos], 8)
        while self.pos < len(self.src) and self.src[self.pos].isdigit():
            self.pos += 1
        return int(self.src[start:self.pos])

    def _read_word(self):
        start = self.pos
        while self.pos < len(self.src) and (self.src[self.pos].isalnum() or self.src[self.pos] == '_'):
            self.pos += 1
        return self.src[start:self.pos]

    def _tokenize(self):
        TWO_CHAR = {'<=': 'LE', '>=': 'GE', '==': 'EQ', '!=': 'NE', '&&': 'AND', '||': 'OR'}
        ONE_CHAR = {
            '+': 'PLUS', '-': 'MINUS', '*': 'STAR', '/': 'SLASH', '%': 'PERCENT',
            '<': 'LT', '>': 'GT', '=': 'ASSIGN', '!': 'NOT',
            '(': 'LPAREN', ')': 'RPAREN', '[': 'LBRACKET', ']': 'RBRACKET',
            '{': 'LBRACE', '}': 'RBRACE', ';': 'SEMICOLON', ',': 'COMMA',
        }

        while True:
            self._skip()
            if self.pos >= len(self.src):
                self.tokens.append(Token('EOF', None, self.line))
                break
            c = self._ch()
            ln = self.line

            if c.isdigit():
                self.tokens.append(Token('INT_CONST', self._read_num(), ln))
            elif c.isalpha() or c == '_':
                w = self._read_word()
                self.tokens.append(Token(w.upper() if w in KEYWORDS else 'IDENT', w, ln))
            else:
                # Try two-char operators
                if self.pos + 1 < len(self.src):
                    two = self.src[self.pos:self.pos + 2]
                    if two in TWO_CHAR:
                        self.pos += 2
                        self.tokens.append(Token(TWO_CHAR[two], two, ln))
                        continue
                if c in ONE_CHAR:
                    self._adv()
                    self.tokens.append(Token(ONE_CHAR[c], c, ln))
                else:
                    raise SyntaxError(f"Line {ln}: unexpected '{c}'")


# ======================== AST Nodes ========================

class Program:
    __slots__ = ('items',)
    def __init__(self, items): self.items = items

class ConstDecl:
    __slots__ = ('defs',)
    def __init__(self, defs): self.defs = defs

class ConstDef:
    __slots__ = ('name', 'dims', 'init')
    def __init__(self, name, dims, init): self.name = name; self.dims = dims; self.init = init

class VarDecl:
    __slots__ = ('defs',)
    def __init__(self, defs): self.defs = defs

class VarDef:
    __slots__ = ('name', 'dims', 'init')
    def __init__(self, name, dims, init): self.name = name; self.dims = dims; self.init = init

class FuncDef:
    __slots__ = ('ret_type', 'name', 'params', 'body')
    def __init__(self, rt, name, params, body): self.ret_type = rt; self.name = name; self.params = params; self.body = body

class FuncParam:
    __slots__ = ('name', 'is_array', 'dims')
    def __init__(self, name, is_arr, dims): self.name = name; self.is_array = is_arr; self.dims = dims

class Block:
    __slots__ = ('items',)
    def __init__(self, items): self.items = items

class AssignStmt:
    __slots__ = ('lval', 'expr')
    def __init__(self, lv, ex): self.lval = lv; self.expr = ex

class ExprStmt:
    __slots__ = ('expr',)
    def __init__(self, ex): self.expr = ex

class IfStmt:
    __slots__ = ('cond', 'then_s', 'else_s')
    def __init__(self, c, t, e): self.cond = c; self.then_s = t; self.else_s = e

class WhileStmt:
    __slots__ = ('cond', 'body')
    def __init__(self, c, b): self.cond = c; self.body = b

class BreakStmt:
    pass

class ContinueStmt:
    pass

class ReturnStmt:
    __slots__ = ('expr',)
    def __init__(self, ex): self.expr = ex

class BinExpr:
    __slots__ = ('op', 'left', 'right')
    def __init__(self, op, l, r): self.op = op; self.left = l; self.right = r

class UnaryExpr:
    __slots__ = ('op', 'operand')
    def __init__(self, op, a): self.op = op; self.operand = a

class CallExpr:
    __slots__ = ('name', 'args')
    def __init__(self, name, args): self.name = name; self.args = args

class LVal:
    __slots__ = ('name', 'indices')
    def __init__(self, name, idx): self.name = name; self.indices = idx

class NumLit:
    __slots__ = ('value',)
    def __init__(self, v): self.value = v

class InitList:
    __slots__ = ('items',)
    def __init__(self, items): self.items = items


# ======================== Parser ========================

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos]

    def _adv(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def _expect(self, tp):
        t = self._adv()
        if t.type != tp:
            raise SyntaxError(f"Line {t.line}: expected {tp}, got {t.type}")
        return t

    def _match(self, tp):
        if self._peek().type == tp:
            return self._adv()
        return None

    def parse(self):
        items = []
        while self._peek().type != 'EOF':
            items.append(self._global_item())
        return Program(items)

    def _global_item(self):
        if self._peek().type == 'CONST':
            return self._const_decl()
        if self._peek().type == 'VOID':
            return self._func_def()
        # int — could be VarDecl or FuncDef
        saved = self.pos
        self._adv()  # 'int'
        self._adv()  # IDENT
        is_func = self._peek().type == 'LPAREN'
        self.pos = saved
        return self._func_def() if is_func else self._var_decl()

    def _const_decl(self):
        self._expect('CONST')
        self._expect('INT')
        defs = [self._const_def()]
        while self._match('COMMA'):
            defs.append(self._const_def())
        self._expect('SEMICOLON')
        return ConstDecl(defs)

    def _const_def(self):
        name = self._expect('IDENT').value
        dims = []
        while self._match('LBRACKET'):
            dims.append(self._expr())
            self._expect('RBRACKET')
        self._expect('ASSIGN')
        init = self._init_val()
        return ConstDef(name, dims, init)

    def _var_decl(self):
        self._expect('INT')
        defs = [self._var_def()]
        while self._match('COMMA'):
            defs.append(self._var_def())
        self._expect('SEMICOLON')
        return VarDecl(defs)

    def _var_def(self):
        name = self._expect('IDENT').value
        dims = []
        while self._match('LBRACKET'):
            dims.append(self._expr())
            self._expect('RBRACKET')
        init = self._init_val() if self._match('ASSIGN') else None
        return VarDef(name, dims, init)

    def _init_val(self):
        if self._peek().type == 'LBRACE':
            self._adv()
            items = []
            if self._peek().type != 'RBRACE':
                items.append(self._init_val())
                while self._match('COMMA'):
                    items.append(self._init_val())
            self._expect('RBRACE')
            return InitList(items)
        return self._expr()

    def _func_def(self):
        rt = 'void' if self._peek().type == 'VOID' else 'int'
        self._adv()
        name = self._expect('IDENT').value
        self._expect('LPAREN')
        params = []
        if self._peek().type != 'RPAREN':
            params.append(self._func_param())
            while self._match('COMMA'):
                params.append(self._func_param())
        self._expect('RPAREN')
        body = self._block()
        return FuncDef(rt, name, params, body)

    def _func_param(self):
        self._expect('INT')
        name = self._expect('IDENT').value
        if self._match('LBRACKET'):
            self._expect('RBRACKET')
            dims = [None]
            while self._match('LBRACKET'):
                dims.append(self._expr())
                self._expect('RBRACKET')
            return FuncParam(name, True, dims)
        return FuncParam(name, False, [])

    def _block(self):
        self._expect('LBRACE')
        items = []
        while self._peek().type != 'RBRACE':
            items.append(self._block_item())
        self._expect('RBRACE')
        return Block(items)

    def _block_item(self):
        if self._peek().type == 'CONST':
            return self._const_decl()
        if self._peek().type == 'INT':
            return self._var_decl()
        return self._stmt()

    def _stmt(self):
        tp = self._peek().type
        if tp == 'LBRACE':
            return self._block()
        if tp == 'IF':
            return self._if_stmt()
        if tp == 'WHILE':
            return self._while_stmt()
        if tp == 'BREAK':
            self._adv()
            self._expect('SEMICOLON')
            return BreakStmt()
        if tp == 'CONTINUE':
            self._adv()
            self._expect('SEMICOLON')
            return ContinueStmt()
        if tp == 'RETURN':
            self._adv()
            ex = None if self._peek().type == 'SEMICOLON' else self._expr()
            self._expect('SEMICOLON')
            return ReturnStmt(ex)
        if tp == 'SEMICOLON':
            self._adv()
            return ExprStmt(None)
        # Expression or assignment
        ex = self._expr()
        if self._peek().type == 'ASSIGN':
            self._adv()
            rhs = self._expr()
            self._expect('SEMICOLON')
            return AssignStmt(ex, rhs)
        self._expect('SEMICOLON')
        return ExprStmt(ex)

    def _if_stmt(self):
        self._expect('IF')
        self._expect('LPAREN')
        c = self._expr()
        self._expect('RPAREN')
        t = self._stmt()
        e = self._stmt() if self._match('ELSE') else None
        return IfStmt(c, t, e)

    def _while_stmt(self):
        self._expect('WHILE')
        self._expect('LPAREN')
        c = self._expr()
        self._expect('RPAREN')
        b = self._stmt()
        return WhileStmt(c, b)

    # ---- Expression parsing (precedence climbing) ----

    def _expr(self):
        return self._lor()

    def _lor(self):
        n = self._land()
        while self._peek().type == 'OR':
            self._adv()
            n = BinExpr('||', n, self._land())
        return n

    def _land(self):
        n = self._eq()
        while self._peek().type == 'AND':
            self._adv()
            n = BinExpr('&&', n, self._eq())
        return n

    def _eq(self):
        n = self._rel()
        while self._peek().type in ('EQ', 'NE'):
            op = self._adv().value
            n = BinExpr(op, n, self._rel())
        return n

    def _rel(self):
        n = self._add()
        while self._peek().type in ('LT', 'GT', 'LE', 'GE'):
            op = self._adv().value
            n = BinExpr(op, n, self._add())
        return n

    def _add(self):
        n = self._mul()
        while self._peek().type in ('PLUS', 'MINUS'):
            op = self._adv().value
            n = BinExpr(op, n, self._mul())
        return n

    def _mul(self):
        n = self._unary()
        while self._peek().type in ('STAR', 'SLASH', 'PERCENT'):
            op = self._adv().value
            n = BinExpr(op, n, self._unary())
        return n

    def _unary(self):
        if self._peek().type in ('PLUS', 'MINUS', 'NOT'):
            op = self._adv().value
            return UnaryExpr(op, self._unary())
        return self._primary()

    def _primary(self):
        tp = self._peek().type
        if tp == 'LPAREN':
            self._adv()
            ex = self._expr()
            self._expect('RPAREN')
            return ex
        if tp == 'INT_CONST':
            return NumLit(self._adv().value)
        if tp == 'IDENT':
            name = self._adv().value
            if self._peek().type == 'LPAREN':
                self._adv()
                args = []
                if self._peek().type != 'RPAREN':
                    args.append(self._expr())
                    while self._match('COMMA'):
                        args.append(self._expr())
                self._expect('RPAREN')
                return CallExpr(name, args)
            idx = []
            while self._peek().type == 'LBRACKET':
                self._adv()
                idx.append(self._expr())
                self._expect('RBRACKET')
            return LVal(name, idx)
        raise SyntaxError(f"Line {self._peek().line}: unexpected {self._peek().type}")


# ======================== Interpreter ========================

class _Break(Exception):
    pass

class _Continue(Exception):
    pass

class _Return(Exception):
    __slots__ = ('value',)
    def __init__(self, v):
        self.value = v


class ArrayObj:
    """Flat storage for a multi-dimensional array, supporting sub-array refs."""
    __slots__ = ('data', 'dims', 'offset')

    def __init__(self, data, dims, offset=0):
        self.data = data
        self.dims = dims
        self.offset = offset

    def _flat(self, indices):
        idx = self.offset
        stride = 1
        for d in self.dims:
            stride *= d
        for i, ix in enumerate(indices):
            stride //= self.dims[i]
            idx += ix * stride
        return idx

    def get(self, indices):
        return self.data[self._flat(indices)]

    def put(self, indices, val):
        self.data[self._flat(indices)] = val

    def sub(self, index):
        stride = 1
        for d in self.dims:
            stride *= d
        stride //= self.dims[0]
        return ArrayObj(self.data, self.dims[1:], self.offset + index * stride)


class Env:
    __slots__ = ('vars', 'parent')

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def get(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Undefined: {name}")

    def put(self, name, val):
        if name in self.vars:
            self.vars[name] = val
            return
        if self.parent:
            self.parent.put(name, val)
            return
        raise NameError(f"Undefined: {name}")

    def define(self, name, val):
        self.vars[name] = val


def _cdiv(a, b):
    """C-style integer division (truncation toward zero)."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _cmod(a, b):
    return a - _cdiv(a, b) * b


class Interpreter:
    def __init__(self):
        self.genv = Env()
        self.funcs = {}
        self._stdin = ''
        self._spos = 0

    def run(self, prog, stdin_data=''):
        self._stdin = stdin_data
        self._spos = 0
        for item in prog.items:
            if isinstance(item, FuncDef):
                self.funcs[item.name] = item
            else:
                self._exec_decl(item, self.genv, True)
        try:
            r = self._call('main', [])
        except _Return as e:
            r = e.value
        return r if r is not None else 0

    # ---- builtins ----

    def _read_int(self):
        buf = ''
        while self._spos < len(self._stdin):
            c = self._stdin[self._spos]
            if c in ' \t\n\r':
                if buf:
                    break
                self._spos += 1
            elif c.isdigit() or (c == '-' and not buf):
                buf += c
                self._spos += 1
            else:
                if buf:
                    break
                self._spos += 1
        return int(buf) if buf else 0

    def _call(self, name, args):
        if name == 'getint':
            return self._read_int()
        if name == 'getch':
            if self._spos < len(self._stdin):
                c = self._stdin[self._spos]
                self._spos += 1
                return ord(c)
            return -1
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
            sys.stdout.write(f"{n}:")
            for i in range(n):
                sys.stdout.write(f" {arr.data[arr.offset + i]}")
            sys.stdout.write("\n")
            return None
        if name in ('starttime', 'stoptime', '_sysy_starttime', '_sysy_stoptime'):
            return None

        func = self.funcs.get(name)
        if func is None:
            raise RuntimeError(f"Undefined function: {name}")
        env = Env(self.genv)
        for p, a in zip(func.params, args):
            env.define(p.name, a)
        try:
            self._exec_block(func.body, env)
        except _Return as e:
            return e.value
        return 0 if func.ret_type == 'int' else None

    # ---- declarations ----

    def _exec_decl(self, decl, env, is_global=False):
        defs = decl.defs
        for d in defs:
            if d.dims:
                dims = [self._eval(dm, env) for dm in d.dims]
                total = 1
                for x in dims:
                    total *= x
                data = [0] * total
                if d.init is not None:
                    if isinstance(d.init, InitList):
                        self._fill_init(data, dims, 0, d.init.items, env)
                    else:
                        data[0] = self._eval(d.init, env)
                env.define(d.name, ArrayObj(data, dims))
            else:
                if d.init is not None:
                    env.define(d.name, self._eval(d.init, env))
                elif is_global:
                    env.define(d.name, 0)
                else:
                    env.define(d.name, 0)

    def _fill_init(self, data, dims, offset, items, env):
        """Fill array data using SysY brace-elision rules. Returns items consumed."""
        if len(dims) == 1:
            consumed = 0
            for i in range(dims[0]):
                if consumed >= len(items):
                    break
                it = items[consumed]
                if isinstance(it, InitList):
                    if it.items:
                        data[offset + i] = self._eval(it.items[0], env)
                    consumed += 1
                else:
                    data[offset + i] = self._eval(it, env)
                    consumed += 1
            return consumed

        sub = 1
        for d in dims[1:]:
            sub *= d
        consumed = 0
        pos = 0
        while consumed < len(items) and pos < dims[0]:
            it = items[consumed]
            if isinstance(it, InitList):
                self._fill_init(data, dims[1:], offset + pos * sub, it.items, env)
                consumed += 1
                pos += 1
            else:
                sc = self._fill_init(data, dims[1:], offset + pos * sub, items[consumed:], env)
                consumed += sc
                pos += 1
        return consumed

    # ---- statements ----

    def _exec_block(self, block, env):
        child = Env(env)
        for item in block.items:
            if isinstance(item, (ConstDecl, VarDecl)):
                self._exec_decl(item, child)
            else:
                self._exec_stmt(item, child)

    def _exec_stmt(self, s, env):
        if isinstance(s, Block):
            self._exec_block(s, env)
        elif isinstance(s, AssignStmt):
            val = self._eval(s.expr, env)
            var = env.get(s.lval.name)
            if isinstance(var, ArrayObj):
                idx = [self._eval(i, env) for i in s.lval.indices]
                var.put(idx, val)
            else:
                env.put(s.lval.name, val)
        elif isinstance(s, ExprStmt):
            if s.expr is not None:
                self._eval(s.expr, env)
        elif isinstance(s, IfStmt):
            if self._eval(s.cond, env) != 0:
                self._exec_stmt(s.then_s, env)
            elif s.else_s is not None:
                self._exec_stmt(s.else_s, env)
        elif isinstance(s, WhileStmt):
            while self._eval(s.cond, env) != 0:
                try:
                    self._exec_stmt(s.body, env)
                except _Break:
                    break
                except _Continue:
                    continue
        elif isinstance(s, BreakStmt):
            raise _Break()
        elif isinstance(s, ContinueStmt):
            raise _Continue()
        elif isinstance(s, ReturnStmt):
            raise _Return(self._eval(s.expr, env) if s.expr else None)

    # ---- expression evaluation ----

    def _eval(self, ex, env):
        if isinstance(ex, NumLit):
            return ex.value

        if isinstance(ex, LVal):
            var = env.get(ex.name)
            if isinstance(var, ArrayObj):
                if ex.indices:
                    idx = [self._eval(i, env) for i in ex.indices]
                    if len(idx) == len(var.dims):
                        return var.get(idx)
                    # Partial indexing — return sub-array ref
                    arr = var
                    for ix in idx:
                        arr = arr.sub(ix)
                    return arr
                return var
            return var

        if isinstance(ex, BinExpr):
            if ex.op == '||':
                return 1 if (self._eval(ex.left, env) != 0 or self._eval(ex.right, env) != 0) else 0
            if ex.op == '&&':
                return 1 if (self._eval(ex.left, env) != 0 and self._eval(ex.right, env) != 0) else 0
            lv = self._eval(ex.left, env)
            rv = self._eval(ex.right, env)
            op = ex.op
            if op == '+': return lv + rv
            if op == '-': return lv - rv
            if op == '*': return lv * rv
            if op == '/': return _cdiv(lv, rv)
            if op == '%': return _cmod(lv, rv)
            if op == '<': return 1 if lv < rv else 0
            if op == '>': return 1 if lv > rv else 0
            if op == '<=': return 1 if lv <= rv else 0
            if op == '>=': return 1 if lv >= rv else 0
            if op == '==': return 1 if lv == rv else 0
            if op == '!=': return 1 if lv != rv else 0

        if isinstance(ex, UnaryExpr):
            v = self._eval(ex.operand, env)
            if ex.op == '+': return v
            if ex.op == '-': return -v
            if ex.op == '!': return 1 if v == 0 else 0

        if isinstance(ex, CallExpr):
            args = [self._eval(a, env) for a in ex.args]
            return self._call(ex.name, args)

        raise RuntimeError(f"Unknown node: {type(ex).__name__}")


# ======================== Main ========================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_interp <file.sy>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        src = f.read()

    stdin_data = ''
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read()

    tokens = Lexer(src).tokens
    prog = Parser(tokens).parse()
    interp = Interpreter()
    ret = interp.run(prog, stdin_data)
    sys.exit(ret % 256)


if __name__ == '__main__':
    main()
