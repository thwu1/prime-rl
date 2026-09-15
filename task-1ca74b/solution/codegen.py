#!/usr/bin/env python3
"""SysY to LLVM IR code generator. Produces .ll text from .sy source."""

import sys, argparse, os

sys.path.insert(0, '/app')
from parser import Lexer, Parser


class SymInfo:
    __slots__ = ('name', 'reg', 'is_global', 'dims', 'is_const', 'const_val',
                 'is_param_arr', 'param_inner_dims', 'init_data')
    def __init__(self, name, reg=None, is_global=False, dims=None,
                 is_const=False, const_val=None, is_param_arr=False,
                 param_inner_dims=None):
        self.name = name; self.reg = reg; self.is_global = is_global
        self.dims = dims; self.is_const = is_const; self.const_val = const_val
        self.is_param_arr = is_param_arr; self.param_inner_dims = param_inner_dims
        self.init_data = None


class Scope:
    def __init__(self, parent=None):
        self.parent = parent; self.syms = {}
    def define(self, sym):
        self.syms[sym.name] = sym
    def lookup(self, name):
        if name in self.syms: return self.syms[name]
        if self.parent: return self.parent.lookup(name)
        return None


class Codegen:
    def __init__(self):
        self.lines = []; self.gscope = Scope(); self.gorder = []
        self.fns = {}; self.tc = 0; self.lc = 0; self.loop_stk = []

    def tmp(self):
        self.tc += 1; return f'%t{self.tc}'
    def lbl(self, pre='L'):
        self.lc += 1; return f'{pre}{self.lc}'
    def emit(self, s):
        self.lines.append(s)

    def llvm_type(self, dims):
        if not dims: return 'i32'
        if len(dims) == 1: return f'[{dims[0]} x i32]'
        return f'[{dims[0]} x {self.llvm_type(dims[1:])}]'

    # ---- constant evaluation ----
    def _evc(self, expr, scope=None):
        if scope is None: scope = self.gscope
        t = expr[0]
        if t == 'num': return expr[1]
        if t == 'lv':
            _, nm, idxs = expr
            sym = scope.lookup(nm)
            if sym and sym.is_const and sym.const_val is not None:
                v = sym.const_val
                for ix in idxs: v = v[self._evc(ix, scope)]
                return v
            raise ValueError(f"Not constant: {nm}")
        if t == 'bop':
            _, op, l, r = expr
            a, b = self._evc(l, scope), self._evc(r, scope)
            if op == '+': return a + b
            if op == '-': return a - b
            if op == '*': return a * b
            if op == '/': return int(a / b) if b else 0
            if op == '%': return a - int(a / b) * b if b else 0
            if op == '<': return 1 if a < b else 0
            if op == '>': return 1 if a > b else 0
            if op == '<=': return 1 if a <= b else 0
            if op == '>=': return 1 if a >= b else 0
            if op == '==': return 1 if a == b else 0
            if op == '!=': return 1 if a != b else 0
            if op == '&&': return 1 if (a and b) else 0
            if op == '||': return 1 if (a or b) else 0
        if t == 'uop':
            _, op, operand = expr; v = self._evc(operand, scope)
            if op == '+': return v
            if op == '-': return -v
            if op == '!': return 1 if v == 0 else 0
        raise ValueError(f"Not constant: {expr}")

    def _evc_init(self, init, scope=None):
        if init[0] == 'iexp': return self._evc(init[1], scope)
        if init[0] == 'ilist': return [self._evc_init(i, scope) for i in init[1]]
        raise ValueError(f"Unknown init: {init}")

    # ---- initializer handling ----
    def _flat_init(self, init, dims, scope=None):
        if len(dims) == 1:
            r = [0] * dims[0]
            if init[0] == 'ilist':
                for i, item in enumerate(init[1]):
                    if i >= dims[0]: break
                    if item[0] == 'iexp': r[i] = self._evc(item[1], scope)
            return r
        sub = dims[1:]
        ssz = 1
        for d in sub: ssz *= d
        result = []
        if init[0] == 'ilist':
            items = init[1]; i = 0
            for row in range(dims[0]):
                if i >= len(items):
                    result.append(self._mkz(sub))
                elif items[i][0] == 'ilist':
                    result.append(self._flat_init(items[i], sub, scope)); i += 1
                else:
                    flat = [0] * ssz
                    for j in range(ssz):
                        if i < len(items) and items[i][0] == 'iexp':
                            flat[j] = self._evc(items[i][1], scope); i += 1
                        elif i < len(items) and items[i][0] == 'ilist': break
                        else: break
                    result.append(self._unflat(flat, sub))
        return result

    def _mkz(self, dims):
        if len(dims) == 1: return [0] * dims[0]
        return [self._mkz(dims[1:]) for _ in range(dims[0])]

    def _unflat(self, flat, dims):
        if len(dims) == 1: return flat[:dims[0]]
        ssz = 1
        for d in dims[1:]: ssz *= d
        return [self._unflat(flat[i*ssz:(i+1)*ssz], dims[1:]) for i in range(dims[0])]

    def _llvm_const(self, data, dims):
        if not dims: return f'i32 {data}'
        if len(dims) == 1:
            return f'[{dims[0]} x i32] [{", ".join(f"i32 {v}" for v in data)}]'
        parts = ', '.join(self._llvm_const(s, dims[1:]) for s in data)
        return f'{self.llvm_type(dims)} [{parts}]'

    def _has_nz(self, data):
        if isinstance(data, list): return any(self._has_nz(x) for x in data)
        return data != 0

    # ---- global registration ----
    def _reg_gvar(self, vdef):
        _, name, dexprs, init = vdef
        if dexprs:
            dims = [self._evc(d) for d in dexprs]
            sym = SymInfo(name, reg=f'@{name}', is_global=True, dims=dims)
            if init: sym.init_data = self._flat_init(init, dims)
            self.gscope.define(sym)
        else:
            sym = SymInfo(name, reg=f'@{name}', is_global=True)
            sym.init_data = self._evc(init[1]) if init and init[0] == 'iexp' else 0
            self.gscope.define(sym)
        self.gorder.append(name)

    def _reg_gconst(self, cdef):
        _, name, dexprs, init = cdef
        if dexprs:
            dims = [self._evc(d) for d in dexprs]
            cv = self._evc_init(init)
            sym = SymInfo(name, reg=f'@{name}', is_global=True, dims=dims,
                         is_const=True, const_val=cv)
            sym.init_data = self._flat_init(init, dims)
            self.gscope.define(sym)
        else:
            v = self._evc(init[1])
            sym = SymInfo(name, reg=f'@{name}', is_global=True,
                         is_const=True, const_val=v)
            sym.init_data = v
            self.gscope.define(sym)
        self.gorder.append(name)

    # ---- compile entry ----
    def compile(self, source):
        toks = Lexer(source).tokenize()
        ast = Parser(toks).parse()
        for node in ast:
            t = node[0]
            if t == 'fdef': self.fns[node[2]] = node
            elif t == 'vdecl':
                for vd in node[1]: self._reg_gvar(vd)
            elif t == 'cdecl':
                for cd in node[1]: self._reg_gconst(cd)

        self.emit('declare i32 @getint()')
        self.emit('declare i32 @getch()')
        self.emit('declare i32 @getarray(ptr)')
        self.emit('declare void @putint(i32)')
        self.emit('declare void @putch(i32)')
        self.emit('declare void @putarray(i32, ptr)')
        self.emit('')

        for gn in self.gorder:
            sym = self.gscope.lookup(gn)
            if sym.dims:
                ty = self.llvm_type(sym.dims)
                if sym.init_data and self._has_nz(sym.init_data):
                    self.emit(f'@{gn} = global {self._llvm_const(sym.init_data, sym.dims)}')
                else:
                    self.emit(f'@{gn} = global {ty} zeroinitializer')
            else:
                iv = sym.init_data if sym.init_data is not None else 0
                self.emit(f'@{gn} = global i32 {iv}')
        if self.gorder: self.emit('')

        for node in ast:
            if node[0] == 'fdef':
                self._gen_func(node); self.emit('')

        return '\n'.join(self.lines) + '\n'

    # ---- function codegen ----
    def _gen_func(self, fdef):
        _, rt, name, params, body = fdef
        self.tc = 0
        scope = Scope(self.gscope)
        pstrs, pregs = [], []
        for i, par in enumerate(params):
            _, pn, pdims = par
            preg = f'%p{i}'; pregs.append(preg)
            pstrs.append(f'{"ptr" if pdims is not None else "i32"} {preg}')

        retty = 'i32' if rt == 'int' else 'void'
        self.emit(f'define {retty} @{name}({", ".join(pstrs)}) {{')
        self.emit('entry:')

        for i, par in enumerate(params):
            _, pn, pdims = par
            areg = self.tmp()
            if pdims is not None:
                self.emit(f'  {areg} = alloca ptr')
                self.emit(f'  store ptr {pregs[i]}, ptr {areg}')
                inner = None
                if len(pdims) > 1:
                    inner = [self._evc(d, scope) for d in pdims[1:]]
                scope.define(SymInfo(pn, reg=areg, is_param_arr=True,
                                    param_inner_dims=inner))
            else:
                self.emit(f'  {areg} = alloca i32')
                self.emit(f'  store i32 {pregs[i]}, ptr {areg}')
                scope.define(SymInfo(pn, reg=areg))

        self._gen_blk(body, scope, rt == 'void')
        if rt == 'void': self.emit('  ret void')
        else: self.emit('  ret i32 0')
        self.emit('}')

    def _gen_blk(self, node, pscope, isvoid):
        scope = Scope(pscope)
        for item in node[1]: self._gen_item(item, scope, isvoid)

    def _gen_item(self, node, scope, isvoid):
        t = node[0]
        if t == 'vdecl': self._gen_vdecl(node, scope)
        elif t == 'cdecl': self._gen_cdecl(node, scope)
        else: self._gen_stmt(node, scope, isvoid)

    # ---- declarations ----
    def _gen_vdecl(self, node, scope):
        for vd in node[1]:
            _, nm, dexprs, init = vd
            if dexprs:
                dims = [self._evc(d, scope) for d in dexprs]
                areg = self.tmp()
                self.emit(f'  {areg} = alloca {self.llvm_type(dims)}')
                scope.define(SymInfo(nm, reg=areg, dims=dims))
                self._init_arr(areg, init, dims, scope)
            else:
                areg = self.tmp()
                self.emit(f'  {areg} = alloca i32')
                scope.define(SymInfo(nm, reg=areg))
                if init and init[0] == 'iexp':
                    v = self._gen_expr(init[1], scope)
                    self.emit(f'  store i32 {v}, ptr {areg}')
                else:
                    self.emit(f'  store i32 0, ptr {areg}')

    def _gen_cdecl(self, node, scope):
        for cd in node[1]:
            _, nm, dexprs, init = cd
            if dexprs:
                dims = [self._evc(d, scope) for d in dexprs]
                areg = self.tmp()
                self.emit(f'  {areg} = alloca {self.llvm_type(dims)}')
                cv = self._evc_init(init, scope)
                scope.define(SymInfo(nm, reg=areg, dims=dims, is_const=True, const_val=cv))
                self._init_arr(areg, init, dims, scope)
            else:
                v = self._evc(init[1], scope)
                areg = self.tmp()
                self.emit(f'  {areg} = alloca i32')
                self.emit(f'  store i32 {v}, ptr {areg}')
                scope.define(SymInfo(nm, reg=areg, is_const=True, const_val=v))

    # ---- array init ----
    def _init_arr(self, base, init, dims, scope):
        total = 1
        for d in dims: total *= d
        for i in range(total):
            idxs = self._lin2multi(i, dims)
            p = self._gep_const(base, dims, idxs)
            self.emit(f'  store i32 0, ptr {p}')
        if init:
            positions = []
            self._collect_init(init, dims, [], positions)
            for idxs, expr_node in positions:
                p = self._gep_const(base, dims, idxs)
                v = self._gen_expr(expr_node, scope)
                self.emit(f'  store i32 {v}, ptr {p}')

    def _lin2multi(self, i, dims):
        idxs = []
        for d in reversed(dims):
            idxs.insert(0, i % d); i //= d
        return idxs

    def _gep_const(self, base, dims, idxs):
        p = self.tmp()
        istr = ', '.join(f'i32 {x}' for x in idxs)
        self.emit(f'  {p} = getelementptr {self.llvm_type(dims)}, ptr {base}, i32 0, {istr}')
        return p

    def _collect_init(self, init, dims, prefix, out):
        if len(dims) == 1:
            if init[0] == 'ilist':
                for i, item in enumerate(init[1]):
                    if i >= dims[0]: break
                    if item[0] == 'iexp': out.append((prefix + [i], item[1]))
            return
        if init[0] != 'ilist': return
        sub = dims[1:]
        ssz = 1
        for d in sub: ssz *= d
        items = init[1]; i = 0
        for row in range(dims[0]):
            if i >= len(items): break
            if items[i][0] == 'ilist':
                self._collect_init(items[i], sub, prefix + [row], out); i += 1
            else:
                flat = []
                for _ in range(ssz):
                    if i < len(items) and items[i][0] == 'iexp':
                        flat.append(items[i]); i += 1
                    elif i < len(items) and items[i][0] == 'ilist': break
                    else: break
                self._collect_init(('ilist', flat), sub, prefix + [row], out)

    # ---- statements ----
    def _gen_stmt(self, node, scope, isvoid):
        t = node[0]
        if t == 'asgn':
            _, lval, expr = node; _, nm, idxs = lval
            sym = scope.lookup(nm)
            val = self._gen_expr(expr, scope)
            if not idxs:
                self.emit(f'  store i32 {val}, ptr {"@" + nm if sym.is_global else sym.reg}')
            else:
                p = self._lval_ptr(lval, scope)
                self.emit(f'  store i32 {val}, ptr {p}')
        elif t == 'estmt':
            self._gen_expr(node[1], scope)
        elif t == 'blk':
            self._gen_blk(node, scope, isvoid)
        elif t == 'if':
            self._gen_if(node, scope, isvoid)
        elif t == 'whl':
            self._gen_while(node, scope, isvoid)
        elif t == 'brk':
            if self.loop_stk:
                self.emit(f'  br label %{self.loop_stk[-1][1]}')
                self.emit(f'{self.lbl("dead")}:')
        elif t == 'cont':
            if self.loop_stk:
                self.emit(f'  br label %{self.loop_stk[-1][0]}')
                self.emit(f'{self.lbl("dead")}:')
        elif t == 'ret':
            if node[1] is not None:
                v = self._gen_expr(node[1], scope)
                self.emit(f'  ret i32 {v}')
            else:
                self.emit('  ret void')
            self.emit(f'{self.lbl("dead")}:')
        elif t == 'empty':
            pass

    def _gen_if(self, node, scope, isvoid):
        _, cond, th, el = node
        cv = self._gen_expr(cond, scope)
        c = self.tmp()
        self.emit(f'  {c} = icmp ne i32 {cv}, 0')
        if el:
            lt, le, lend = self.lbl('then'), self.lbl('else'), self.lbl('endif')
            self.emit(f'  br i1 {c}, label %{lt}, label %{le}')
            self.emit(f'{lt}:')
            self._gen_stmt(th, scope, isvoid)
            self.emit(f'  br label %{lend}')
            self.emit(f'{le}:')
            self._gen_stmt(el, scope, isvoid)
            self.emit(f'  br label %{lend}')
            self.emit(f'{lend}:')
        else:
            lt, lend = self.lbl('then'), self.lbl('endif')
            self.emit(f'  br i1 {c}, label %{lt}, label %{lend}')
            self.emit(f'{lt}:')
            self._gen_stmt(th, scope, isvoid)
            self.emit(f'  br label %{lend}')
            self.emit(f'{lend}:')

    def _gen_while(self, node, scope, isvoid):
        _, cond, body = node
        lcond, lbody, lend = self.lbl('wcond'), self.lbl('wbody'), self.lbl('wend')
        self.emit(f'  br label %{lcond}')
        self.emit(f'{lcond}:')
        cv = self._gen_expr(cond, scope)
        c = self.tmp()
        self.emit(f'  {c} = icmp ne i32 {cv}, 0')
        self.emit(f'  br i1 {c}, label %{lbody}, label %{lend}')
        self.emit(f'{lbody}:')
        self.loop_stk.append((lcond, lend))
        self._gen_stmt(body, scope, isvoid)
        self.loop_stk.pop()
        self.emit(f'  br label %{lcond}')
        self.emit(f'{lend}:')

    # ---- lvalue pointer ----
    def _lval_ptr(self, lval, scope):
        _, nm, idxs = lval; sym = scope.lookup(nm)
        if sym.is_param_arr:
            base = self.tmp()
            self.emit(f'  {base} = load ptr, ptr {sym.reg}')
            if sym.param_inner_dims and len(idxs) > 0:
                ix = self._gen_expr(idxs[0], scope)
                ity = self.llvm_type(sym.param_inner_dims)
                p = self.tmp()
                self.emit(f'  {p} = getelementptr {ity}, ptr {base}, i32 {ix}')
                for k in range(1, len(idxs)):
                    ix2 = self._gen_expr(idxs[k], scope)
                    rdims = sym.param_inner_dims[k-1:]
                    rty = self.llvm_type(rdims)
                    p2 = self.tmp()
                    self.emit(f'  {p2} = getelementptr {rty}, ptr {p}, i32 0, i32 {ix2}')
                    p = p2
                return p
            else:
                for ix_expr in idxs:
                    ix = self._gen_expr(ix_expr, scope)
                    p = self.tmp()
                    self.emit(f'  {p} = getelementptr i32, ptr {base}, i32 {ix}')
                    base = p
                return base
        elif sym.is_global and sym.dims:
            return self._gep_dyn(f'@{nm}', sym.dims, idxs, scope)
        elif sym.dims:
            return self._gep_dyn(sym.reg, sym.dims, idxs, scope)
        else:
            return f'@{nm}' if sym.is_global else sym.reg

    def _gep_dyn(self, base, dims, idx_exprs, scope):
        ivs = [self._gen_expr(ix, scope) for ix in idx_exprs]
        istr = ', '.join(f'i32 {v}' for v in ivs)
        p = self.tmp()
        self.emit(f'  {p} = getelementptr {self.llvm_type(dims)}, ptr {base}, i32 0, {istr}')
        return p

    # ---- expressions ----
    _BIN = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'sdiv', '%': 'srem'}
    _CMP = {'<': 'slt', '>': 'sgt', '<=': 'sle', '>=': 'sge', '==': 'eq', '!=': 'ne'}

    def _gen_expr(self, node, scope):
        t = node[0]
        if t == 'num': return str(node[1])
        if t == 'lv': return self._gen_lv(node, scope)
        if t == 'bop':
            _, op, l, r = node
            if op == '&&': return self._gen_and(l, r, scope)
            if op == '||': return self._gen_or(l, r, scope)
            lv, rv = self._gen_expr(l, scope), self._gen_expr(r, scope)
            res = self.tmp()
            if op in self._BIN:
                self.emit(f'  {res} = {self._BIN[op]} i32 {lv}, {rv}')
                return res
            if op in self._CMP:
                c = self.tmp()
                self.emit(f'  {c} = icmp {self._CMP[op]} i32 {lv}, {rv}')
                self.emit(f'  {res} = zext i1 {c} to i32')
                return res
        if t == 'uop':
            _, op, operand = node; v = self._gen_expr(operand, scope)
            if op == '-':
                r = self.tmp(); self.emit(f'  {r} = sub i32 0, {v}'); return r
            if op == '!':
                c, r = self.tmp(), self.tmp()
                self.emit(f'  {c} = icmp eq i32 {v}, 0')
                self.emit(f'  {r} = zext i1 {c} to i32'); return r
            return v
        if t == 'call': return self._gen_call(node, scope)
        raise RuntimeError(f"Unknown expr: {node}")

    def _gen_lv(self, node, scope):
        _, nm, idxs = node; sym = scope.lookup(nm)
        if sym.is_const and sym.const_val is not None:
            if not sym.dims: return str(sym.const_val)
            if sym.dims and len(idxs) == len(sym.dims):
                try:
                    v = sym.const_val
                    for ix in idxs: v = v[self._evc(ix, scope)]
                    return str(v)
                except: pass
        if not idxs and not sym.dims and not sym.is_param_arr:
            r = self.tmp()
            self.emit(f'  {r} = load i32, ptr {"@" + nm if sym.is_global else sym.reg}')
            return r
        if not idxs and (sym.dims or sym.is_param_arr):
            if sym.is_param_arr:
                r = self.tmp()
                self.emit(f'  {r} = load ptr, ptr {sym.reg}')
                return r
            return f'@{nm}' if sym.is_global else sym.reg
        if sym.dims and len(idxs) < len(sym.dims):
            base = f'@{nm}' if sym.is_global else sym.reg
            return self._gep_dyn(base, sym.dims, idxs, scope)
        p = self._lval_ptr(node, scope)
        r = self.tmp()
        self.emit(f'  {r} = load i32, ptr {p}')
        return r

    def _gen_and(self, left, right, scope):
        res = self.tmp()
        self.emit(f'  {res} = alloca i32')
        self.emit(f'  store i32 0, ptr {res}')
        lrhs, lend = self.lbl('arhs'), self.lbl('aend')
        lv = self._gen_expr(left, scope)
        c = self.tmp()
        self.emit(f'  {c} = icmp ne i32 {lv}, 0')
        self.emit(f'  br i1 {c}, label %{lrhs}, label %{lend}')
        self.emit(f'{lrhs}:')
        rv = self._gen_expr(right, scope)
        c2, r2 = self.tmp(), self.tmp()
        self.emit(f'  {c2} = icmp ne i32 {rv}, 0')
        self.emit(f'  {r2} = zext i1 {c2} to i32')
        self.emit(f'  store i32 {r2}, ptr {res}')
        self.emit(f'  br label %{lend}')
        self.emit(f'{lend}:')
        v = self.tmp()
        self.emit(f'  {v} = load i32, ptr {res}')
        return v

    def _gen_or(self, left, right, scope):
        res = self.tmp()
        self.emit(f'  {res} = alloca i32')
        self.emit(f'  store i32 1, ptr {res}')
        lrhs, lend = self.lbl('orhs'), self.lbl('oend')
        lv = self._gen_expr(left, scope)
        c = self.tmp()
        self.emit(f'  {c} = icmp ne i32 {lv}, 0')
        self.emit(f'  br i1 {c}, label %{lend}, label %{lrhs}')
        self.emit(f'{lrhs}:')
        rv = self._gen_expr(right, scope)
        c2, r2 = self.tmp(), self.tmp()
        self.emit(f'  {c2} = icmp ne i32 {rv}, 0')
        self.emit(f'  {r2} = zext i1 {c2} to i32')
        self.emit(f'  store i32 {r2}, ptr {res}')
        self.emit(f'  br label %{lend}')
        self.emit(f'{lend}:')
        v = self.tmp()
        self.emit(f'  {v} = load i32, ptr {res}')
        return v

    def _gen_call(self, node, scope):
        _, nm, args = node; avals = []
        for a in args:
            if a[0] == 'lv':
                _, anm, aidxs = a; asym = scope.lookup(anm)
                if asym and (asym.dims or asym.is_param_arr):
                    if not aidxs:
                        if asym.is_param_arr:
                            r = self.tmp()
                            self.emit(f'  {r} = load ptr, ptr {asym.reg}')
                            avals.append(('ptr', r))
                        elif asym.is_global:
                            avals.append(('ptr', f'@{anm}'))
                        else:
                            avals.append(('ptr', asym.reg))
                        continue
                    elif asym.dims and len(aidxs) < len(asym.dims):
                        base = f'@{anm}' if asym.is_global else asym.reg
                        p = self._gep_dyn(base, asym.dims, aidxs, scope)
                        avals.append(('ptr', p)); continue
                    elif asym.is_param_arr and aidxs and asym.param_inner_dims:
                        base = self.tmp()
                        self.emit(f'  {base} = load ptr, ptr {asym.reg}')
                        ix = self._gen_expr(aidxs[0], scope)
                        ity = self.llvm_type(asym.param_inner_dims)
                        p = self.tmp()
                        self.emit(f'  {p} = getelementptr {ity}, ptr {base}, i32 {ix}')
                        if len(aidxs) <= len(asym.param_inner_dims):
                            avals.append(('ptr', p)); continue
            v = self._gen_expr(a, scope)
            avals.append(('i32', v))

        if nm in self.fns: rty = 'i32' if self.fns[nm][1] == 'int' else 'void'
        elif nm in ('getint', 'getch', 'getarray'): rty = 'i32'
        else: rty = 'void'

        astr = ', '.join(f'{at} {av}' for at, av in avals)
        if rty == 'void':
            self.emit(f'  call void @{nm}({astr})'); return '0'
        else:
            r = self.tmp()
            self.emit(f'  {r} = call i32 @{nm}({astr})'); return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('-o', '--output', default=None)
    args = ap.parse_args()
    with open(args.input) as f: src = f.read()
    ir = Codegen().compile(src)
    if args.output:
        with open(args.output, 'w') as f: f.write(ir)
    else:
        sys.stdout.write(ir)

if __name__ == '__main__':
    main()
