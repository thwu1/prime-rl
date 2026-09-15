#!/usr/bin/env python3
"""
SysY to LLVM IR Compiler

Compiles SysY source to LLVM IR (.ll) with opaque pointer syntax (LLVM 18+).
Generated IR declares external refs to SysY runtime library functions which
must be linked separately (e.g., via llvm-link with compiled sylib.c).

"""
import sys


# ====================== Lexer ======================

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


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1
    while i < n:
        ch = source[i]
        if ch in ' \t\r':
            i += 1
            continue
        if ch == '\n':
            line += 1
            i += 1
            continue
        if ch == '/' and i + 1 < n and source[i + 1] == '/':
            i += 2
            while i < n and source[i] != '\n':
                i += 1
            continue
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
                i = n
            continue
        if i + 1 < n and source[i:i + 2] in TWO_CHAR_OPS:
            tok = source[i:i + 2]
            tokens.append(Token(tok, tok, line))
            i += 2
            continue
        if ch in '+-*/%<>=!()[]{}.,;':
            tokens.append(Token(ch, ch, line))
            i += 1
            continue
        if ch.isdigit():
            start = i
            if ch == '0' and i + 1 < n and source[i + 1] in 'xX':
                i += 2
                while i < n and source[i] in '0123456789abcdefABCDEF':
                    i += 1
                tokens.append(Token('INT', int(source[start:i], 16), line))
            elif ch == '0' and i + 1 < n and source[i + 1] in '01234567':
                i += 1
                while i < n and source[i] in '01234567':
                    i += 1
                tokens.append(Token('INT', int(source[start:i], 8), line))
            else:
                while i < n and source[i].isdigit():
                    i += 1
                tokens.append(Token('INT', int(source[start:i]), line))
            continue
        if ch.isalpha() or ch == '_':
            start = i
            i += 1
            while i < n and (source[i].isalnum() or source[i] == '_'):
                i += 1
            word = source[start:i]
            tokens.append(Token(word if word in KEYWORDS else 'IDENT', word, line))
            continue
        raise SyntaxError(f"Unexpected character '{ch}' at line {line}")
    tokens.append(Token('EOF', None, line))
    return tokens


