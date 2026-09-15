#!/usr/bin/env python3
"""SysY to LLVM IR compiler — reference implementation."""
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


# ======================== Utilities ========================

def _cdiv(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


def _cmod(a, b):
    return a - _cdiv(a, b) * b


# ======================== Variable Info ========================

class VarInfo:
    """Tracks an LLVM register/global and its type shape."""
    __slots__ = ('reg', 'kind', 'dims', 'inner_dims', 'const_val')

    def __init__(self, reg, kind, dims=None, inner_dims=None, const_val=None):
        self.reg = reg             # LLVM register (%name) or global (@name)
        self.kind = kind           # 'scalar', 'array', 'array_param', 'const'
        self.dims = dims or []     # array dimensions for kind='array'
        self.inner_dims = inner_dims or []  # known inner dims for kind='array_param'
        self.const_val = const_val # compile-time value for kind='const'


# ======================== LLVM IR Code Generator ========================

class IRGen:
    def __init__(self):
        self.output = []       # accumulated output lines
        self.func_lines = []   # lines for current function
        self.temp_id = 0
        self.label_id = 0
        self.scopes = [{}]     # scope stack: list of {name: VarInfo}
        self.break_target = None
        self.continue_target = None
        self.current_ret_type = None
        self.terminated = False
        self.name_counts = {}  # for unique local register names
        self.func_sigs = {}    # name -> FuncDef (for calling conventions)

    # ---- Utility ----

    def new_temp(self):
        self.temp_id += 1
        return f'%t{self.temp_id}'

    def new_label(self, prefix='L'):
        self.label_id += 1
        return f'{prefix}{self.label_id}'

    def unique_reg(self, base):
        """Generate a unique local register name from a base name."""
        if base not in self.name_counts:
            self.name_counts[base] = 0
            return f'%{base}'
        self.name_counts[base] += 1
        return f'%{base}.{self.name_counts[base]}'

    def emit(self, line):
        """Emit a regular (non-terminator) instruction."""
        self.func_lines.append('  ' + line)

    def emit_term(self, line):
        """Emit a terminator instruction (skipped if block already terminated)."""
        if not self.terminated:
            self.func_lines.append('  ' + line)
            self.terminated = True

    def emit_label(self, label):
        """Start a new basic block. Adds fallthrough branch if previous block unterminated."""
        if not self.terminated:
            self.func_lines.append(f'  br label %{label}')
        self.func_lines.append(f'{label}:')
        self.terminated = False

    def emit_global(self, line):
        self.output.append(line)

    # ---- Scope ----

    def push_scope(self):
        self.scopes.append({})

    def pop_scope(self):
        self.scopes.pop()

    def define_var(self, name, info):
        self.scopes[-1][name] = info

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    # ---- Types ----

    def llvm_type(self, dims):
        """Build LLVM type from array dimensions. [] -> i32, [3] -> [3 x i32], etc."""
        t = 'i32'
        for d in reversed(dims):
            t = f'[{d} x {t}]'
        return t

    # ---- Compile-time constant evaluation ----

    def const_eval(self, expr):
        """Evaluate a constant expression at compile time."""
        if isinstance(expr, NumLit):
            return expr.value
        if isinstance(expr, LVal) and not expr.indices:
            info = self.lookup(expr.name)
            if info and info.kind == 'const':
                return info.const_val
            raise ValueError(f"Not a compile-time constant: {expr.name}")
        if isinstance(expr, BinExpr):
            l = self.const_eval(expr.left)
            r = self.const_eval(expr.right)
            ops = {
                '+': lambda a, b: a + b, '-': lambda a, b: a - b,
                '*': lambda a, b: a * b, '/': lambda a, b: _cdiv(a, b),
                '%': lambda a, b: _cmod(a, b),
                '<': lambda a, b: int(a < b), '>': lambda a, b: int(a > b),
                '<=': lambda a, b: int(a <= b), '>=': lambda a, b: int(a >= b),
                '==': lambda a, b: int(a == b), '!=': lambda a, b: int(a != b),
                '&&': lambda a, b: int(a != 0 and b != 0),
                '||': lambda a, b: int(a != 0 or b != 0),
            }
            return ops[expr.op](l, r)
        if isinstance(expr, UnaryExpr):
            v = self.const_eval(expr.operand)
            if expr.op == '+': return v
            if expr.op == '-': return -v
            if expr.op == '!': return int(v == 0)
        raise ValueError(f"Cannot evaluate at compile time")

    # ---- Array initialization helpers ----

    def flat_to_multi(self, flat_idx, dims):
        """Convert flat index to multi-dimensional indices."""
        indices = []
        for d in reversed(dims):
            indices.append(flat_idx % d)
            flat_idx //= d
        indices.reverse()
        return indices

    def compute_init_values(self, init, dims):
        """Compute flat array of values from an InitList using brace-elision rules."""
        total = 1
        for d in dims:
            total *= d
        data = [0] * total
        if init and isinstance(init, InitList):
            self._fill_init(data, dims, 0, init.items)
        return data

    def _fill_init(self, data, dims, offset, items):
        """Fill data array from InitList items (compile-time constants)."""
        if len(dims) == 1:
            consumed = 0
            for i in range(dims[0]):
                if consumed >= len(items):
                    break
                it = items[consumed]
                if isinstance(it, InitList):
                    if it.items:
                        data[offset + i] = self.const_eval(it.items[0])
                    consumed += 1
                else:
                    data[offset + i] = self.const_eval(it)
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
                self._fill_init(data, dims[1:], offset + pos * sub, it.items)
                consumed += 1
                pos += 1
            else:
                sc = self._fill_init(data, dims[1:], offset + pos * sub, items[consumed:])
                consumed += sc
                pos += 1
        return consumed

    def format_global_init(self, dims, values):
        """Format a global array initializer as LLVM IR literal."""
        if len(dims) == 1:
            elems = ', '.join(f'i32 {v}' for v in values[:dims[0]])
            return f'[{dims[0]} x i32] [{elems}]'
        sub = 1
        for d in dims[1:]:
            sub *= d
        inner_type = self.llvm_type(dims[1:])
        parts = []
        for i in range(dims[0]):
            sv = values[i * sub:(i + 1) * sub]
            parts.append(self.format_global_init(dims[1:], sv))
        return f'[{dims[0]} x {inner_type}] [{", ".join(parts)}]'

    # ---- Top-level code generation ----

    def generate(self, program):
        """Generate LLVM IR for the entire program. Returns IR as string."""
        # Runtime library declarations
        self.emit_global('declare i32 @getint()')
        self.emit_global('declare i32 @getch()')
        self.emit_global('declare i32 @getarray(ptr)')
        self.emit_global('declare void @putint(i32)')
        self.emit_global('declare void @putch(i32)')
        self.emit_global('declare void @putarray(i32, ptr)')
        self.emit_global('')

        # Pre-pass: collect function signatures
        for item in program.items:
            if isinstance(item, FuncDef):
                self.func_sigs[item.name] = item

        # Generate code for each top-level item
        for item in program.items:
            if isinstance(item, FuncDef):
                self.gen_func(item)
            elif isinstance(item, (ConstDecl, VarDecl)):
                self.gen_global_decl(item)

        return '\n'.join(self.output)

    # ---- Global declarations ----

    def gen_global_decl(self, decl):
        for d in decl.defs:
            if d.dims:
                dims = [self.const_eval(dm) for dm in d.dims]
                ltype = self.llvm_type(dims)
                if d.init:
                    values = self.compute_init_values(d.init, dims)
                    if all(v == 0 for v in values):
                        self.emit_global(f'@{d.name} = global {ltype} zeroinitializer')
                    else:
                        init_str = self.format_global_init(dims, values)
                        self.emit_global(f'@{d.name} = global {init_str}')
                else:
                    self.emit_global(f'@{d.name} = global {ltype} zeroinitializer')
                self.define_var(d.name, VarInfo(f'@{d.name}', 'array', dims=dims))
            else:
                if isinstance(decl, ConstDecl):
                    val = self.const_eval(d.init)
                    self.define_var(d.name, VarInfo(None, 'const', const_val=val))
                else:
                    val = self.const_eval(d.init) if d.init else 0
                    self.emit_global(f'@{d.name} = global i32 {val}')
                    self.define_var(d.name, VarInfo(f'@{d.name}', 'scalar'))
        self.emit_global('')

    # ---- Function generation ----

    def gen_func(self, func):
        self.func_lines = []
        self.temp_id = 0
        self.name_counts = {}
        self.terminated = False
        self.current_ret_type = 'i32' if func.ret_type == 'int' else 'void'

        self.push_scope()

        # Build parameter list
        params = []
        for p in func.params:
            if p.is_array:
                params.append(f'ptr %{p.name}.arg')
            else:
                params.append(f'i32 %{p.name}.arg')

        ret_type = self.current_ret_type
        self.func_lines.append(f'define {ret_type} @{func.name}({", ".join(params)}) {{')
        self.func_lines.append('entry:')
        self.terminated = False

        # Create allocas for parameters and store incoming values
        for p in func.params:
            if p.is_array:
                reg = self.unique_reg(f'{p.name}.addr')
                self.emit(f'{reg} = alloca ptr')
                self.emit(f'store ptr %{p.name}.arg, ptr {reg}')
                inner_dims = []
                if len(p.dims) > 1:
                    for dim_expr in p.dims[1:]:
                        inner_dims.append(self.const_eval(dim_expr))
                self.define_var(p.name, VarInfo(reg, 'array_param', inner_dims=inner_dims))
            else:
                reg = self.unique_reg(f'{p.name}.addr')
                self.emit(f'{reg} = alloca i32')
                self.emit(f'store i32 %{p.name}.arg, ptr {reg}')
                self.define_var(p.name, VarInfo(reg, 'scalar'))

        # Generate body
        self.gen_block(func.body)

        # Default return if body didn't terminate
        if not self.terminated:
            if ret_type == 'void':
                self.emit_term('ret void')
            else:
                self.emit_term('ret i32 0')

        self.func_lines.append('}')
        self.func_lines.append('')
        self.output.extend(self.func_lines)
        self.pop_scope()

    # ---- Block and local declarations ----

    def gen_block(self, block):
        self.push_scope()
        for item in block.items:
            if self.terminated:
                break
            if isinstance(item, (ConstDecl, VarDecl)):
                self.gen_local_decl(item)
            else:
                self.gen_stmt(item)
        self.pop_scope()

    def gen_local_decl(self, decl):
        for d in decl.defs:
            if d.dims:
                # Array declaration
                dims = [self.const_eval(dm) for dm in d.dims]
                ltype = self.llvm_type(dims)
                reg = self.unique_reg(d.name)
                self.emit(f'{reg} = alloca {ltype}')

                total = 1
                for x in dims:
                    total *= x

                if d.init:
                    values = self.compute_init_values(d.init, dims)
                else:
                    values = [0] * total

                # Emit stores for all elements
                gep_type = ltype
                for i in range(total):
                    multi = self.flat_to_multi(i, dims)
                    idx_parts = ['i32 0'] + [f'i32 {idx}' for idx in multi]
                    addr = self.new_temp()
                    self.emit(f'{addr} = getelementptr {gep_type}, ptr {reg}, {", ".join(idx_parts)}')
                    self.emit(f'store i32 {values[i]}, ptr {addr}')

                self.define_var(d.name, VarInfo(reg, 'array', dims=dims))
            else:
                # Scalar declaration
                if isinstance(decl, ConstDecl):
                    val = self.const_eval(d.init)
                    self.define_var(d.name, VarInfo(None, 'const', const_val=val))
                else:
                    reg = self.unique_reg(d.name)
                    self.emit(f'{reg} = alloca i32')
                    if d.init:
                        val = self.gen_expr(d.init)
                        self.emit(f'store i32 {val}, ptr {reg}')
                    self.define_var(d.name, VarInfo(reg, 'scalar'))

    # ---- Statements ----

    def gen_stmt(self, stmt):
        if isinstance(stmt, Block):
            self.gen_block(stmt)
        elif isinstance(stmt, AssignStmt):
            self.gen_assign(stmt)
        elif isinstance(stmt, ExprStmt):
            if stmt.expr:
                self.gen_expr(stmt.expr)
        elif isinstance(stmt, IfStmt):
            self.gen_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self.gen_while(stmt)
        elif isinstance(stmt, BreakStmt):
            self.emit_term(f'br label %{self.break_target}')
        elif isinstance(stmt, ContinueStmt):
            self.emit_term(f'br label %{self.continue_target}')
        elif isinstance(stmt, ReturnStmt):
            if stmt.expr:
                val = self.gen_expr(stmt.expr)
                self.emit_term(f'ret i32 {val}')
            else:
                self.emit_term('ret void')

    def gen_assign(self, stmt):
        val = self.gen_expr(stmt.expr)
        info = self.lookup(stmt.lval.name)

        if info.kind == 'scalar':
            self.emit(f'store i32 {val}, ptr {info.reg}')
        elif info.kind in ('array', 'array_param'):
            addr = self.gen_array_elem_addr(info, stmt.lval.indices)
            self.emit(f'store i32 {val}, ptr {addr}')

    def gen_if(self, stmt):
        then_label = self.new_label('if.then')
        end_label = self.new_label('if.end')

        cond = self.gen_expr(stmt.cond)
        cond_bool = self.new_temp()
        self.emit(f'{cond_bool} = icmp ne i32 {cond}, 0')

        if stmt.else_s:
            else_label = self.new_label('if.else')
            self.emit_term(f'br i1 {cond_bool}, label %{then_label}, label %{else_label}')

            self.emit_label(then_label)
            self.gen_stmt(stmt.then_s)
            then_term = self.terminated
            if not self.terminated:
                self.emit_term(f'br label %{end_label}')

            self.emit_label(else_label)
            self.gen_stmt(stmt.else_s)
            else_term = self.terminated
            if not self.terminated:
                self.emit_term(f'br label %{end_label}')

            if not (then_term and else_term):
                self.emit_label(end_label)
            # else: both branches terminated, self.terminated stays True
        else:
            self.emit_term(f'br i1 {cond_bool}, label %{then_label}, label %{end_label}')

            self.emit_label(then_label)
            self.gen_stmt(stmt.then_s)
            if not self.terminated:
                self.emit_term(f'br label %{end_label}')

            self.emit_label(end_label)

    def gen_while(self, stmt):
        cond_label = self.new_label('while.cond')
        body_label = self.new_label('while.body')
        end_label = self.new_label('while.end')

        saved_break = self.break_target
        saved_continue = self.continue_target
        self.break_target = end_label
        self.continue_target = cond_label

        self.emit_term(f'br label %{cond_label}')
        self.emit_label(cond_label)

        cond = self.gen_expr(stmt.cond)
        cond_bool = self.new_temp()
        self.emit(f'{cond_bool} = icmp ne i32 {cond}, 0')
        self.emit_term(f'br i1 {cond_bool}, label %{body_label}, label %{end_label}')

        self.emit_label(body_label)
        self.gen_stmt(stmt.body)
        if not self.terminated:
            self.emit_term(f'br label %{cond_label}')

        self.emit_label(end_label)

        self.break_target = saved_break
        self.continue_target = saved_continue

    # ---- Expressions ----

    def gen_expr(self, expr):
        """Generate code for an expression. Returns an i32 value (temp or literal)."""
        if isinstance(expr, NumLit):
            return str(expr.value)

        if isinstance(expr, LVal):
            return self.gen_lval_load(expr)

        if isinstance(expr, BinExpr):
            return self.gen_binexpr(expr)

        if isinstance(expr, UnaryExpr):
            return self.gen_unary(expr)

        if isinstance(expr, CallExpr):
            return self.gen_call(expr)

        raise RuntimeError(f"Unknown expression: {type(expr).__name__}")

    def gen_lval_load(self, lval):
        """Load the value of an lval (scalar or array element)."""
        info = self.lookup(lval.name)

        if info.kind == 'const':
            return str(info.const_val)

        if info.kind == 'scalar':
            t = self.new_temp()
            self.emit(f'{t} = load i32, ptr {info.reg}')
            return t

        if info.kind in ('array', 'array_param'):
            addr = self.gen_array_elem_addr(info, lval.indices)
            t = self.new_temp()
            self.emit(f'{t} = load i32, ptr {addr}')
            return t

        raise RuntimeError(f"Cannot load: {info.kind}")

    def gen_array_elem_addr(self, info, index_exprs):
        """Compute the address of an array element."""
        indices = [self.gen_expr(idx) for idx in index_exprs]

        if info.kind == 'array':
            gep_type = self.llvm_type(info.dims)
            idx_parts = ['i32 0'] + [f'i32 {idx}' for idx in indices]
            t = self.new_temp()
            self.emit(f'{t} = getelementptr {gep_type}, ptr {info.reg}, {", ".join(idx_parts)}')
            return t

        if info.kind == 'array_param':
            base = self.new_temp()
            self.emit(f'{base} = load ptr, ptr {info.reg}')

            if not info.inner_dims:
                # int arr[] — pointer to i32 elements
                t = self.new_temp()
                self.emit(f'{t} = getelementptr i32, ptr {base}, i32 {indices[0]}')
                return t
            else:
                # int m[][N] — pointer to [N x i32] elements
                inner_type = self.llvm_type(info.inner_dims)
                idx_parts = [f'i32 {idx}' for idx in indices]
                t = self.new_temp()
                self.emit(f'{t} = getelementptr {inner_type}, ptr {base}, {", ".join(idx_parts)}')
                return t

        raise RuntimeError(f"Not an array: {info.kind}")

    def gen_array_ptr(self, lval):
        """Get a pointer for passing an array to a function."""
        info = self.lookup(lval.name)

        if lval.indices:
            # Partial indexing — get sub-array pointer
            return self.gen_array_elem_addr(info, lval.indices)

        if info.kind == 'array':
            return info.reg

        if info.kind == 'array_param':
            t = self.new_temp()
            self.emit(f'{t} = load ptr, ptr {info.reg}')
            return t

        raise RuntimeError(f"Cannot get array ptr: {info.kind}")

    def gen_binexpr(self, expr):
        # Short-circuit operators
        if expr.op == '||':
            return self.gen_or(expr)
        if expr.op == '&&':
            return self.gen_and(expr)

        lv = self.gen_expr(expr.left)
        rv = self.gen_expr(expr.right)

        op = expr.op
        if op == '+':
            t = self.new_temp()
            self.emit(f'{t} = add i32 {lv}, {rv}')
            return t
        if op == '-':
            t = self.new_temp()
            self.emit(f'{t} = sub i32 {lv}, {rv}')
            return t
        if op == '*':
            t = self.new_temp()
            self.emit(f'{t} = mul i32 {lv}, {rv}')
            return t
        if op == '/':
            t = self.new_temp()
            self.emit(f'{t} = sdiv i32 {lv}, {rv}')
            return t
        if op == '%':
            t = self.new_temp()
            self.emit(f'{t} = srem i32 {lv}, {rv}')
            return t

        # Comparison operators
        cmp_map = {
            '<': 'slt', '>': 'sgt', '<=': 'sle', '>=': 'sge',
            '==': 'eq', '!=': 'ne',
        }
        t1 = self.new_temp()
        self.emit(f'{t1} = icmp {cmp_map[op]} i32 {lv}, {rv}')
        t2 = self.new_temp()
        self.emit(f'{t2} = zext i1 {t1} to i32')
        return t2

    def gen_or(self, expr):
        """Short-circuit OR: evaluate LHS, skip RHS if true."""
        res_reg = self.new_temp()
        self.emit(f'{res_reg} = alloca i32')
        self.emit(f'store i32 1, ptr {res_reg}')

        rhs_label = self.new_label('or.rhs')
        end_label = self.new_label('or.end')

        lv = self.gen_expr(expr.left)
        lv_bool = self.new_temp()
        self.emit(f'{lv_bool} = icmp ne i32 {lv}, 0')
        self.emit_term(f'br i1 {lv_bool}, label %{end_label}, label %{rhs_label}')

        self.emit_label(rhs_label)
        rv = self.gen_expr(expr.right)
        rv_bool = self.new_temp()
        self.emit(f'{rv_bool} = icmp ne i32 {rv}, 0')
        rv_int = self.new_temp()
        self.emit(f'{rv_int} = zext i1 {rv_bool} to i32')
        self.emit(f'store i32 {rv_int}, ptr {res_reg}')
        self.emit_term(f'br label %{end_label}')

        self.emit_label(end_label)
        result = self.new_temp()
        self.emit(f'{result} = load i32, ptr {res_reg}')
        return result

    def gen_and(self, expr):
        """Short-circuit AND: evaluate LHS, skip RHS if false."""
        res_reg = self.new_temp()
        self.emit(f'{res_reg} = alloca i32')
        self.emit(f'store i32 0, ptr {res_reg}')

        rhs_label = self.new_label('and.rhs')
        end_label = self.new_label('and.end')

        lv = self.gen_expr(expr.left)
        lv_bool = self.new_temp()
        self.emit(f'{lv_bool} = icmp ne i32 {lv}, 0')
        self.emit_term(f'br i1 {lv_bool}, label %{rhs_label}, label %{end_label}')

        self.emit_label(rhs_label)
        rv = self.gen_expr(expr.right)
        rv_bool = self.new_temp()
        self.emit(f'{rv_bool} = icmp ne i32 {rv}, 0')
        rv_int = self.new_temp()
        self.emit(f'{rv_int} = zext i1 {rv_bool} to i32')
        self.emit(f'store i32 {rv_int}, ptr {res_reg}')
        self.emit_term(f'br label %{end_label}')

        self.emit_label(end_label)
        result = self.new_temp()
        self.emit(f'{result} = load i32, ptr {res_reg}')
        return result

    def gen_unary(self, expr):
        v = self.gen_expr(expr.operand)
        if expr.op == '+':
            return v
        if expr.op == '-':
            t = self.new_temp()
            self.emit(f'{t} = sub i32 0, {v}')
            return t
        if expr.op == '!':
            t1 = self.new_temp()
            self.emit(f'{t1} = icmp eq i32 {v}, 0')
            t2 = self.new_temp()
            self.emit(f'{t2} = zext i1 {t1} to i32')
            return t2
        raise RuntimeError(f"Unknown unary op: {expr.op}")

    def gen_call(self, call):
        """Generate a function call."""
        # Runtime library function signatures
        rt_sigs = {
            'getint': ('i32', []),
            'getch': ('i32', []),
            'getarray': ('i32', [True]),
            'putint': ('void', [False]),
            'putch': ('void', [False]),
            'putarray': ('void', [False, True]),
        }

        if call.name in rt_sigs:
            ret, param_is_arr = rt_sigs[call.name]
            args = []
            for i, arg_expr in enumerate(call.args):
                if param_is_arr[i]:
                    if isinstance(arg_expr, LVal):
                        ptr = self.gen_array_ptr(arg_expr)
                        args.append(f'ptr {ptr}')
                    else:
                        raise RuntimeError("Expected array argument")
                else:
                    val = self.gen_expr(arg_expr)
                    args.append(f'i32 {val}')
            arg_str = ', '.join(args)
            if ret == 'void':
                self.emit(f'call void @{call.name}({arg_str})')
                return '0'
            else:
                t = self.new_temp()
                self.emit(f'{t} = call i32 @{call.name}({arg_str})')
                return t

        # User-defined function
        func_def = self.func_sigs.get(call.name)
        if not func_def:
            raise RuntimeError(f"Unknown function: {call.name}")

        ret = 'i32' if func_def.ret_type == 'int' else 'void'
        args = []
        for i, arg_expr in enumerate(call.args):
            param = func_def.params[i]
            if param.is_array:
                if isinstance(arg_expr, LVal):
                    ptr = self.gen_array_ptr(arg_expr)
                    args.append(f'ptr {ptr}')
                else:
                    raise RuntimeError("Expected array argument")
            else:
                val = self.gen_expr(arg_expr)
                args.append(f'i32 {val}')

        arg_str = ', '.join(args)
        if ret == 'void':
            self.emit(f'call void @{call.name}({arg_str})')
            return '0'
        else:
            t = self.new_temp()
            self.emit(f'{t} = call i32 @{call.name}({arg_str})')
            return t


# ======================== Main ========================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysyc <file.sy>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        src = f.read()

    tokens = Lexer(src).tokens
    prog = Parser(tokens).parse()
    gen = IRGen()
    ir = gen.generate(prog)
    print(ir)


if __name__ == '__main__':
    main()
