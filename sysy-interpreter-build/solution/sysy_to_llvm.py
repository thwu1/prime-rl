#!/usr/bin/env python3
"""SysY to LLVM IR compiler."""
import sys

# ── Lexer ────────────────────────────────────────────────────────
KEYWORDS = frozenset(['int','void','const','if','else','while','break','continue','return'])

class Token:
    __slots__ = ('ty','val','line')
    def __init__(self, ty, val, line):
        self.ty, self.val, self.line = ty, val, line

def tokenize(source):
    tokens = []; i = 0; n = len(source); line = 1
    while i < n:
        c = source[i]
        if c in ' \t\r': i += 1; continue
        if c == '\n': i += 1; line += 1; continue
        if c == '#':
            while i < n and source[i] != '\n': i += 1
            continue
        if c == '/' and i+1 < n:
            if source[i+1] == '/':
                i += 2
                while i < n and source[i] != '\n': i += 1
                continue
            if source[i+1] == '*':
                i += 2
                while i+1 < n:
                    if source[i] == '*' and source[i+1] == '/': i += 2; break
                    if source[i] == '\n': line += 1
                    i += 1
                continue
        if c.isdigit():
            start = i
            if c == '0' and i+1 < n and source[i+1] in 'xX':
                i += 2
                while i < n and source[i] in '0123456789abcdefABCDEF': i += 1
                tokens.append(Token('NUM', int(source[start:i], 16), line))
            elif c == '0' and i+1 < n and source[i+1] in '01234567':
                i += 1
                while i < n and source[i] in '01234567': i += 1
                tokens.append(Token('NUM', int(source[start:i], 8), line))
            else:
                while i < n and source[i].isdigit(): i += 1
                tokens.append(Token('NUM', int(source[start:i]), line))
            continue
        if c.isalpha() or c == '_':
            start = i
            while i < n and (source[i].isalnum() or source[i] == '_'): i += 1
            word = source[start:i]
            tokens.append(Token(word if word in KEYWORDS else 'ID', word, line))
            continue
        if i+1 < n and source[i:i+2] in ('<=','>=','==','!=','&&','||'):
            op = source[i:i+2]; tokens.append(Token(op, op, line)); i += 2; continue
        tokens.append(Token(c, c, line)); i += 1
    tokens.append(Token('EOF', None, line))
    return tokens