# ====================== Parser ======================

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
                f"at line {tok.line}")
        return tok

    def match(self, tp):
        if self.peek().type == tp:
            return self.advance()
        return None

    def parse(self):
        decls = []
        while self.peek().type != 'EOF':
            decls.append(self._global())
        return ('program', decls)

    def _global(self):
        if self.peek().type == 'const':
            return self._const_decl()
        if self.peek().type == 'void':
            return self._func_def()
        saved = self.pos
        self.expect('int')
        self.expect('IDENT')
        is_func = self.peek().type == '('
        self.pos = saved
        return self._func_def() if is_func else self._var_decl()

    def _const_decl(self):
        self.expect('const')
        self.expect('int')
        defs = [self._const_def()]
        while self.match(','):
            defs.append(self._const_def())
        self.expect(';')
        return ('const_decl', defs)

    def _const_def(self):
        name = self.expect('IDENT').value
        dims = []
        while self.match('['):
            dims.append(self._exp())
            self.expect(']')
        self.expect('=')
        init = self._init_val()
        return ('const_def', name, dims, init)

    def _var_decl(self):
        self.expect('int')
        defs = [self._var_def()]
        while self.match(','):
            defs.append(self._var_def())
        self.expect(';')
        return ('var_decl', defs)

    def _var_def(self):
        name = self.expect('IDENT').value
        dims = []
        while self.match('['):
            dims.append(self._exp())
            self.expect(']')
        init = self._init_val() if self.match('=') else None
        return ('var_def', name, dims, init)

    def _init_val(self):
        if self.match('{'):
            vals = []
            if self.peek().type != '}':
                vals.append(self._init_val())
                while self.match(','):
                    vals.append(self._init_val())
            self.expect('}')
            return ('init_list', vals)
        return self._exp()

    def _func_def(self):
        rt = self.advance().value
        name = self.expect('IDENT').value
        self.expect('(')
        params = []
        if self.peek().type != ')':
            params.append(self._func_param())
            while self.match(','):
                params.append(self._func_param())
        self.expect(')')
        body = self._block()
        return ('func_def', rt, name, params, body)

    def _func_param(self):
        self.expect('int')
        name = self.expect('IDENT').value
        dims = None
        if self.match('['):
            self.expect(']')
            dims = [None]
            while self.match('['):
                dims.append(self._exp())
                self.expect(']')
        return ('param', name, dims)

    def _block(self):
        self.expect('{')
        items = []
        while self.peek().type != '}':
            items.append(self._block_item())
        self.expect('}')
        return ('block', items)

    def _block_item(self):
        if self.peek().type == 'const':
            return self._const_decl()
        if self.peek().type == 'int':
            return self._var_decl()
        return self._stmt()

    def _stmt(self):
        tp = self.peek().type
        if tp == '{':
            return self._block()
        if tp == 'if':
            self.advance()
            self.expect('(')
            cond = self._exp()
            self.expect(')')
            then = self._stmt()
            els = self._stmt() if self.match('else') else None
            return ('if', cond, then, els)
        if tp == 'while':
            self.advance()
            self.expect('(')
            cond = self._exp()
            self.expect(')')
            return ('while', cond, self._stmt())
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
            val = None if self.peek().type == ';' else self._exp()
            self.expect(';')
            return ('return', val)
        if tp == ';':
            self.advance()
            return ('empty',)
        exp = self._exp()
        if self.match('='):
            rhs = self._exp()
            self.expect(';')
            return ('assign', exp, rhs)
        self.expect(';')
        return ('expr_stmt', exp)

    def _exp(self):
        return self._lor()

    def _lor(self):
        left = self._land()
        while self.peek().type == '||':
            self.advance()
            left = ('||', left, self._land())
        return left

    def _land(self):
        left = self._eq()
        while self.peek().type == '&&':
            self.advance()
            left = ('&&', left, self._eq())
        return left

    def _eq(self):
        left = self._rel()
        while self.peek().type in ('==', '!='):
            op = self.advance().type
            left = (op, left, self._rel())
        return left

    def _rel(self):
        left = self._add()
        while self.peek().type in ('<', '>', '<=', '>='):
            op = self.advance().type
            left = (op, left, self._add())
        return left

    def _add(self):
        left = self._mul()
        while self.peek().type in ('+', '-'):
            op = self.advance().type
            left = (op, left, self._mul())
        return left

    def _mul(self):
        left = self._unary()
        while self.peek().type in ('*', '/', '%'):
            op = self.advance().type
            left = (op, left, self._unary())
        return left

    def _unary(self):
        if self.peek().type in ('+', '-', '!'):
            op = self.advance().type
            return ('u' + op, self._unary())
        if (self.peek().type == 'IDENT'
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].type == '('):
            name = self.advance().value
            self.expect('(')
            args = []
            if self.peek().type != ')':
                args.append(self._exp())
                while self.match(','):
                    args.append(self._exp())
            self.expect(')')
            return ('call', name, args)
        return self._primary()

    def _primary(self):
        if self.match('('):
            exp = self._exp()
            self.expect(')')
            return exp
        if self.peek().type == 'INT':
            return ('int', self.advance().value)
        if self.peek().type == 'IDENT':
            name = self.advance().value
            indices = []
            while self.peek().type == '[':
                self.advance()
                indices.append(self._exp())
                self.expect(']')
            return ('index', name, indices) if indices else ('var', name)
        raise SyntaxError(
            f"Unexpected token '{self.peek().type}' at line {self.peek().line}")


# ====================== Scope ======================

class Scope:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def define(self, name, info):
        self.vars[name] = info

    def lookup(self, name):
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.lookup(name)
        raise KeyError(f"Undefined: {name}")


# ====================== LLVM IR Generator ======================

