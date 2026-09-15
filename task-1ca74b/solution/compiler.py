#!/usr/bin/env python3
"""SysY-to-bytecode compiler.  Reads .sy source, writes .bc for vm.py."""

import sys, argparse, os

sys.path.insert(0, '/app')
from parser import Lexer, Parser          # provided SysY parser


# ======================== SYMBOL TABLE ========================

class Symbol:
    __slots__ = ('name', 'slot', 'is_global', 'dims', 'is_const', 'const_val', 'init_data')

    def __init__(self, name, slot=None, is_global=False, dims=None,
                 is_const=False, const_val=None):
        self.name = name
        self.slot = slot
        self.is_global = is_global
        self.dims = dims          # None => scalar, list of ints => array
        self.is_const = is_const
        self.const_val = const_val  # compile-time value (int or nested list)
        self.init_data = None       # flat/nested list for array init, int for scalar


class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.syms = {}

    def define(self, sym):
        self.syms[sym.name] = sym

    def lookup(self, name):
        if name in self.syms:
            return self.syms[name]
        if self.parent:
            return self.parent.lookup(name)
        return None


# ======================== COMPILER ========================

class Compiler:
    def __init__(self):
        self.out = []
        self.gscope = Scope()
        self.gorder = []
        self.fns = {}
        self.lc = 0
        self.loop_stk = []          # (start_label, end_label)

    # ---- helpers ----
    def _lbl(self, pre='L'):
        self.lc += 1
        return f'{pre}_{self.lc}'

    def emit(self, s):
        self.out.append(s)

    # ---- compile entry ----
    def compile(self, source):
        toks = Lexer(source).tokenize()
        ast = Parser(toks).parse()

        # register globals & functions
        for node in ast:
            t = node[0]
            if t == 'fdef':
                self.fns[node[2]] = node
            elif t == 'vdecl':
                for vd in node[1]:
                    self._reg_gvar(vd)
            elif t == 'cdecl':
                for cd in node[1]:
                    self._reg_gconst(cd)

        # emit .global directives
        for gn in self.gorder:
            sym = self.gscope.lookup(gn)
            if sym.dims:
                self.emit(f'.global {gn} {" ".join(str(d) for d in sym.dims)}')
            else:
                self.emit(f'.global {gn}')

        # compile each function (preserve source order)
        for node in ast:
            if node[0] == 'fdef':
                self._cfunc(node)

        return '\n'.join(self.out) + '\n'

    # ---- constant evaluation ----
    def _evc(self, expr, scope=None):
        """Evaluate constant expression at compile time."""
        if scope is None:
            scope = self.gscope
        t = expr[0]
        if t == 'num':
            return expr[1]
        if t == 'lv':
            _, nm, idxs = expr
            sym = scope.lookup(nm)
            if sym and sym.is_const and sym.const_val is not None:
                v = sym.const_val
                if not idxs:
                    return v
                for ix in idxs:
                    v = v[self._evc(ix, scope)]
                return v
            raise ValueError(f"Not constant: {nm}")
        if t == 'bop':
            _, op, l, r = expr
            lv = self._evc(l, scope)
            rv = self._evc(r, scope)
            if op == '+': return lv + rv
            if op == '-': return lv - rv
            if op == '*': return lv * rv
            if op == '/': return int(lv / rv) if rv else 0
            if op == '%': return lv - int(lv / rv) * rv if rv else 0
            if op == '<': return 1 if lv < rv else 0
            if op == '>': return 1 if lv > rv else 0
            if op == '<=': return 1 if lv <= rv else 0
            if op == '>=': return 1 if lv >= rv else 0
            if op == '==': return 1 if lv == rv else 0
            if op == '!=': return 1 if lv != rv else 0
            if op == '&&': return 1 if (lv != 0 and rv != 0) else 0
            if op == '||': return 1 if (lv != 0 or rv != 0) else 0
        if t == 'uop':
            _, op, operand = expr
            v = self._evc(operand, scope)
            if op == '+': return v
            if op == '-': return -v
            if op == '!': return 1 if v == 0 else 0
        raise ValueError(f"Not a constant expr: {expr}")

    def _evc_init(self, init, scope=None):
        """Evaluate constant initializer recursively."""
        if init[0] == 'iexp':
            return self._evc(init[1], scope)
        if init[0] == 'ilist':
            return [self._evc_init(item, scope) for item in init[1]]
        raise ValueError(f"Unknown init node: {init}")

    # ---- global registration ----
    def _reg_gvar(self, vdef):
        _, name, dexprs, init = vdef
        if dexprs:
            dims = [self._evc(d) for d in dexprs]
            sym = Symbol(name, is_global=True, dims=dims)
            if init:
                sym.init_data = self._flat_init(init, dims)
            self.gscope.define(sym)
        else:
            sym = Symbol(name, is_global=True)
            if init and init[0] == 'iexp':
                sym.init_data = self._evc(init[1])
            else:
                sym.init_data = 0
            self.gscope.define(sym)
        self.gorder.append(name)

    def _reg_gconst(self, cdef):
        _, name, dexprs, init = cdef
        if dexprs:
            dims = [self._evc(d) for d in dexprs]
            cv = self._evc_init(init)
            sym = Symbol(name, is_global=True, dims=dims, is_const=True, const_val=cv)
            sym.init_data = self._flat_init(init, dims)
            self.gscope.define(sym)
        else:
            v = self._evc(init[1])
            sym = Symbol(name, is_global=True, is_const=True, const_val=v)
            sym.init_data = v
            self.gscope.define(sym)
        self.gorder.append(name)

    # ---- flatten initializer (compile-time, for global init) ----
    def _flat_init(self, init, dims):
        if len(dims) == 1:
            flat = [0] * dims[0]
            if init[0] == 'ilist':
                for i, item in enumerate(init[1]):
                    if i >= dims[0]:
                        break
                    if item[0] == 'iexp':
                        flat[i] = self._evc(item[1])
            return flat
        sub = dims[1:]
        ssz = 1
        for d in sub:
            ssz *= d
        result = []
        if init[0] == 'ilist':
            items = init[1]
            i = 0
            for row in range(dims[0]):
                if i >= len(items):
                    result.append(self._mkz(sub))
                elif items[i][0] == 'ilist':
                    result.append(self._flat_init(items[i], sub))
                    i += 1
                else:
                    flat = [0] * ssz
                    for j in range(ssz):
                        if i < len(items) and items[i][0] == 'iexp':
                            flat[j] = self._evc(items[i][1])
                            i += 1
                        elif i < len(items) and items[i][0] == 'ilist':
                            break
                        else:
                            break
                    result.append(self._unflat(flat, sub))
        else:
            for _ in range(dims[0]):
                result.append(self._mkz(sub))
        return result

    def _mkz(self, dims):
        if len(dims) == 1:
            return [0] * dims[0]
        return [self._mkz(dims[1:]) for _ in range(dims[0])]

    def _unflat(self, flat, dims):
        if len(dims) == 1:
            return flat[:dims[0]]
        ssz = 1
        for d in dims[1:]:
            ssz *= d
        res = []
        for i in range(dims[0]):
            st = i * ssz
            res.append(self._unflat(flat[st:st + ssz], dims[1:]))
        return res

    # ---- function compilation ----
    def _cfunc(self, fdef):
        _, rt, name, params, body = fdef
        scope = Scope(self.gscope)
        slot = [0]

        def alloc():
            s = slot[0]; slot[0] += 1; return s

        # register params
        for par in params:
            _, pn, pdims = par
            s = alloc()
            sym = Symbol(pn, slot=s, dims=pdims)
            scope.define(sym)

        nparams = len(params)
        nlocals = self._cnt_locals(body)

        self.emit(f'.func {name} {nparams} {nlocals}')

        # global init at start of main
        if name == 'main':
            self._emit_ginits()

        # generate body
        self._gblk(body, scope, alloc, rt == 'void')

        # fallthrough return
        if rt == 'void':
            self.emit('  RET')
        else:
            self.emit('  ICONST 0')
            self.emit('  RETV')

        self.emit('.endfunc')

    def _cnt_locals(self, node):
        t = node[0]
        if t == 'blk':
            return sum(self._cnt_locals(it) for it in node[1])
        if t in ('vdecl', 'cdecl'):
            return len(node[1])
        if t == 'if':
            c = self._cnt_locals(node[2])
            if node[3]:
                c += self._cnt_locals(node[3])
            return c
        if t == 'whl':
            return self._cnt_locals(node[2])
        return 0

    def _emit_ginits(self):
        for gn in self.gorder:
            sym = self.gscope.lookup(gn)
            if sym.dims:
                if sym.init_data:
                    self._emit_garr(gn, sym.init_data, sym.dims, [])
            else:
                if sym.init_data and sym.init_data != 0:
                    self.emit(f'  ICONST {sym.init_data}')
                    self.emit(f'  GSTORE {gn}')

    def _emit_garr(self, name, data, dims, prefix):
        if len(dims) == 1:
            for i, v in enumerate(data):
                if v != 0:
                    self.emit(f'  GLOAD {name}')
                    for idx in prefix:
                        self.emit(f'  ICONST {idx}')
                        self.emit('  ALOAD')
                    self.emit(f'  ICONST {i}')
                    self.emit(f'  ICONST {v}')
                    self.emit('  ASTORE')
        else:
            for i, sub in enumerate(data):
                self._emit_garr(name, sub, dims[1:], prefix + [i])

    # ---- code gen: blocks & items ----
    def _gblk(self, node, pscope, alloc, is_void):
        scope = Scope(pscope)
        for item in node[1]:
            self._gitem(item, scope, alloc, is_void)

    def _gitem(self, node, scope, alloc, is_void):
        t = node[0]
        if t == 'vdecl':
            self._gvdecl(node, scope, alloc)
        elif t == 'cdecl':
            self._gcdecl(node, scope, alloc)
        else:
            self._gstmt(node, scope, alloc, is_void)

    # ---- code gen: declarations ----
    def _gvdecl(self, node, scope, alloc):
        for vd in node[1]:
            _, nm, dexprs, init = vd
            s = alloc()
            if dexprs:
                dims = [self._evc(d, scope) for d in dexprs]
                sym = Symbol(nm, slot=s, dims=dims)
                scope.define(sym)
                self.emit(f'  NEWARRAY {" ".join(str(d) for d in dims)}')
                self.emit(f'  STORE {s}')
                if init:
                    self._garr_init(s, init, dims, scope)
            else:
                sym = Symbol(nm, slot=s)
                scope.define(sym)
                if init and init[0] == 'iexp':
                    self._gexpr(init[1], scope)
                else:
                    self.emit('  ICONST 0')
                self.emit(f'  STORE {s}')

    def _gcdecl(self, node, scope, alloc):
        for cd in node[1]:
            _, nm, dexprs, init = cd
            s = alloc()
            if dexprs:
                dims = [self._evc(d, scope) for d in dexprs]
                cv = self._evc_init(init, scope)
                sym = Symbol(nm, slot=s, dims=dims, is_const=True, const_val=cv)
                scope.define(sym)
                self.emit(f'  NEWARRAY {" ".join(str(d) for d in dims)}')
                self.emit(f'  STORE {s}')
                if init:
                    self._garr_init(s, init, dims, scope)
            else:
                v = self._evc(init[1], scope)
                sym = Symbol(nm, slot=s, is_const=True, const_val=v)
                scope.define(sym)
                self.emit(f'  ICONST {v}')
                self.emit(f'  STORE {s}')

    # ---- array initialization (runtime code gen) ----
    def _garr_init(self, slot, init, dims, scope):
        positions = []
        self._collect_init(init, dims, [], positions)
        for indices, expr_node in positions:
            self.emit(f'  LOAD {slot}')
            for idx in indices[:-1]:
                self.emit(f'  ICONST {idx}')
                self.emit('  ALOAD')
            self.emit(f'  ICONST {indices[-1]}')
            self._gexpr(expr_node, scope)
            self.emit('  ASTORE')

    def _collect_init(self, init, dims, prefix, out):
        if len(dims) == 1:
            if init[0] == 'ilist':
                for i, item in enumerate(init[1]):
                    if i >= dims[0]:
                        break
                    if item[0] == 'iexp':
                        out.append((prefix + [i], item[1]))
            return
        if init[0] != 'ilist':
            return
        sub = dims[1:]
        ssz = 1
        for d in sub:
            ssz *= d
        items = init[1]
        i = 0
        for row in range(dims[0]):
            if i >= len(items):
                break
            if items[i][0] == 'ilist':
                self._collect_init(items[i], sub, prefix + [row], out)
                i += 1
            else:
                flat = []
                for _ in range(ssz):
                    if i < len(items) and items[i][0] == 'iexp':
                        flat.append(items[i])
                        i += 1
                    elif i < len(items) and items[i][0] == 'ilist':
                        break
                    else:
                        break
                self._collect_init(('ilist', flat), sub, prefix + [row], out)

    # ---- code gen: statements ----
    def _gstmt(self, node, scope, alloc, is_void):
        t = node[0]
        if t == 'asgn':
            self._gasgn(node, scope)
        elif t == 'estmt':
            self._gexpr(node[1], scope)
            self.emit('  POP')
        elif t == 'blk':
            self._gblk(node, scope, alloc, is_void)
        elif t == 'if':
            self._gif(node, scope, alloc, is_void)
        elif t == 'whl':
            self._gwhl(node, scope, alloc, is_void)
        elif t == 'brk':
            if self.loop_stk:
                self.emit(f'  JMP {self.loop_stk[-1][1]}')
        elif t == 'cont':
            if self.loop_stk:
                self.emit(f'  JMP {self.loop_stk[-1][0]}')
        elif t == 'ret':
            if node[1] is not None:
                self._gexpr(node[1], scope)
                self.emit('  RETV')
            else:
                self.emit('  RET')
        elif t == 'empty':
            pass

    def _gasgn(self, node, scope):
        _, lval, expr = node
        _, nm, idxs = lval
        sym = scope.lookup(nm)
        if not idxs:
            self._gexpr(expr, scope)
            if sym.is_global:
                self.emit(f'  GSTORE {nm}')
            else:
                self.emit(f'  STORE {sym.slot}')
        else:
            # array element assignment
            if sym.is_global:
                self.emit(f'  GLOAD {nm}')
            else:
                self.emit(f'  LOAD {sym.slot}')
            for ix in idxs[:-1]:
                self._gexpr(ix, scope)
                self.emit('  ALOAD')
            self._gexpr(idxs[-1], scope)
            self._gexpr(expr, scope)
            self.emit('  ASTORE')

    def _gif(self, node, scope, alloc, is_void):
        _, cond, th, el = node
        if el:
            el_lbl = self._lbl('ELSE')
            end_lbl = self._lbl('ENDIF')
            self._gexpr(cond, scope)
            self.emit(f'  JZ {el_lbl}')
            self._gstmt(th, scope, alloc, is_void)
            self.emit(f'  JMP {end_lbl}')
            self.emit(f'  LABEL {el_lbl}')
            self._gstmt(el, scope, alloc, is_void)
            self.emit(f'  LABEL {end_lbl}')
        else:
            end_lbl = self._lbl('ENDIF')
            self._gexpr(cond, scope)
            self.emit(f'  JZ {end_lbl}')
            self._gstmt(th, scope, alloc, is_void)
            self.emit(f'  LABEL {end_lbl}')

    def _gwhl(self, node, scope, alloc, is_void):
        _, cond, body = node
        start = self._lbl('WHL')
        end = self._lbl('EWHL')
        self.emit(f'  LABEL {start}')
        self._gexpr(cond, scope)
        self.emit(f'  JZ {end}')
        self.loop_stk.append((start, end))
        self._gstmt(body, scope, alloc, is_void)
        self.loop_stk.pop()
        self.emit(f'  JMP {start}')
        self.emit(f'  LABEL {end}')

    # ---- code gen: expressions ----
    _OP = {'+':'ADD','-':'SUB','*':'MUL','/':'DIV','%':'MOD',
           '<':'LT','>':'GT','<=':'LE','>=':'GE','==':'EQ','!=':'NE'}

    def _gexpr(self, node, scope):
        t = node[0]

        if t == 'num':
            self.emit(f'  ICONST {node[1]}')

        elif t == 'lv':
            _, nm, idxs = node
            sym = scope.lookup(nm)
            if sym.is_global:
                self.emit(f'  GLOAD {nm}')
            else:
                self.emit(f'  LOAD {sym.slot}')
            for ix in idxs:
                self._gexpr(ix, scope)
                self.emit('  ALOAD')

        elif t == 'bop':
            _, op, l, r = node
            if op == '&&':
                fl = self._lbl('AF')
                el = self._lbl('AE')
                self._gexpr(l, scope)
                self.emit(f'  JZ {fl}')
                self._gexpr(r, scope)
                self.emit(f'  JZ {fl}')
                self.emit('  ICONST 1')
                self.emit(f'  JMP {el}')
                self.emit(f'  LABEL {fl}')
                self.emit('  ICONST 0')
                self.emit(f'  LABEL {el}')
            elif op == '||':
                tl = self._lbl('OT')
                el = self._lbl('OE')
                self._gexpr(l, scope)
                self.emit(f'  JNZ {tl}')
                self._gexpr(r, scope)
                self.emit(f'  JNZ {tl}')
                self.emit('  ICONST 0')
                self.emit(f'  JMP {el}')
                self.emit(f'  LABEL {tl}')
                self.emit('  ICONST 1')
                self.emit(f'  LABEL {el}')
            else:
                self._gexpr(l, scope)
                self._gexpr(r, scope)
                self.emit(f'  {self._OP[op]}')

        elif t == 'uop':
            _, op, operand = node
            self._gexpr(operand, scope)
            if op == '-':
                self.emit('  NEG')
            elif op == '!':
                self.emit('  NOT')
            # '+' is a no-op

        elif t == 'call':
            _, nm, args = node
            for a in args:
                self._gexpr(a, scope)
            self.emit(f'  CALL {nm} {len(args)}')


# ======================== MAIN ========================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('-o', '--output', default=None)
    args = ap.parse_args()

    with open(args.input) as f:
        src = f.read()

    bc = Compiler().compile(src)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(bc)
    else:
        sys.stdout.write(bc)


if __name__ == '__main__':
    main()