# ── Parser ───────────────────────────────────────────────────────
class Parser:
    def __init__(self, tokens): self.tokens = tokens; self.pos = 0
    def cur(self): return self.tokens[self.pos]
    def eat(self, ty=None):
        tok = self.tokens[self.pos]
        if ty and tok.ty != ty:
            raise SyntaxError(f"Line {tok.line}: expected '{ty}', got '{tok.ty}'")
        self.pos += 1; return tok
    def at(self, ty): return self.tokens[self.pos].ty == ty
    def maybe(self, ty):
        if self.at(ty): return self.eat()
        return None
    def parse(self):
        decls, funcs = [], []
        while not self.at('EOF'):
            saved = self.pos; is_const = bool(self.maybe('const'))
            self.eat(); self.eat('ID')
            if not is_const and self.at('('):
                self.pos = saved; funcs.append(self.parse_func())
            else:
                self.pos = saved; decls.append(self.parse_decl())
        return ('unit', decls, funcs)
    def parse_decl(self):
        is_const = bool(self.maybe('const')); self.eat()
        defs = [self.parse_vardef()]
        while self.maybe(','): defs.append(self.parse_vardef())
        self.eat(';'); return ('decl', is_const, defs)
    def parse_vardef(self):
        name = self.eat('ID').val; dims = []
        while self.maybe('['): dims.append(self.parse_expr()); self.eat(']')
        init = self.parse_initval() if self.maybe('=') else None
        return ('vardef', name, dims, init)
    def parse_initval(self):
        if self.at('{'):
            self.eat('{')
            if self.at('}'): self.eat('}'); return ('initlist', [])
            children = [self.parse_initval()]
            while self.maybe(','):
                if self.at('}'): break
                children.append(self.parse_initval())
            self.eat('}'); return ('initlist', children)
        return ('initexpr', self.parse_expr())
    def parse_func(self):
        ret_type = self.eat().val; name = self.eat('ID').val; self.eat('(')
        params = []
        if not self.at(')'):
            params.append(self.parse_param())
            while self.maybe(','): params.append(self.parse_param())
        self.eat(')'); body = self.parse_block()
        return ('func', ret_type, name, params, body)
    def parse_param(self):
        self.eat(); name = self.eat('ID').val
        is_array = False; extra_dims = []
        if self.maybe('['):
            is_array = True; self.eat(']')
            while self.maybe('['): extra_dims.append(self.parse_expr()); self.eat(']')
        return ('param', name, is_array, extra_dims)
    def parse_block(self):
        self.eat('{'); items = []
        while not self.at('}'):
            if self.at('const') or (self.at('int') and self._is_decl()):
                items.append(self.parse_decl())
            else: items.append(self.parse_stmt())
        self.eat('}'); return ('block', items)
    def _is_decl(self):
        saved = self.pos; self.eat(); r = self.at('ID'); self.pos = saved; return r
    def parse_stmt(self):
        if self.at('{'): return self.parse_block()
        if self.at('if'):
            self.eat(); self.eat('('); cond = self.parse_expr(); self.eat(')')
            then_s = self.parse_stmt()
            else_s = self.parse_stmt() if self.maybe('else') else None
            return ('if', cond, then_s, else_s)
        if self.at('while'):
            self.eat(); self.eat('('); cond = self.parse_expr(); self.eat(')')
            return ('while', cond, self.parse_stmt())
        if self.at('break'): self.eat(); self.eat(';'); return ('break',)
        if self.at('continue'): self.eat(); self.eat(';'); return ('continue',)
        if self.at('return'):
            self.eat()
            expr = None if self.at(';') else self.parse_expr()
            self.eat(';'); return ('return', expr)
        if self.at(';'): self.eat(); return ('nop',)
        expr = self.parse_expr()
        if self.at('=') and expr[0] == 'lval':
            self.eat(); rhs = self.parse_expr(); self.eat(';')
            return ('assign', expr, rhs)
        self.eat(';'); return ('exprstmt', expr)
    def parse_expr(self): return self._lor()
    def _lor(self):
        n = self._land()
        while self.at('||'): self.eat(); n = ('||', n, self._land())
        return n
    def _land(self):
        n = self._eq()
        while self.at('&&'): self.eat(); n = ('&&', n, self._eq())
        return n
    def _eq(self):
        n = self._rel()
        while self.cur().ty in ('==','!='): op = self.eat().ty; n = (op, n, self._rel())
        return n
    def _rel(self):
        n = self._add()
        while self.cur().ty in ('<','>','<=','>='): op = self.eat().ty; n = (op, n, self._add())
        return n
    def _add(self):
        n = self._mul()
        while self.cur().ty in ('+','-'): op = self.eat().ty; n = (op, n, self._mul())
        return n
    def _mul(self):
        n = self._unary()
        while self.cur().ty in ('*','/','%'): op = self.eat().ty; n = (op, n, self._unary())
        return n
    def _unary(self):
        if self.cur().ty in ('+','-','!'): op = self.eat().ty; return ('unary_'+op, self._unary())
        return self._primary()
    def _primary(self):
        if self.at('('): self.eat(); e = self.parse_expr(); self.eat(')'); return e
        if self.at('NUM'): return ('num', self.eat().val)
        if self.at('ID'):
            name = self.eat().val
            if self.at('('):
                self.eat(); args = []
                if not self.at(')'):
                    args.append(self.parse_expr())
                    while self.maybe(','): args.append(self.parse_expr())
                self.eat(')'); return ('call', name, args)
            indices = []
            while self.at('['): self.eat(); indices.append(self.parse_expr()); self.eat(']')
            return ('lval', name, indices)
        raise SyntaxError(f"Line {self.cur().line}: unexpected '{self.cur().val}'")