class IRGen:
    def __init__(self):
        self.lines = []
        self.tc = 0       # temp counter (per function)
        self.lc = 0       # label counter (per function)
        self.scope = None  # current scope (None at global level)
        self.gscope = Scope()
        self.terminated = False
        self.loops = []    # stack of (continue_label, break_label)
        self.funcs = {}    # name -> (ret_type, [param_llvm_types])

    def tmp(self):
        self.tc += 1
        return f"%t{self.tc}"

    def lbl(self, prefix="L"):
        self.lc += 1
        return f"{prefix}{self.lc}"

    def out(self, s):
        if not self.terminated:
            self.lines.append("  " + s)

    def raw(self, s):
        self.lines.append(s)

    def emit_label(self, label):
        self.lines.append(f"{label}:")
        self.terminated = False

    def br(self, label):
        if not self.terminated:
            self.out(f"br label %{label}")
            self.terminated = True

    def arr_type(self, dims):
        """Build LLVM array type: [2 x [3 x i32]] for dims=[2,3]."""
        t = "i32"
        for d in reversed(dims):
            t = f"[{d} x {t}]"
        return t

    # ---- Compile-time constant evaluation ----

    def _ce(self, node):
        k = node[0]
        if k == 'int':
            return node[1]
        if k == 'var':
            info = (self.scope or self.gscope).lookup(node[1])
            return info.get('cv', 0)
        if k == 'u+':
            return self._ce(node[1])
        if k == 'u-':
            return -self._ce(node[1])
        if k == 'u!':
            return 0 if self._ce(node[1]) else 1
        a, b = self._ce(node[1]), self._ce(node[2])
        if k == '+': return a + b
        if k == '-': return a - b
        if k == '*': return a * b
        if k == '/':
            q = abs(a) // abs(b)
            return q if (a >= 0) == (b >= 0) else -q
        if k == '%':
            q = abs(a) // abs(b)
            q = q if (a >= 0) == (b >= 0) else -q
            return a - q * b
        raise RuntimeError(f"Cannot const-evaluate: {k}")

    def _flat_ce(self, node, dims):
        total = 1
        for d in dims:
            total *= d
        flat = [0] * total
        self._fill_ce(node, dims, flat, 0)
        return flat

    def _fill_ce(self, node, dims, flat, off):
        if not dims:
            flat[off] = self._ce(node)
            return 1
        if isinstance(node, tuple) and node[0] == 'init_list':
            sz = 1
            for d in dims[1:]:
                sz *= d
            pos = 0
            for v in node[1]:
                if isinstance(v, tuple) and v[0] == 'init_list':
                    self._fill_ce(v, dims[1:], flat, off + pos)
                    pos += sz
                else:
                    flat[off + pos] = self._ce(v)
                    pos += 1
            return pos
        flat[off] = self._ce(node)
        return 1

    def _fmt_ac(self, flat, dims):
        """Format flat array as LLVM constant: [i32 1, i32 2, ...]."""
        if len(dims) == 1:
            return "[" + ", ".join(f"i32 {v}" for v in flat) + "]"
        isz = 1
        for d in dims[1:]:
            isz *= d
        it = self.arr_type(dims[1:])
        parts = []
        for i in range(dims[0]):
            chunk = flat[i * isz:(i + 1) * isz]
            parts.append(f"{it} {self._fmt_ac(chunk, dims[1:])}")
        return "[" + ", ".join(parts) + "]"

    # ---- Top-level generation ----

    def generate(self, program):
        _, decls = program

        # First pass: collect function signatures
        for d in decls:
            if d[0] == 'func_def':
                _, rt, name, params, _ = d
                ptypes = ['ptr' if p[2] is not None else 'i32' for p in params]
                self.funcs[name] = (rt, ptypes)

        # Emit runtime library external declarations
        self.raw("declare i32 @getint()")
        self.raw("declare i32 @getch()")
        self.raw("declare i32 @getarray(ptr)")
        self.raw("declare void @putint(i32)")
        self.raw("declare void @putch(i32)")
        self.raw("declare void @putarray(i32, ptr)")
        self.raw("")

        # Process global declarations
        for d in decls:
            if d[0] == 'var_decl':
                for vd in d[1]:
                    self._gvar(vd, False)
            elif d[0] == 'const_decl':
                for cd in d[1]:
                    self._gvar(cd, True)
        self.raw("")

        # Process function definitions
        for d in decls:
            if d[0] == 'func_def':
                self._func(d)

        return "\n".join(self.lines)

    # ---- Global variable/constant declarations ----

    def _gvar(self, node, const):
        _, name, dim_nodes, init = node
        ir = f"@{name}"
        kw = 'constant' if const else 'global'
        if dim_nodes:
            dims = [self._ce(d) for d in dim_nodes]
            t = self.arr_type(dims)
            if init:
                vs = self._flat_ce(init, dims)
                self.raw(f"{ir} = {kw} {t} {self._fmt_ac(vs, dims)}")
            else:
                self.raw(f"{ir} = global {t} zeroinitializer")
            self.gscope.define(name, {
                'ir': ir, 'k': 'arr', 'dims': dims, 'at': t
            })
        else:
            v = self._ce(init) if init else 0
            self.raw(f"{ir} = {kw} i32 {v}")
            info = {'ir': ir, 'k': 'sc', 'dims': [], 'at': 'i32'}
            if const:
                info['cv'] = v
            self.gscope.define(name, info)

    # ---- Function definitions ----

    def _func(self, node):
        _, rt, name, params, body = node

        # Build LLVM parameter list
        pstrs = []
        for i, p in enumerate(params):
            pt = 'ptr' if p[2] is not None else 'i32'
            pstrs.append(f"{pt} %arg_{i}")

        rtype = 'i32' if rt == 'int' else 'void'
        self.raw(f"define {rtype} @{name}({', '.join(pstrs)}) {{")

        # Reset per-function state
        self.scope = Scope(self.gscope)
        self.tc = 0
        self.lc = 0
        self.terminated = False
        self.lines.append("entry:")

        # Alloca and store each parameter
        for i, p in enumerate(params):
            _, pn, pdims = p
            if pdims is None:
                # Scalar int parameter
                a = self.tmp()
                self.out(f"{a} = alloca i32")
                self.out(f"store i32 %arg_{i}, ptr {a}")
                self.scope.define(pn, {
                    'ir': a, 'k': 'sc', 'dims': [], 'at': 'i32'
                })
            else:
                # Array pointer parameter
                a = self.tmp()
                self.out(f"{a} = alloca ptr")
                self.out(f"store ptr %arg_{i}, ptr {a}")
                rdims = [self._ce(d) for d in pdims[1:]] if len(pdims) > 1 else []
                gt = self.arr_type(rdims) if rdims else "i32"
                self.scope.define(pn, {
                    'ir': a, 'k': 'ap', 'dims': rdims, 'gt': gt
                })

        # Generate function body
        self._block(body)

        # Implicit return if body didn't terminate
        if not self.terminated:
            if rtype == 'i32':
                self.out("ret i32 0")
            else:
                self.out("ret void")

        self.raw("}")
        self.raw("")
        self.scope = None

    # ---- Block and items ----

    def _block(self, node):
        _, items = node
        saved = self.scope
        self.scope = Scope(saved)
        for item in items:
            if self.terminated:
                break
            self._item(item)
        self.scope = saved

    def _item(self, item):
        k = item[0]
        if k == 'var_decl':
            for vd in item[1]:
                self._lvar(vd, False)
        elif k == 'const_decl':
            for cd in item[1]:
                self._lvar(cd, True)
        else:
            self._stmt(item)

    # ---- Local variable/constant declarations ----

    def _lvar(self, node, const):
        _, name, dim_nodes, init = node
        if dim_nodes:
            dims = [self._ce(d) for d in dim_nodes]
            t = self.arr_type(dims)
            a = self.tmp()
            self.out(f"{a} = alloca {t}")
            if init:
                self._arr_init(a, t, dims, init)
            else:
                # Zero-initialize
                total = 1
                for d in dims:
                    total *= d
                for idx in range(total):
                    indices = self._unflat(idx, dims)
                    p = self.tmp()
                    ixs = ", i32 0" + "".join(f", i32 {x}" for x in indices)
                    self.out(f"{p} = getelementptr {t}, ptr {a}{ixs}")
                    self.out(f"store i32 0, ptr {p}")
            self.scope.define(name, {
                'ir': a, 'k': 'arr', 'dims': dims, 'at': t
            })
        else:
            a = self.tmp()
            self.out(f"{a} = alloca i32")
            if init:
                if const:
                    v = self._ce(init)
                    self.out(f"store i32 {v}, ptr {a}")
                    self.scope.define(name, {
                        'ir': a, 'k': 'sc', 'dims': [], 'at': 'i32', 'cv': v
                    })
                else:
                    v = self._expr(init)
                    self.out(f"store i32 {v}, ptr {a}")
                    self.scope.define(name, {
                        'ir': a, 'k': 'sc', 'dims': [], 'at': 'i32'
                    })
            else:
                self.out(f"store i32 0, ptr {a}")
                self.scope.define(name, {
                    'ir': a, 'k': 'sc', 'dims': [], 'at': 'i32'
                })

    def _arr_init(self, alloca, atype, dims, init_node):
        """Initialize a local array from an initializer list."""
        total = 1
        for d in dims:
            total *= d
        flat = [None] * total
        self._collect_init(init_node, dims, flat, 0)
        for idx in range(total):
            indices = self._unflat(idx, dims)
            p = self.tmp()
            ixs = ", i32 0" + "".join(f", i32 {x}" for x in indices)
            self.out(f"{p} = getelementptr {atype}, ptr {alloca}{ixs}")
            if flat[idx] is not None:
                v = self._expr(flat[idx])
            else:
                v = "0"
            self.out(f"store i32 {v}, ptr {p}")

    def _collect_init(self, node, dims, flat, off):
        if not dims:
            flat[off] = node
            return 1
        if isinstance(node, tuple) and node[0] == 'init_list':
            sz = 1
            for d in dims[1:]:
                sz *= d
            pos = 0
            for v in node[1]:
                if isinstance(v, tuple) and v[0] == 'init_list':
                    self._collect_init(v, dims[1:], flat, off + pos)
                    pos += sz
                else:
                    flat[off + pos] = v
                    pos += 1
            return pos
        flat[off] = node
        return 1

    def _unflat(self, idx, dims):
        """Convert flat index to multi-dimensional indices."""
        r = []
        for d in reversed(dims):
            r.append(idx % d)
            idx //= d
        return list(reversed(r))

    # ---- Statement generation ----

    def _stmt(self, node):
        k = node[0]

        if k == 'block':
            self._block(node)

        elif k == 'if':
            _, cond, then_s, else_s = node
            cv = self._cond(cond)
            if else_s:
                tl = self.lbl("then")
                el = self.lbl("else")
                ml = self.lbl("ifend")
                self.out(f"br i1 {cv}, label %{tl}, label %{el}")
                self.terminated = True
                self.emit_label(tl)
                self._stmt(then_s)
                self.br(ml)
                self.emit_label(el)
                self._stmt(else_s)
                self.br(ml)
                self.emit_label(ml)
            else:
                tl = self.lbl("then")
                ml = self.lbl("ifend")
                self.out(f"br i1 {cv}, label %{tl}, label %{ml}")
                self.terminated = True
                self.emit_label(tl)
                self._stmt(then_s)
                self.br(ml)
                self.emit_label(ml)

        elif k == 'while':
            _, cond, body = node
            cl = self.lbl("wcond")
            bl = self.lbl("wbody")
            el = self.lbl("wend")
            self.br(cl)
            self.emit_label(cl)
            cv = self._cond(cond)
            self.out(f"br i1 {cv}, label %{bl}, label %{el}")
            self.terminated = True
            self.loops.append((cl, el))
            self.emit_label(bl)
            self._stmt(body)
            self.br(cl)
            self.loops.pop()
            self.emit_label(el)

        elif k == 'break':
            _, el = self.loops[-1]
            self.br(el)

        elif k == 'continue':
            cl, _ = self.loops[-1]
            self.br(cl)

        elif k == 'return':
            if node[1] is not None:
                v = self._expr(node[1])
                if not self.terminated:
                    self.out(f"ret i32 {v}")
                    self.terminated = True
            else:
                if not self.terminated:
                    self.out("ret void")
                    self.terminated = True

        elif k == 'assign':
            _, lval, rhs = node
            v = self._expr(rhs)
            p = self._lval_addr(lval)
            self.out(f"store i32 {v}, ptr {p}")

        elif k == 'expr_stmt':
            self._expr(node[1])

        # 'empty' — do nothing

    # ---- Condition (i32 -> i1) ----

    def _cond(self, node):
        v = self._expr(node)
        t = self.tmp()
        self.out(f"{t} = icmp ne i32 {v}, 0")
        return t

    # ---- L-value address ----

    def _lval_addr(self, node):
        """Get ptr to an assignable location."""
        if node[0] == 'var':
            info = self.scope.lookup(node[1])
            return info['ir']
        # index
        _, name, idx_nodes = node
        info = self.scope.lookup(name)
        indices = [self._expr(ix) for ix in idx_nodes]
        return self._gep(info, indices)

    # ---- GEP (array element access) ----

    def _gep(self, info, indices):
        """Generate GEP to access an array element, return ptr."""
        if info['k'] == 'arr':
            # Locally/globally allocated array
            t = info['at']
            p = self.tmp()
            ixs = ", i32 0" + "".join(f", i32 {ix}" for ix in indices)
            self.out(f"{p} = getelementptr {t}, ptr {info['ir']}{ixs}")
            return p
        else:
            # Array pointer parameter ('ap')
            ap = self.tmp()
            self.out(f"{ap} = load ptr, ptr {info['ir']}")
            gt = info['gt']
            p = self.tmp()
            ixs = "".join(f", i32 {ix}" for ix in indices)
            self.out(f"{p} = getelementptr {gt}, ptr {ap}{ixs}")
            return p

    # ---- Expression generation ----

    def _expr(self, node):
        """Generate expression code, return i32 value name."""
        k = node[0]

        if k == 'int':
            return str(node[1])

        if k == 'var':
            info = self.scope.lookup(node[1])
            t = self.tmp()
            self.out(f"{t} = load i32, ptr {info['ir']}")
            return t

        if k == 'index':
            _, name, idx_nodes = node
            info = self.scope.lookup(name)
            indices = [self._expr(ix) for ix in idx_nodes]
            p = self._gep(info, indices)
            t = self.tmp()
            self.out(f"{t} = load i32, ptr {p}")
            return t

        if k == 'call':
            return self._call(node[1], node[2])

        # Binary arithmetic
        if k in ('+', '-', '*', '/', '%'):
            l = self._expr(node[1])
            r = self._expr(node[2])
            t = self.tmp()
            ops = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'sdiv', '%': 'srem'}
            self.out(f"{t} = {ops[k]} i32 {l}, {r}")
            return t

        # Relational / equality
        if k in ('<', '>', '<=', '>=', '==', '!='):
            l = self._expr(node[1])
            r = self._expr(node[2])
            t = self.tmp()
            cm = {'<': 'slt', '>': 'sgt', '<=': 'sle', '>=': 'sge',
                  '==': 'eq', '!=': 'ne'}
            self.out(f"{t} = icmp {cm[k]} i32 {l}, {r}")
            t2 = self.tmp()
            self.out(f"{t2} = zext i1 {t} to i32")
            return t2

        # Short-circuit logical
        if k == '&&':
            return self._and(node)
        if k == '||':
            return self._or(node)

        # Unary
        if k == 'u+':
            return self._expr(node[1])
        if k == 'u-':
            v = self._expr(node[1])
            t = self.tmp()
            self.out(f"{t} = sub i32 0, {v}")
            return t
        if k == 'u!':
            v = self._expr(node[1])
            t = self.tmp()
            self.out(f"{t} = icmp eq i32 {v}, 0")
            t2 = self.tmp()
            self.out(f"{t2} = zext i1 {t} to i32")
            return t2

        raise RuntimeError(f"Unknown expression kind: {k}")

    # ---- Short-circuit && ----

    def _and(self, node):
        rp = self.tmp()
        self.out(f"{rp} = alloca i32")
        self.out(f"store i32 0, ptr {rp}")

        l = self._expr(node[1])
        lb = self.tmp()
        self.out(f"{lb} = icmp ne i32 {l}, 0")

        rl = self.lbl("and_rhs")
        el = self.lbl("and_end")
        self.out(f"br i1 {lb}, label %{rl}, label %{el}")
        self.terminated = True

        self.emit_label(rl)
        r = self._expr(node[2])
        rb = self.tmp()
        self.out(f"{rb} = icmp ne i32 {r}, 0")
        ri = self.tmp()
        self.out(f"{ri} = zext i1 {rb} to i32")
        self.out(f"store i32 {ri}, ptr {rp}")
        self.br(el)

        self.emit_label(el)
        res = self.tmp()
        self.out(f"{res} = load i32, ptr {rp}")
        return res

    # ---- Short-circuit || ----

    def _or(self, node):
        rp = self.tmp()
        self.out(f"{rp} = alloca i32")
        self.out(f"store i32 1, ptr {rp}")

        l = self._expr(node[1])
        lb = self.tmp()
        self.out(f"{lb} = icmp ne i32 {l}, 0")

        rl = self.lbl("or_rhs")
        el = self.lbl("or_end")
        self.out(f"br i1 {lb}, label %{el}, label %{rl}")
        self.terminated = True

        self.emit_label(rl)
        r = self._expr(node[2])
        rb = self.tmp()
        self.out(f"{rb} = icmp ne i32 {r}, 0")
        ri = self.tmp()
        self.out(f"{ri} = zext i1 {rb} to i32")
        self.out(f"store i32 {ri}, ptr {rp}")
        self.br(el)

        self.emit_label(el)
        res = self.tmp()
        self.out(f"{res} = load i32, ptr {rp}")
        return res

    # ---- Function calls ----

    def _call(self, fname, arg_nodes):
        # Determine expected parameter types
        if fname in self.funcs:
            rt, ptypes = self.funcs[fname]
        elif fname in ('getint', 'getch'):
            rt, ptypes = 'int', []
        elif fname == 'getarray':
            rt, ptypes = 'int', ['ptr']
        elif fname == 'putint':
            rt, ptypes = 'void', ['i32']
        elif fname == 'putch':
            rt, ptypes = 'void', ['i32']
        elif fname == 'putarray':
            rt, ptypes = 'void', ['i32', 'ptr']
        else:
            raise RuntimeError(f"Unknown function: {fname}")

        # Generate argument values
        args = []
        for i, an in enumerate(arg_nodes):
            if i < len(ptypes) and ptypes[i] == 'ptr':
                v = self._arr_arg(an)
                args.append(f"ptr {v}")
            else:
                v = self._expr(an)
                args.append(f"i32 {v}")

        rtype = 'i32' if rt == 'int' else 'void'
        a = ", ".join(args)
        if rtype == 'void':
            self.out(f"call void @{fname}({a})")
            return "0"
        t = self.tmp()
        self.out(f"{t} = call i32 @{fname}({a})")
        return t

    # ---- Array argument (get pointer for pass-by-reference) ----

    def _arr_arg(self, node):
        """Generate ptr value for array argument passing."""
        if node[0] == 'var':
            info = self.scope.lookup(node[1])
            if info['k'] == 'arr':
                # Local/global array: GEP to first element
                t = info['at']
                p = self.tmp()
                self.out(f"{p} = getelementptr {t}, ptr {info['ir']}, i32 0, i32 0")
                return p
            else:
                # Array pointer param: load the stored pointer
                p = self.tmp()
                self.out(f"{p} = load ptr, ptr {info['ir']}")
                return p
        elif node[0] == 'index':
            # Partial indexing (e.g., mat[i] for 2D array)
            _, name, idx_nodes = node
            info = self.scope.lookup(name)
            indices = [self._expr(ix) for ix in idx_nodes]
            if info['k'] == 'arr':
                t = info['at']
                p = self.tmp()
                ixs = ", i32 0" + "".join(f", i32 {ix}" for ix in indices)
                self.out(f"{p} = getelementptr {t}, ptr {info['ir']}{ixs}")
                return p
            else:
                ap = self.tmp()
                self.out(f"{ap} = load ptr, ptr {info['ir']}")
                gt = info['gt']
                p = self.tmp()
                ixs = "".join(f", i32 {ix}" for ix in indices)
                self.out(f"{p} = getelementptr {gt}, ptr {ap}{ixs}")
                return p
        raise RuntimeError(f"Cannot generate array arg for: {node}")


# ====================== Main ======================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_compiler.py <input.sy> [output.ll]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        source = f.read()

    tokens = tokenize(source)
    parser = Parser(tokens)
    program = parser.parse()

    gen = IRGen()
    ir = gen.generate(program)

    if len(sys.argv) > 2:
        with open(sys.argv[2], 'w') as f:
            f.write(ir + "\n")
    else:
        print(ir)


if __name__ == '__main__':
    main()
