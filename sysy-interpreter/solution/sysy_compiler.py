#!/usr/bin/env python3
"""SysY to LLVM IR compiler."""
import sys

# ======================================================================
# LEXER
# ======================================================================

class Token:
    __slots__ = ('ty', 'val', 'ln')
    def __init__(self, ty, val, ln=0):
        self.ty = ty
        self.val = val
        self.ln = ln

KEYWORDS = frozenset(['const','int','void','if','else','while','break','continue','return'])

def tokenize(src):
    toks = []
    i, n, ln = 0, len(src), 1
    while i < n:
        c = src[i]
        if c in ' \t\r':
            i += 1; continue
        if c == '\n':
            ln += 1; i += 1; continue
        if c == '/' and i+1 < n and src[i+1] == '/':
            i += 2
            while i < n and src[i] != '\n': i += 1
            continue
        if c == '/' and i+1 < n and src[i+1] == '*':
            i += 2
            while i+1 < n and not (src[i]=='*' and src[i+1]=='/'):
                if src[i]=='\n': ln += 1
                i += 1
            i += 2; continue
        if c == '#':
            while i < n and src[i] != '\n': i += 1
            continue
        if c.isdigit():
            j = i
            if c=='0' and i+1<n and src[i+1] in 'xX':
                i += 2
                while i<n and src[i] in '0123456789abcdefABCDEF': i += 1
                toks.append(Token('NUM', int(src[j:i],16), ln))
            elif c=='0' and i+1<n and src[i+1] in '01234567':
                while i<n and src[i] in '01234567': i += 1
                toks.append(Token('NUM', int(src[j:i],8), ln))
            else:
                while i<n and src[i].isdigit(): i += 1
                toks.append(Token('NUM', int(src[j:i]), ln))
            continue
        if c.isalpha() or c=='_':
            j = i
            while i<n and (src[i].isalnum() or src[i]=='_'): i += 1
            w = src[j:i]
            toks.append(Token(w if w in KEYWORDS else 'ID', w, ln))
            continue
        if i+1<n and src[i:i+2] in ('<=','>=','==','!=','&&','||'):
            toks.append(Token(src[i:i+2], src[i:i+2], ln))
            i += 2; continue
        toks.append(Token(c, c, ln))
        i += 1
    toks.append(Token('EOF','',ln))
    return toks

# ======================================================================
# PARSER
# ======================================================================

class Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0
    def peek(self):
        return self.toks[self.pos]
    def advance(self):
        t = self.toks[self.pos]; self.pos += 1; return t
    def expect(self, ty):
        t = self.advance()
        if t.ty != ty:
            raise SyntaxError(f"Expected {ty}, got {t.ty}({t.val}) line {t.ln}")
        return t
    def at(self, *tys):
        return self.peek().ty in tys
    def match(self, ty):
        if self.at(ty): return self.advance()
        return None

    def parse(self):
        items = []
        while not self.at('EOF'):
            items.append(self._decl_or_func())
        return items

    def _decl_or_func(self):
        if self.at('const'): return self._const_decl()
        if self.at('void'): return self._func_def()
        save = self.pos
        self.expect('int')
        self.expect('ID')
        is_func = self.at('(')
        self.pos = save
        return self._func_def() if is_func else self._var_decl()

    def _const_decl(self):
        self.expect('const'); self.expect('int')
        defs = [self._const_def()]
        while self.match(','): defs.append(self._const_def())
        self.expect(';')
        return ('ConstDecl', defs)

    def _const_def(self):
        name = self.expect('ID').val
        dims = []
        while self.match('['):
            dims.append(self._exp())
            self.expect(']')
        self.expect('=')
        init = self._const_init()
        return (name, dims, init)

    def _const_init(self):
        if self.at('{'):
            self.advance()
            items = []
            if not self.at('}'):
                items.append(self._const_init())
                while self.match(','): items.append(self._const_init())
            self.expect('}')
            return ('InitList', items)
        return self._exp()

    def _var_decl(self):
        self.expect('int')
        defs = [self._var_def()]
        while self.match(','): defs.append(self._var_def())
        self.expect(';')
        return ('VarDecl', defs)

    def _var_def(self):
        name = self.expect('ID').val
        dims = []
        while self.match('['):
            dims.append(self._exp())
            self.expect(']')
        init = None
        if self.match('='): init = self._init_val()
        return (name, dims, init)

    def _init_val(self):
        if self.at('{'):
            self.advance()
            items = []
            if not self.at('}'):
                items.append(self._init_val())
                while self.match(','): items.append(self._init_val())
            self.expect('}')
            return ('InitList', items)
        return self._exp()

    def _func_def(self):
        ret = self.advance().val
        name = self.expect('ID').val
        self.expect('(')
        params = []
        if not self.at(')'):
            params.append(self._param())
            while self.match(','): params.append(self._param())
        self.expect(')')
        body = self._block()
        return ('FuncDef', ret, name, params, body)

    def _param(self):
        self.expect('int')
        name = self.expect('ID').val
        is_arr = False; dims = []
        if self.match('['):
            self.expect(']'); is_arr = True
            while self.match('['):
                dims.append(self._exp())
                self.expect(']')
        return (name, is_arr, dims)

    def _block(self):
        self.expect('{')
        items = []
        while not self.at('}'):
            items.append(self._block_item())
        self.expect('}')
        return ('Block', items)

    def _block_item(self):
        if self.at('const'): return self._const_decl()
        if self.at('int'): return self._var_decl()
        return self._stmt()

    def _stmt(self):
        if self.at('{'): return self._block()
        if self.at('if'): return self._if()
        if self.at('while'): return self._while()
        if self.at('break'):
            self.advance(); self.expect(';'); return ('Break',)
        if self.at('continue'):
            self.advance(); self.expect(';'); return ('Continue',)
        if self.at('return'):
            self.advance()
            e = None
            if not self.at(';'): e = self._exp()
            self.expect(';')
            return ('Return', e)
        if self.at(';'):
            self.advance(); return ('ExpStmt', None)
        e = self._exp()
        if self.match('='):
            rhs = self._exp(); self.expect(';')
            return ('Assign', e, rhs)
        self.expect(';')
        return ('ExpStmt', e)

    def _if(self):
        self.expect('if'); self.expect('(')
        cond = self._exp(); self.expect(')')
        then = self._stmt()
        els = self._stmt() if self.match('else') else None
        return ('If', cond, then, els)

    def _while(self):
        self.expect('while'); self.expect('(')
        cond = self._exp(); self.expect(')')
        body = self._stmt()
        return ('While', cond, body)

    # ---- Expressions (precedence climbing) ----
    def _exp(self): return self._lor()
    def _lor(self):
        l = self._land()
        while self.match('||'): l = ('BinOp','||',l,self._land())
        return l
    def _land(self):
        l = self._eq()
        while self.match('&&'): l = ('BinOp','&&',l,self._eq())
        return l
    def _eq(self):
        l = self._rel()
        while self.at('==','!='):
            op = self.advance().val; l = ('BinOp',op,l,self._rel())
        return l
    def _rel(self):
        l = self._add()
        while self.at('<','>','<=','>='):
            op = self.advance().val; l = ('BinOp',op,l,self._add())
        return l
    def _add(self):
        l = self._mul()
        while self.at('+','-'):
            op = self.advance().val; l = ('BinOp',op,l,self._mul())
        return l
    def _mul(self):
        l = self._unary()
        while self.at('*','/','%'):
            op = self.advance().val; l = ('BinOp',op,l,self._unary())
        return l
    def _unary(self):
        if self.at('+','-','!'):
            op = self.advance().val; return ('UnaryOp',op,self._unary())
        if self.at('ID') and self.pos+1<len(self.toks) and self.toks[self.pos+1].ty=='(':
            name = self.advance().val; self.expect('(')
            args = []
            if not self.at(')'):
                args.append(self._exp())
                while self.match(','): args.append(self._exp())
            self.expect(')')
            return ('Call', name, args)
        return self._primary()
    def _primary(self):
        if self.match('('):
            e = self._exp(); self.expect(')'); return e
        if self.at('NUM'):
            return ('Num', self.advance().val)
        return self._lval()
    def _lval(self):
        name = self.expect('ID').val
        indices = []
        while self.match('['):
            indices.append(self._exp())
            self.expect(']')
        return ('LVal', name, indices)