# ── Constant evaluator ───────────────────────────────────────────
def const_eval(node, consts=None):
    if consts is None: consts = {}
    tag = node[0]
    if tag == 'num': return node[1]
    if tag == 'lval':
        name = node[1]
        if not node[2] and name in consts: return consts[name]
        return None
    if tag == 'unary_+':
        v = const_eval(node[1], consts)
        return v if v is not None else None
    if tag == 'unary_-':
        v = const_eval(node[1], consts)
        return -v if v is not None else None
    if tag == 'unary_!':
        v = const_eval(node[1], consts)
        return int(not v) if v is not None else None
    if tag in ('+','-','*','/','%','==','!=','<','>','<=','>='):
        l = const_eval(node[1], consts)
        r = const_eval(node[2], consts)
        if l is None or r is None: return None
        if tag == '+': return l + r
        if tag == '-': return l - r
        if tag == '*': return l * r
        if tag == '/':
            if r == 0: return 0
            s = -1 if (l < 0) != (r < 0) else 1
            return s * (abs(l) // abs(r))
        if tag == '%':
            if r == 0: return 0
            s = -1 if (l < 0) != (r < 0) else 1
            q = s * (abs(l) // abs(r))
            return l - q * r
        if tag == '==': return int(l == r)
        if tag == '!=': return int(l != r)
        if tag == '<': return int(l < r)
        if tag == '>': return int(l > r)
        if tag == '<=': return int(l <= r)
        if tag == '>=': return int(l >= r)
    if tag == '||':
        l = const_eval(node[1], consts)
        r = const_eval(node[2], consts)
        if l is None or r is None: return None
        return int(l or r)
    if tag == '&&':
        l = const_eval(node[1], consts)
        r = const_eval(node[2], consts)
        if l is None or r is None: return None
        return int(l and r)
    return None

# ── LLVM IR Code Generator ───────────────────────────────────────
class IRGen:
    def __init__(self):
        self.lines = []
        self.tmp_counter = 0
        self.label_counter = 0
        self.globals = {}        # name -> (ir_name, dims, is_const)
        self.locals = {}         # name -> (ir_name, dims, is_ptr_param)
        self.scope_stack = []
        self.functions = {}      # name -> (ret_type, params)
        self.break_label = None
        self.continue_label = None
        self.const_vals = {}     # name -> int value for compile-time consts

    def tmp(self):
        self.tmp_counter += 1; return f"%t{self.tmp_counter}"
    def label(self, prefix="L"):
        self.label_counter += 1; return f"{prefix}{self.label_counter}"
    def emit(self, s): self.lines.append(s)
    def emit_label(self, name): self.lines.append(f"{name}:")
    def push_scope(self): self.scope_stack.append(dict(self.locals))
    def pop_scope(self): self.locals = self.scope_stack.pop()
    def lookup(self, name):
        if name in self.locals: return ('local', self.locals[name])
        if name in self.globals: return ('global', self.globals[name])
        return None

    def array_type(self, dims):
        t = "i32"
        for d in reversed(dims): t = f"[{d} x {t}]"
        return t

    def flatten_init(self, init, dims):
        total = 1
        for d in dims: total *= d
        data = [0] * total
        if init: self._fill_init(data, 0, dims, init)
        return data

    def _fill_init(self, data, offset, dims, init):
        if init[0] == 'initexpr':
            v = const_eval(init[1], self.const_vals)
            if v is None: v = 0
            data[offset] = v; return
        children = init[1]
        if not dims: return
        if len(dims) == 1:
            for ci, child in enumerate(children):
                if ci >= dims[0]: break
                if child[0] == 'initexpr':
                    v = const_eval(child[1], self.const_vals)
                    if v is None: v = 0
                    data[offset + ci] = v
                elif child[0] == 'initlist' and child[1]:
                    if child[1][0][0] == 'initexpr':
                        v = const_eval(child[1][0][1], self.const_vals)
                        if v is None: v = 0
                        data[offset + ci] = v
            return
        stride = 1
        for d in dims[1:]: stride *= d
        pos = 0; ci = 0
        while ci < len(children) and pos < dims[0]:
            child = children[ci]
            if child[0] == 'initlist':
                self._fill_init(data, offset + pos * stride, dims[1:], child)
                pos += 1; ci += 1
            else:
                bare = []
                while ci < len(children) and children[ci][0] == 'initexpr' and len(bare) < stride:
                    bare.append(children[ci]); ci += 1
                self._fill_init(data, offset + pos * stride, dims[1:], ('initlist', bare))
                pos += 1

    def format_const_array(self, data, dims):
        if len(dims) == 1:
            elems = ", ".join(f"i32 {data[i]}" for i in range(dims[0]))
            return f"[{dims[0]} x i32] [{elems}]"
        stride = 1
        for d in dims[1:]: stride *= d
        inner_type = self.array_type(dims[1:])
        parts = []
        for i in range(dims[0]):
            sub = data[i*stride:(i+1)*stride]
            parts.append(self.format_const_array(sub, dims[1:]))
        elems = ", ".join(parts)
        return f"[{dims[0]} x {inner_type}] [{elems}]"

    def _flat_to_gep_indices(self, flat_idx, dims):
        indices = []
        for i in range(len(dims)):
            stride = 1
            for d in dims[i+1:]: stride *= d
            indices.append(flat_idx // stride)
            flat_idx %= stride
        return indices

    def generate(self, ast):
        _, decls, funcs = ast
        for f in funcs:
            self.functions[f[2]] = (f[1], f[3])
        # Runtime declarations
        self.emit("declare i32 @getint()")
        self.emit("declare i32 @getch()")
        self.emit("declare i32 @getarray(ptr)")
        self.emit("declare void @putint(i32)")
        self.emit("declare void @putch(i32)")
        self.emit("declare void @putarray(i32, ptr)")
        self.emit("")
        for d in decls: self.gen_global_decl(d)
        self.emit("")
        for f in funcs: self.gen_func(f)
        return "\n".join(self.lines) + "\n"

    def gen_global_decl(self, node):
        _, is_const, defs = node
        for vdef in defs:
            _, name, dim_exprs, init = vdef
            dims = [const_eval(d, self.const_vals) for d in dim_exprs]
            ir_name = f"@{name}"
            if not dims:
                val = 0
                if init and init[0] == 'initexpr':
                    v = const_eval(init[1], self.const_vals)
                    if v is not None: val = v
                self.globals[name] = (ir_name, [], is_const)
                self.const_vals[name] = val
                kw = 'constant' if is_const else 'global'
                self.emit(f"{ir_name} = {kw} i32 {val}")
            else:
                data = self.flatten_init(init, dims)
                self.globals[name] = (ir_name, dims, is_const)
                arr_type = self.array_type(dims)
                kw = 'constant' if is_const else 'global'
                if all(v == 0 for v in data):
                    self.emit(f"{ir_name} = {kw} {arr_type} zeroinitializer")
                else:
                    init_str = self.format_const_array(data, dims)
                    self.emit(f"{ir_name} = {kw} {init_str}")

    def gen_func(self, node):
        _, ret_type, name, params, body = node
        self.tmp_counter = 0; self.label_counter = 0; self.locals = {}
        param_strs = []
        for p in params:
            _, pname, is_array, _ = p
            if is_array: param_strs.append(f"ptr %p_{pname}")
            else: param_strs.append(f"i32 %p_{pname}")
        ret_ir = "i32" if ret_type == "int" else "void"
        self.emit(f"define {ret_ir} @{name}({', '.join(param_strs)}) {{")
        self.emit_label("entry")
        for p in params:
            _, pname, is_array, extra_dims = p
            if is_array:
                alloca = self.tmp()
                self.emit(f"  {alloca} = alloca ptr")
                self.emit(f"  store ptr %p_{pname}, ptr {alloca}")
                edims = [const_eval(d, self.const_vals) for d in extra_dims]
                self.locals[pname] = (alloca, edims, True)
            else:
                alloca = self.tmp()
                self.emit(f"  {alloca} = alloca i32")
                self.emit(f"  store i32 %p_{pname}, ptr {alloca}")
                self.locals[pname] = (alloca, [], False)
        self.gen_block(body)
        if ret_type == "void": self.emit("  ret void")
        else: self.emit("  ret i32 0")
        self.emit("}"); self.emit("")

    def gen_block(self, node):
        self.push_scope()
        for item in node[1]:
            if item[0] == 'decl': self.gen_local_decl(item)
            else: self.gen_stmt(item)
        self.pop_scope()

    def gen_local_decl(self, node):
        _, is_const, defs = node
        for vdef in defs:
            _, name, dim_exprs, init = vdef
            dims = [const_eval(d, self.const_vals) for d in dim_exprs]
            if not dims:
                alloca = self.tmp()
                self.emit(f"  {alloca} = alloca i32")
                if init and init[0] == 'initexpr':
                    cv = const_eval(init[1], self.const_vals)
                    if is_const and cv is not None:
                        self.emit(f"  store i32 {cv}, ptr {alloca}")
                        self.locals[name] = (alloca, [], False)
                        self.const_vals[name] = cv
                        continue
                    if cv is not None:
                        self.emit(f"  store i32 {cv}, ptr {alloca}")
                    else:
                        val = self.gen_expr(init[1])
                        self.emit(f"  store i32 {val}, ptr {alloca}")
                else:
                    self.emit(f"  store i32 0, ptr {alloca}")
                self.locals[name] = (alloca, [], False)
            else:
                arr_type = self.array_type(dims)
                alloca = self.tmp()
                self.emit(f"  {alloca} = alloca {arr_type}")
                total = 1
                for d in dims: total *= d
                if init:
                    flat = self.flatten_init(init, dims)
                else:
                    flat = [0] * total
                # Store all elements (alloca doesn't zero-init)
                for idx in range(total):
                    gep = self.tmp()
                    gep_indices = self._flat_to_gep_indices(idx, dims)
                    idx_str = "".join(f", i32 {ii}" for ii in gep_indices)
                    self.emit(f"  {gep} = getelementptr {arr_type}, ptr {alloca}, i32 0{idx_str}")
                    self.emit(f"  store i32 {flat[idx]}, ptr {gep}")
                self.locals[name] = (alloca, dims, False)

    def gen_stmt(self, node):
        tag = node[0]
        if tag == 'block': self.gen_block(node)
        elif tag == 'assign':
            val = self.gen_expr(node[2])
            ptr = self.gen_lval_ptr(node[1])
            self.emit(f"  store i32 {val}, ptr {ptr}")
        elif tag == 'exprstmt': self.gen_expr(node[1])
        elif tag == 'if':
            _, cond, then_s, else_s = node
            cond_val = self.gen_expr(cond)
            cmp = self.tmp()
            self.emit(f"  {cmp} = icmp ne i32 {cond_val}, 0")
            if else_s:
                then_l, else_l, end_l = self.label("then"), self.label("else"), self.label("endif")
                self.emit(f"  br i1 {cmp}, label %{then_l}, label %{else_l}")
                self.emit_label(then_l); self.gen_stmt(then_s)
                self.emit(f"  br label %{end_l}")
                self.emit_label(else_l); self.gen_stmt(else_s)
                self.emit(f"  br label %{end_l}")
                self.emit_label(end_l)
            else:
                then_l, end_l = self.label("then"), self.label("endif")
                self.emit(f"  br i1 {cmp}, label %{then_l}, label %{end_l}")
                self.emit_label(then_l); self.gen_stmt(then_s)
                self.emit(f"  br label %{end_l}")
                self.emit_label(end_l)
        elif tag == 'while':
            _, cond, body = node
            cond_l, body_l, end_l = self.label("whcond"), self.label("whbody"), self.label("whend")
            old_b, old_c = self.break_label, self.continue_label
            self.break_label, self.continue_label = end_l, cond_l
            self.emit(f"  br label %{cond_l}")
            self.emit_label(cond_l)
            cond_val = self.gen_expr(cond)
            cmp = self.tmp()
            self.emit(f"  {cmp} = icmp ne i32 {cond_val}, 0")
            self.emit(f"  br i1 {cmp}, label %{body_l}, label %{end_l}")
            self.emit_label(body_l); self.gen_stmt(body)
            self.emit(f"  br label %{cond_l}")
            self.emit_label(end_l)
            self.break_label, self.continue_label = old_b, old_c
        elif tag == 'break':
            self.emit(f"  br label %{self.break_label}")
            self.emit_label(self.label("dead"))
        elif tag == 'continue':
            self.emit(f"  br label %{self.continue_label}")
            self.emit_label(self.label("dead"))
        elif tag == 'return':
            if node[1] is not None:
                val = self.gen_expr(node[1])
                self.emit(f"  ret i32 {val}")
            else:
                self.emit("  ret void")
            self.emit_label(self.label("dead"))

    def gen_lval_ptr(self, lval):
        _, name, indices = lval
        info = self.lookup(name)
        if info is None: raise RuntimeError(f"Undefined: {name}")
        where, data = info

        if where == 'global':
            ir_name, dims, _ = data
            if not dims: return ir_name
            arr_type = self.array_type(dims)
            idx_vals = [self.gen_expr(i) for i in indices]
            gep = self.tmp()
            idx_str = "".join(f", i32 {v}" for v in idx_vals)
            self.emit(f"  {gep} = getelementptr {arr_type}, ptr {ir_name}, i32 0{idx_str}")
            return gep
        else:
            ir_name, dims, is_ptr = data
            if is_ptr:
                base = self.tmp()
                self.emit(f"  {base} = load ptr, ptr {ir_name}")
                idx_vals = [self.gen_expr(i) for i in indices]
                if not dims:
                    gep = self.tmp()
                    self.emit(f"  {gep} = getelementptr i32, ptr {base}, i32 {idx_vals[0]}")
                    return gep
                else:
                    inner_type = self.array_type(dims)
                    gep = self.tmp()
                    self.emit(f"  {gep} = getelementptr {inner_type}, ptr {base}, i32 {idx_vals[0]}")
                    if len(idx_vals) > 1:
                        gep2 = self.tmp()
                        rest = "".join(f", i32 {v}" for v in idx_vals[1:])
                        self.emit(f"  {gep2} = getelementptr {inner_type}, ptr {gep}, i32 0{rest}")
                        return gep2
                    return gep
            elif dims:
                arr_type = self.array_type(dims)
                idx_vals = [self.gen_expr(i) for i in indices]
                gep = self.tmp()
                idx_str = "".join(f", i32 {v}" for v in idx_vals)
                self.emit(f"  {gep} = getelementptr {arr_type}, ptr {ir_name}, i32 0{idx_str}")
                return gep
            else:
                return ir_name

    def gen_expr(self, node):
        tag = node[0]
        if tag == 'num': return str(node[1])

        if tag == 'lval':
            _, name, indices = node
            info = self.lookup(name)
            if info is None: raise RuntimeError(f"Undefined: {name}")
            where, data = info

            if where == 'global':
                ir_name, dims, _ = data
                if not dims and not indices:
                    t = self.tmp()
                    self.emit(f"  {t} = load i32, ptr {ir_name}")
                    return t
                if dims and not indices:
                    gep = self.tmp()
                    at = self.array_type(dims)
                    self.emit(f"  {gep} = getelementptr {at}, ptr {ir_name}, i32 0, i32 0")
                    return gep
                if dims and indices:
                    at = self.array_type(dims)
                    idx_vals = [self.gen_expr(i) for i in indices]
                    if len(indices) < len(dims):
                        gep = self.tmp()
                        idx_str = "".join(f", i32 {v}" for v in idx_vals)
                        self.emit(f"  {gep} = getelementptr {at}, ptr {ir_name}, i32 0{idx_str}, i32 0")
                        return gep
                    gep = self.tmp()
                    idx_str = "".join(f", i32 {v}" for v in idx_vals)
                    self.emit(f"  {gep} = getelementptr {at}, ptr {ir_name}, i32 0{idx_str}")
                    t = self.tmp()
                    self.emit(f"  {t} = load i32, ptr {gep}")
                    return t
            else:
                ir_name, dims, is_ptr = data
                if is_ptr:
                    base = self.tmp()
                    self.emit(f"  {base} = load ptr, ptr {ir_name}")
                    if not indices: return base
                    idx_vals = [self.gen_expr(i) for i in indices]
                    if not dims:
                        gep = self.tmp()
                        self.emit(f"  {gep} = getelementptr i32, ptr {base}, i32 {idx_vals[0]}")
                        t = self.tmp()
                        self.emit(f"  {t} = load i32, ptr {gep}")
                        return t
                    else:
                        inner_type = self.array_type(dims)
                        gep = self.tmp()
                        self.emit(f"  {gep} = getelementptr {inner_type}, ptr {base}, i32 {idx_vals[0]}")
                        if len(idx_vals) > 1:
                            gep2 = self.tmp()
                            rest = "".join(f", i32 {v}" for v in idx_vals[1:])
                            self.emit(f"  {gep2} = getelementptr {inner_type}, ptr {gep}, i32 0{rest}")
                            if len(idx_vals) - 1 == len(dims):
                                t = self.tmp()
                                self.emit(f"  {t} = load i32, ptr {gep2}")
                                return t
                            return gep2
                        return gep
                elif dims:
                    at = self.array_type(dims)
                    if not indices:
                        gep = self.tmp()
                        self.emit(f"  {gep} = getelementptr {at}, ptr {ir_name}, i32 0, i32 0")
                        return gep
                    idx_vals = [self.gen_expr(i) for i in indices]
                    if len(indices) < len(dims):
                        gep = self.tmp()
                        idx_str = "".join(f", i32 {v}" for v in idx_vals)
                        self.emit(f"  {gep} = getelementptr {at}, ptr {ir_name}, i32 0{idx_str}, i32 0")
                        return gep
                    gep = self.tmp()
                    idx_str = "".join(f", i32 {v}" for v in idx_vals)
                    self.emit(f"  {gep} = getelementptr {at}, ptr {ir_name}, i32 0{idx_str}")
                    t = self.tmp()
                    self.emit(f"  {t} = load i32, ptr {gep}")
                    return t
                else:
                    t = self.tmp()
                    self.emit(f"  {t} = load i32, ptr {ir_name}")
                    return t

        if tag == 'call':
            _, fname, arg_exprs = node
            if fname in ('getint', 'getch'):
                t = self.tmp()
                self.emit(f"  {t} = call i32 @{fname}()")
                return t
            if fname in ('putint', 'putch'):
                val = self.gen_expr(arg_exprs[0])
                self.emit(f"  call void @{fname}(i32 {val})")
                return "0"
            if fname == 'putarray':
                nv = self.gen_expr(arg_exprs[0])
                av = self.gen_expr(arg_exprs[1])
                self.emit(f"  call void @putarray(i32 {nv}, ptr {av})")
                return "0"
            if fname == 'getarray':
                av = self.gen_expr(arg_exprs[0])
                t = self.tmp()
                self.emit(f"  {t} = call i32 @getarray(ptr {av})")
                return t
            if fname in ('starttime','stoptime','_sysy_starttime','_sysy_stoptime'):
                return "0"
            func_info = self.functions.get(fname)
            if func_info is None: raise RuntimeError(f"Undefined function: {fname}")
            ret_type, params = func_info
            arg_vals = []; arg_types = []
            for i, ae in enumerate(arg_exprs):
                if i < len(params) and params[i][2]:  # is_array
                    v = self.gen_expr(ae); arg_vals.append(v); arg_types.append("ptr")
                else:
                    v = self.gen_expr(ae); arg_vals.append(v); arg_types.append("i32")
            args_str = ", ".join(f"{t} {v}" for t, v in zip(arg_types, arg_vals))
            if ret_type == "void":
                self.emit(f"  call void @{fname}({args_str})"); return "0"
            else:
                t = self.tmp()
                self.emit(f"  {t} = call i32 @{fname}({args_str})"); return t

        # Short-circuit || using alloca (no phi needed)
        if tag == '||':
            res = self.tmp()
            self.emit(f"  {res} = alloca i32")
            left_val = self.gen_expr(node[1])
            left_nz = self.tmp()
            self.emit(f"  {left_nz} = icmp ne i32 {left_val}, 0")
            true_l, rhs_l, merge_l = self.label("or_t"), self.label("or_r"), self.label("or_m")
            self.emit(f"  br i1 {left_nz}, label %{true_l}, label %{rhs_l}")
            self.emit_label(true_l)
            self.emit(f"  store i32 1, ptr {res}")
            self.emit(f"  br label %{merge_l}")
            self.emit_label(rhs_l)
            right_val = self.gen_expr(node[2])
            right_nz = self.tmp()
            self.emit(f"  {right_nz} = icmp ne i32 {right_val}, 0")
            right_ext = self.tmp()
            self.emit(f"  {right_ext} = zext i1 {right_nz} to i32")
            self.emit(f"  store i32 {right_ext}, ptr {res}")
            self.emit(f"  br label %{merge_l}")
            self.emit_label(merge_l)
            result = self.tmp()
            self.emit(f"  {result} = load i32, ptr {res}")
            return result

        # Short-circuit && using alloca
        if tag == '&&':
            res = self.tmp()
            self.emit(f"  {res} = alloca i32")
            left_val = self.gen_expr(node[1])
            left_nz = self.tmp()
            self.emit(f"  {left_nz} = icmp ne i32 {left_val}, 0")
            false_l, rhs_l, merge_l = self.label("and_f"), self.label("and_r"), self.label("and_m")
            self.emit(f"  br i1 {left_nz}, label %{rhs_l}, label %{false_l}")
            self.emit_label(false_l)
            self.emit(f"  store i32 0, ptr {res}")
            self.emit(f"  br label %{merge_l}")
            self.emit_label(rhs_l)
            right_val = self.gen_expr(node[2])
            right_nz = self.tmp()
            self.emit(f"  {right_nz} = icmp ne i32 {right_val}, 0")
            right_ext = self.tmp()
            self.emit(f"  {right_ext} = zext i1 {right_nz} to i32")
            self.emit(f"  store i32 {right_ext}, ptr {res}")
            self.emit(f"  br label %{merge_l}")
            self.emit_label(merge_l)
            result = self.tmp()
            self.emit(f"  {result} = load i32, ptr {res}")
            return result

        # Binary arithmetic
        if tag in ('+','-','*'):
            l = self.gen_expr(node[1]); r = self.gen_expr(node[2])
            t = self.tmp()
            op = {'+':"add",'-':"sub",'*':"mul"}[tag]
            self.emit(f"  {t} = {op} i32 {l}, {r}"); return t
        if tag == '/':
            l = self.gen_expr(node[1]); r = self.gen_expr(node[2])
            t = self.tmp()
            self.emit(f"  {t} = sdiv i32 {l}, {r}"); return t
        if tag == '%':
            l = self.gen_expr(node[1]); r = self.gen_expr(node[2])
            t = self.tmp()
            self.emit(f"  {t} = srem i32 {l}, {r}"); return t

        # Comparisons
        if tag in ('==','!=','<','>','<=','>='):
            l = self.gen_expr(node[1]); r = self.gen_expr(node[2])
            cop = {'==':'eq','!=':'ne','<':'slt','>':'sgt','<=':'sle','>=':'sge'}[tag]
            cmp = self.tmp()
            self.emit(f"  {cmp} = icmp {cop} i32 {l}, {r}")
            t = self.tmp()
            self.emit(f"  {t} = zext i1 {cmp} to i32"); return t

        # Unary
        if tag == 'unary_+': return self.gen_expr(node[1])
        if tag == 'unary_-':
            val = self.gen_expr(node[1]); t = self.tmp()
            self.emit(f"  {t} = sub i32 0, {val}"); return t
        if tag == 'unary_!':
            val = self.gen_expr(node[1]); cmp = self.tmp()
            self.emit(f"  {cmp} = icmp eq i32 {val}, 0")
            t = self.tmp()
            self.emit(f"  {t} = zext i1 {cmp} to i32"); return t

        raise RuntimeError(f"Unknown expression: {tag}")


def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_to_llvm <file.sy>", file=sys.stderr); sys.exit(1)
    with open(sys.argv[1]) as f: source = f.read()
    tokens = tokenize(source)
    parser = Parser(tokens)
    ast = parser.parse()
    gen = IRGen()
    ir = gen.generate(ast)
    sys.stdout.write(ir)

if __name__ == '__main__':
    main()