# ======================================================================
# VARIABLE INFO
# ======================================================================

class VarInfo:
    __slots__ = ('ptr','dims','is_global','is_const','is_param_ptr','const_val')
    def __init__(self, ptr, dims, is_global=False, is_const=False,
                 is_param_ptr=False, const_val=None):
        self.ptr = ptr
        self.dims = dims            # list of int dimensions, [] for scalar
        self.is_global = is_global
        self.is_const = is_const
        self.is_param_ptr = is_param_ptr  # array param: ptr stores a ptr
        self.const_val = const_val  # int (scalar) or flat list (array)


# ======================================================================
# IR GENERATOR
# ======================================================================

def c_div(a, b):
    s = -1 if (a < 0) != (b < 0) else 1
    return s * (abs(a) // abs(b))

def c_mod(a, b):
    return a - c_div(a, b) * b

class IRGen:
    def __init__(self):
        self.output = []        # final output lines
        self.lines = []         # current function lines
        self.tmp_cnt = 0
        self.lbl_cnt = 0
        self.terminated = False
        self.loop_stack = []    # (cond_label, end_label)
        self.scopes = []        # list of dicts: name -> VarInfo
        self.global_vars = {}   # name -> VarInfo
        self.func_sigs = {}     # name -> {'ret': str, 'params': [{'arr':bool,'dims':[int]}]}

    # -- helpers --
    def tmp(self):
        self.tmp_cnt += 1; return f"%t{self.tmp_cnt}"
    def lbl(self, hint="L"):
        self.lbl_cnt += 1; return f"{hint}{self.lbl_cnt}"
    def emit(self, line):
        if not self.terminated:
            self.lines.append(line)
    def emit_label(self, label):
        if not self.terminated:
            self.lines.append(f"  br label %{label}")
        self.lines.append(f"{label}:")
        self.terminated = False
    def emit_br(self, label):
        if not self.terminated:
            self.lines.append(f"  br label %{label}")
            self.terminated = True
    def emit_cbr(self, cond, t_lbl, f_lbl):
        if not self.terminated:
            self.lines.append(f"  br i1 {cond}, label %{t_lbl}, label %{f_lbl}")
            self.terminated = True
    def push_scope(self):
        self.scopes.append({})
    def pop_scope(self):
        self.scopes.pop()
    def add_var(self, name, info):
        self.scopes[-1][name] = info
    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s: return s[name]
        if name in self.global_vars: return self.global_vars[name]
        raise NameError(f"Undefined: {name}")

    @staticmethod
    def dims_ty(dims):
        """[3,4] -> '[3 x [4 x i32]]'"""
        t = 'i32'
        for d in reversed(dims):
            t = f'[{d} x {t}]'
        return t

    def eval_const(self, node):
        """Evaluate a compile-time constant expression."""
        kind = node[0]
        if kind == 'Num': return node[1]
        if kind == 'UnaryOp':
            v = self.eval_const(node[2])
            if node[1]=='-': return -v
            if node[1]=='+': return v
            if node[1]=='!': return 1 if v==0 else 0
        if kind == 'BinOp':
            l,r = self.eval_const(node[2]), self.eval_const(node[3])
            op = node[1]
            if op=='+': return l+r
            if op=='-': return l-r
            if op=='*': return l*r
            if op=='/': return c_div(l,r)
            if op=='%': return c_mod(l,r)
            if op=='<': return 1 if l<r else 0
            if op=='>': return 1 if l>r else 0
            if op=='<=': return 1 if l<=r else 0
            if op=='>=': return 1 if l>=r else 0
            if op=='==': return 1 if l==r else 0
            if op=='!=': return 1 if l!=r else 0
            if op=='&&': return 1 if (l!=0 and r!=0) else 0
            if op=='||': return 1 if (l!=0 or r!=0) else 0
        if kind == 'LVal':
            var = self.lookup(node[1])
            if not var.is_const:
                raise ValueError(f"Not const: {node[1]}")
            if len(var.dims)==0:
                return var.const_val
            idx_vals = [self.eval_const(idx) for idx in node[2]]
            offset = 0
            for i, iv in enumerate(idx_vals):
                stride = 1
                for d in var.dims[i+1:]: stride *= d
                offset += iv * stride
            return var.const_val[offset]
        raise ValueError(f"Cannot const-eval: {node}")

    def flatten_init_const(self, init_node, dims):
        """Flatten initializer (brace elision) to flat list of ints."""
        total = 1
        for d in dims: total *= d
        result = [0]*total
        pos = [0]
        def fill(items, depth):
            sub_sz = 1
            for d in dims[depth+1:]: sub_sz *= d
            for item in items:
                if item[0]=='InitList':
                    if depth+1 < len(dims):
                        start = pos[0]
                        fill(item[1], depth+1)
                        pos[0] = start + sub_sz
                    else:
                        for si in item[1]:
                            if pos[0]<total:
                                result[pos[0]] = self.eval_const(si)
                                pos[0] += 1
                else:
                    if pos[0]<total:
                        result[pos[0]] = self.eval_const(item)
                        pos[0] += 1
        if init_node[0]=='InitList':
            fill(init_node[1], 0)
        else:
            result[0] = self.eval_const(init_node)
        return result

    def format_const_arr(self, vals, dims):
        """Format flat values as LLVM constant array literal."""
        if len(dims)==0:
            return f"i32 {vals[0]}"
        if len(dims)==1:
            elems = ', '.join(f'i32 {vals[i]}' for i in range(dims[0]))
            return f"[{dims[0]} x i32] [{elems}]"
        inner_sz = 1
        for d in dims[1:]: inner_sz *= d
        parts = []
        for i in range(dims[0]):
            sub = vals[i*inner_sz:(i+1)*inner_sz]
            parts.append(self.format_const_arr(sub, dims[1:]))
        ty = self.dims_ty(dims)
        return f"{ty} [{', '.join(parts)}]"

    def linear_to_idx(self, flat, dims):
        indices = []
        for d in reversed(dims):
            indices.append(flat % d)
            flat //= d
        indices.reverse()
        return indices

    # -- REGISTRATION of builtin runtime --
    def _init_builtins(self):
        self.func_sigs = {
            'getint':    {'ret':'int',  'params':[]},
            'getch':     {'ret':'int',  'params':[]},
            'getarray':  {'ret':'int',  'params':[{'arr':True,'dims':[]}]},
            'putint':    {'ret':'void', 'params':[{'arr':False,'dims':[]}]},
            'putch':     {'ret':'void', 'params':[{'arr':False,'dims':[]}]},
            'putarray':  {'ret':'void', 'params':[{'arr':False,'dims':[]},{'arr':True,'dims':[]}]},
            'starttime': {'ret':'void', 'params':[]},
            'stoptime':  {'ret':'void', 'params':[]},
        }

    # ============================================================
    # TOP-LEVEL GENERATION
    # ============================================================

    def generate(self, items):
        self._init_builtins()
        out = []
        out.append('declare i32 @getint()')
        out.append('declare i32 @getch()')
        out.append('declare i32 @getarray(ptr)')
        out.append('declare void @putint(i32)')
        out.append('declare void @putch(i32)')
        out.append('declare void @putarray(i32, ptr)')
        out.append('declare void @starttime()')
        out.append('declare void @stoptime()')
        out.append('')

        for item in items:
            kind = item[0]
            if kind == 'FuncDef':
                self._register_func(item)
                out.extend(self._gen_func(item))
                out.append('')
            elif kind in ('ConstDecl','VarDecl'):
                out.extend(self._gen_global(item))

        return '\n'.join(out)

    def _register_func(self, node):
        _, ret, name, params, _ = node
        plist = []
        for pname, is_arr, pdims in params:
            d = [self.eval_const(x) for x in pdims] if is_arr else []
            plist.append({'arr': is_arr, 'dims': d})
        self.func_sigs[name] = {'ret': ret, 'params': plist}

    # -- globals --
    def _gen_global(self, decl):
        lines = []
        is_const = decl[0] == 'ConstDecl'
        for defn in decl[1]:
            name, dim_exprs, init = defn
            dims = [self.eval_const(d) for d in dim_exprs]
            gname = f"@{name}"
            if len(dims) == 0:
                # scalar
                val = 0
                if init is not None:
                    val = self.eval_const(init)
                kw = 'constant' if is_const else 'global'
                lines.append(f"{gname} = {kw} i32 {val}")
                self.global_vars[name] = VarInfo(
                    gname, [], is_global=True, is_const=is_const, const_val=val)
            else:
                # array
                kw = 'constant' if is_const else 'global'
                ty = self.dims_ty(dims)
                if init is not None:
                    flat = self.flatten_init_const(init, dims)
                    if all(v==0 for v in flat):
                        lines.append(f"{gname} = {kw} {ty} zeroinitializer")
                    else:
                        lit = self.format_const_arr(flat, dims)
                        lines.append(f"{gname} = {kw} {lit}")
                else:
                    lines.append(f"{gname} = {kw} {ty} zeroinitializer")
                    flat = None
                cv = flat if is_const else None
                self.global_vars[name] = VarInfo(
                    gname, dims, is_global=True, is_const=is_const, const_val=cv)
        return lines

    # -- functions --
    def _gen_func(self, node):
        _, ret_ty, name, params, body = node
        self.lines = []
        self.tmp_cnt = 0
        self.lbl_cnt = 0
        self.terminated = False
        self.loop_stack = []
        self.scopes = [{}]  # function scope

        ir_ret = 'i32' if ret_ty == 'int' else 'void'
        pstrs = []
        for i, (pname, is_arr, pdims) in enumerate(params):
            pstrs.append(f"ptr %p{i}" if is_arr else f"i32 %p{i}")

        self.lines.append(f"define {ir_ret} @{name}({', '.join(pstrs)}) {{")
        self.lines.append("entry:")

        # alloca + store params
        for i, (pname, is_arr, pdims) in enumerate(params):
            if is_arr:
                ptr = self.tmp()
                self.emit(f"  {ptr} = alloca ptr")
                self.emit(f"  store ptr %p{i}, ptr {ptr}")
                dims = [self.eval_const(d) for d in pdims]
                self.add_var(pname, VarInfo(ptr, dims, is_param_ptr=True))
            else:
                ptr = self.tmp()
                self.emit(f"  {ptr} = alloca i32")
                self.emit(f"  store i32 %p{i}, ptr {ptr}")
                self.add_var(pname, VarInfo(ptr, []))

        # body
        self._gen_block_items(body[1])

        # ensure terminator
        if not self.terminated:
            if ir_ret == 'i32':
                self.emit("  ret i32 0")
            else:
                self.emit("  ret void")

        self.lines.append("}")
        return self.lines

    def _gen_block_items(self, items):
        for item in items:
            if self.terminated: break
            kind = item[0]
            if kind in ('ConstDecl','VarDecl'):
                self._gen_local_decl(item)
            else:
                self._gen_stmt(item)

    # -- local declarations --
    def _gen_local_decl(self, decl):
        is_const = decl[0] == 'ConstDecl'
        for defn in decl[1]:
            name, dim_exprs, init = defn
            dims = [self.eval_const(d) for d in dim_exprs]
            if len(dims) == 0:
                # scalar
                ptr = self.tmp()
                self.emit(f"  {ptr} = alloca i32")
                cv = None
                if init is not None:
                    if is_const:
                        cv = self.eval_const(init)
                        self.emit(f"  store i32 {cv}, ptr {ptr}")
                    else:
                        val = self._gen_expr(init)
                        self.emit(f"  store i32 {val}, ptr {ptr}")
                else:
                    self.emit(f"  store i32 0, ptr {ptr}")
                self.add_var(name, VarInfo(ptr, [], is_const=is_const, const_val=cv))
            else:
                # array
                ty = self.dims_ty(dims)
                ptr = self.tmp()
                self.emit(f"  {ptr} = alloca {ty}")
                total = 1
                for d in dims: total *= d
                # zero-init
                for idx in range(total):
                    mi = self.linear_to_idx(idx, dims)
                    gep_args = 'i32 0, ' + ', '.join(f'i32 {x}' for x in mi)
                    ep = self.tmp()
                    self.emit(f"  {ep} = getelementptr {ty}, ptr {ptr}, {gep_args}")
                    self.emit(f"  store i32 0, ptr {ep}")
                cv = None
                if init is not None:
                    if is_const:
                        flat = self.flatten_init_const(init, dims)
                        cv = flat
                        for idx in range(total):
                            if flat[idx] != 0:
                                mi = self.linear_to_idx(idx, dims)
                                gep_args = 'i32 0, ' + ', '.join(f'i32 {x}' for x in mi)
                                ep = self.tmp()
                                self.emit(f"  {ep} = getelementptr {ty}, ptr {ptr}, {gep_args}")
                                self.emit(f"  store i32 {flat[idx]}, ptr {ep}")
                    else:
                        self._gen_runtime_init(ptr, dims, ty, init)
                self.add_var(name, VarInfo(ptr, dims, is_const=is_const, const_val=cv))

    def _gen_runtime_init(self, ptr, dims, ty, init_node):
        """Emit stores for runtime array initialization with brace elision."""
        total = 1
        for d in dims: total *= d
        pos = [0]
        def fill(items, depth):
            sub_sz = 1
            for d in dims[depth+1:]: sub_sz *= d
            for item in items:
                if item[0]=='InitList':
                    if depth+1 < len(dims):
                        start = pos[0]
                        fill(item[1], depth+1)
                        pos[0] = start + sub_sz
                    else:
                        for si in item[1]:
                            if pos[0]<total:
                                self._store_elem(ptr, dims, ty, pos[0], si)
                                pos[0] += 1
                else:
                    if pos[0]<total:
                        self._store_elem(ptr, dims, ty, pos[0], item)
                        pos[0] += 1
        if init_node[0]=='InitList':
            fill(init_node[1], 0)
        else:
            self._store_elem(ptr, dims, ty, 0, init_node)

    def _store_elem(self, ptr, dims, ty, flat_idx, expr):
        val = self._gen_expr(expr)
        mi = self.linear_to_idx(flat_idx, dims)
        gep_args = 'i32 0, ' + ', '.join(f'i32 {x}' for x in mi)
        ep = self.tmp()
        self.emit(f"  {ep} = getelementptr {ty}, ptr {ptr}, {gep_args}")
        self.emit(f"  store i32 {val}, ptr {ep}")

    # -- statements --
    def _gen_stmt(self, node):
        kind = node[0]
        if kind == 'Block':
            self.push_scope()
            self._gen_block_items(node[1])
            self.pop_scope()
        elif kind == 'If':
            self._gen_if(node)
        elif kind == 'While':
            self._gen_while(node)
        elif kind == 'Break':
            _, end_lbl = self.loop_stack[-1]
            self.emit_br(end_lbl)
        elif kind == 'Continue':
            cond_lbl, _ = self.loop_stack[-1]
            self.emit_br(cond_lbl)
        elif kind == 'Return':
            if node[1] is not None:
                val = self._gen_expr(node[1])
                self.emit(f"  ret i32 {val}")
            else:
                self.emit("  ret void")
            self.terminated = True
        elif kind == 'Assign':
            rhs = self._gen_expr(node[2])
            addr = self._gen_lval_addr(node[1])
            self.emit(f"  store i32 {rhs}, ptr {addr}")
        elif kind == 'ExpStmt':
            if node[1] is not None:
                self._gen_expr(node[1])

    def _gen_if(self, node):
        _, cond, then_s, else_s = node
        then_l = self.lbl("if.then")
        else_l = self.lbl("if.else") if else_s else None
        end_l = self.lbl("if.end")
        false_l = else_l if else_s else end_l

        cv = self._gen_expr(cond)
        c = self.tmp()
        self.emit(f"  {c} = icmp ne i32 {cv}, 0")
        self.emit_cbr(c, then_l, false_l)

        self.emit_label(then_l)
        self._gen_stmt(then_s)
        self.emit_br(end_l)

        if else_s:
            self.emit_label(else_l)
            self._gen_stmt(else_s)
            self.emit_br(end_l)

        self.emit_label(end_l)

    def _gen_while(self, node):
        _, cond, body = node
        cond_l = self.lbl("while.cond")
        body_l = self.lbl("while.body")
        end_l = self.lbl("while.end")

        self.loop_stack.append((cond_l, end_l))
        self.emit_br(cond_l)

        self.emit_label(cond_l)
        cv = self._gen_expr(cond)
        c = self.tmp()
        self.emit(f"  {c} = icmp ne i32 {cv}, 0")
        self.emit_cbr(c, body_l, end_l)

        self.emit_label(body_l)
        self._gen_stmt(body)
        self.emit_br(cond_l)

        self.emit_label(end_l)
        self.loop_stack.pop()

    # -- expressions --
    def _gen_expr(self, node):
        kind = node[0]
        if kind == 'Num':
            return str(node[1])
        if kind == 'LVal':
            var = self.lookup(node[1])
            if len(var.dims)==0 or len(node[2])==len(var.dims) or \
               (var.is_param_ptr and len(node[2])==len(var.dims)+1):
                # scalar access
                addr = self._gen_lval_addr(node)
                r = self.tmp()
                self.emit(f"  {r} = load i32, ptr {addr}")
                return r
            else:
                # sub-array reference used in expression? shouldn't happen
                addr = self._gen_lval_addr(node)
                r = self.tmp()
                self.emit(f"  {r} = load i32, ptr {addr}")
                return r
        if kind == 'BinOp':
            return self._gen_binop(node)
        if kind == 'UnaryOp':
            return self._gen_unary(node)
        if kind == 'Call':
            return self._gen_call(node)
        raise ValueError(f"Unknown expr: {node}")

    ICMP = {'<':'slt','>':'sgt','<=':'sle','>=':'sge','==':'eq','!=':'ne'}

    def _gen_binop(self, node):
        _, op, left, right = node
        if op == '&&': return self._gen_land(left, right)
        if op == '||': return self._gen_lor(left, right)

        l = self._gen_expr(left)
        r = self._gen_expr(right)
        t = self.tmp()
        if   op=='+': self.emit(f"  {t} = add i32 {l}, {r}")
        elif op=='-': self.emit(f"  {t} = sub i32 {l}, {r}")
        elif op=='*': self.emit(f"  {t} = mul i32 {l}, {r}")
        elif op=='/': self.emit(f"  {t} = sdiv i32 {l}, {r}")
        elif op=='%': self.emit(f"  {t} = srem i32 {l}, {r}")
        elif op in self.ICMP:
            c = self.tmp()
            self.emit(f"  {c} = icmp {self.ICMP[op]} i32 {l}, {r}")
            self.emit(f"  {t} = zext i1 {c} to i32")
        return t

    def _gen_land(self, left, right):
        rp = self.tmp()
        self.emit(f"  {rp} = alloca i32")
        self.emit(f"  store i32 0, ptr {rp}")

        lv = self._gen_expr(left)
        lc = self.tmp()
        self.emit(f"  {lc} = icmp ne i32 {lv}, 0")
        rhs_l = self.lbl("land.rhs")
        end_l = self.lbl("land.end")
        self.emit_cbr(lc, rhs_l, end_l)

        self.emit_label(rhs_l)
        rv = self._gen_expr(right)
        rc = self.tmp()
        self.emit(f"  {rc} = icmp ne i32 {rv}, 0")
        ri = self.tmp()
        self.emit(f"  {ri} = zext i1 {rc} to i32")
        self.emit(f"  store i32 {ri}, ptr {rp}")
        self.emit_br(end_l)

        self.emit_label(end_l)
        res = self.tmp()
        self.emit(f"  {res} = load i32, ptr {rp}")
        return res

    def _gen_lor(self, left, right):
        rp = self.tmp()
        self.emit(f"  {rp} = alloca i32")
        self.emit(f"  store i32 1, ptr {rp}")

        lv = self._gen_expr(left)
        lc = self.tmp()
        self.emit(f"  {lc} = icmp ne i32 {lv}, 0")
        rhs_l = self.lbl("lor.rhs")
        end_l = self.lbl("lor.end")
        self.emit_cbr(lc, end_l, rhs_l)

        self.emit_label(rhs_l)
        rv = self._gen_expr(right)
        rc = self.tmp()
        self.emit(f"  {rc} = icmp ne i32 {rv}, 0")
        ri = self.tmp()
        self.emit(f"  {ri} = zext i1 {rc} to i32")
        self.emit(f"  store i32 {ri}, ptr {rp}")
        self.emit_br(end_l)

        self.emit_label(end_l)
        res = self.tmp()
        self.emit(f"  {res} = load i32, ptr {rp}")
        return res

    def _gen_unary(self, node):
        _, op, operand = node
        v = self._gen_expr(operand)
        if op == '+': return v
        t = self.tmp()
        if op == '-':
            self.emit(f"  {t} = sub i32 0, {v}")
        elif op == '!':
            c = self.tmp()
            self.emit(f"  {c} = icmp eq i32 {v}, 0")
            self.emit(f"  {t} = zext i1 {c} to i32")
        return t

    def _gen_call(self, node):
        _, name, args = node
        sig = self.func_sigs[name]
        arg_strs = []
        for i, arg in enumerate(args):
            if i < len(sig['params']) and sig['params'][i]['arr']:
                ptr = self._gen_array_arg(arg)
                arg_strs.append(f"ptr {ptr}")
            else:
                val = self._gen_expr(arg)
                arg_strs.append(f"i32 {val}")
        joined = ', '.join(arg_strs)
        if sig['ret'] == 'void':
            self.emit(f"  call void @{name}({joined})")
            return '0'
        else:
            t = self.tmp()
            self.emit(f"  {t} = call i32 @{name}({joined})")
            return t

    # -- lval address computation --
    def _gen_lval_addr(self, node):
        """Return a ptr to the addressed element."""
        _, name, indices = node
        var = self.lookup(name)
        idx_regs = [self._gen_expr(ix) for ix in indices]

        if var.is_param_ptr:
            base = self.tmp()
            self.emit(f"  {base} = load ptr, ptr {var.ptr}")
            if len(idx_regs) == 0:
                return base
            if len(var.dims) == 0:
                # int a[] - flat ptr
                p = self.tmp()
                self.emit(f"  {p} = getelementptr i32, ptr {base}, i32 {idx_regs[0]}")
                return p
            else:
                inner_ty = self.dims_ty(var.dims)
                gep_args = ', '.join(f'i32 {r}' for r in idx_regs)
                p = self.tmp()
                self.emit(f"  {p} = getelementptr {inner_ty}, ptr {base}, {gep_args}")
                return p
        else:
            if len(var.dims) == 0:
                return var.ptr
            ty = self.dims_ty(var.dims)
            gep_args = 'i32 0, ' + ', '.join(f'i32 {r}' for r in idx_regs)
            p = self.tmp()
            self.emit(f"  {p} = getelementptr {ty}, ptr {var.ptr}, {gep_args}")
            return p

    def _gen_array_arg(self, expr):
        """Generate a pointer to pass as an array argument."""
        if expr[0] != 'LVal':
            raise ValueError("Array arg must be lval")
        _, name, indices = expr
        var = self.lookup(name)
        idx_regs = [self._gen_expr(ix) for ix in indices]

        if var.is_param_ptr:
            base = self.tmp()
            self.emit(f"  {base} = load ptr, ptr {var.ptr}")
            if len(idx_regs) == 0:
                return base
            if len(var.dims) == 0:
                p = self.tmp()
                self.emit(f"  {p} = getelementptr i32, ptr {base}, i32 {idx_regs[0]}")
                return p
            else:
                inner_ty = self.dims_ty(var.dims)
                gep_args = ', '.join(f'i32 {r}' for r in idx_regs)
                p = self.tmp()
                self.emit(f"  {p} = getelementptr {inner_ty}, ptr {base}, {gep_args}")
                return p
        else:
            if len(var.dims) == 0:
                return var.ptr
            ty = self.dims_ty(var.dims)
            if len(idx_regs) == 0:
                # whole array: return ptr to start
                p = self.tmp()
                self.emit(f"  {p} = getelementptr {ty}, ptr {var.ptr}, i32 0, i32 0")
                return p
            else:
                gep_args = 'i32 0, ' + ', '.join(f'i32 {r}' for r in idx_regs)
                p = self.tmp()
                self.emit(f"  {p} = getelementptr {ty}, ptr {var.ptr}, {gep_args}")
                return p


# ======================================================================
# MAIN
# ======================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: sysy_compiler <file.sy>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        src = f.read()
    toks = tokenize(src)
    parser = Parser(toks)
    items = parser.parse()
    gen = IRGen()
    ir = gen.generate(items)
    print(ir)

if __name__ == '__main__':
    main()
