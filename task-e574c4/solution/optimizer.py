#!/usr/bin/env python3
"""
TAC Optimizer — constant propagation/folding, dead-code elimination,
common sub-expression elimination, copy propagation, unreachable-code removal,
Graphviz DOT CFG generation, and LLVM IR backend.
"""

import sys
import os
import re
from collections import OrderedDict, defaultdict

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def is_literal(s):
    try:
        int(str(s))
        return True
    except (ValueError, TypeError):
        return False


def lit_val(s):
    return int(str(s))


def eval_binop(l, op, r):
    if op == '+': return l + r
    if op == '-': return l - r
    if op == '*': return l * r
    if op == '/': return l // r if r != 0 else 0
    if op == '%': return l % r if r != 0 else 0
    if op == '==': return 1 if l == r else 0
    if op == '!=': return 1 if l != r else 0
    if op == '<': return 1 if l < r else 0
    if op == '>': return 1 if l > r else 0
    if op == '<=': return 1 if l <= r else 0
    if op == '>=': return 1 if l >= r else 0
    if op == '&&': return 1 if (l and r) else 0
    if op == '||': return 1 if (l or r) else 0
    return None


def eval_unop(op, v):
    if op == '-': return -v
    if op == '!': return 1 if not v else 0
    return None


# ---------------------------------------------------------------------------
# IR data model
# ---------------------------------------------------------------------------

ASSIGN_CONST = 'ac'
ASSIGN_COPY  = 'cp'
BINOP        = 'bi'
UNOP         = 'un'
CALL         = 'ca'
PRINT        = 'pr'
IF           = 'if'
GOTO         = 'go'
RETURN       = 're'
NOP          = 'no'

HAS_DEST = {ASSIGN_CONST, ASSIGN_COPY, BINOP, UNOP, CALL}


class Instr:
    __slots__ = ('kind', 'dest', 'op', 'args', 'true_lbl', 'false_lbl',
                 'target', 'fname', 'dead')

    def __init__(self, kind, **kw):
        self.kind = kind
        self.dest = kw.get('dest')
        self.op = kw.get('op')
        self.args = kw.get('args', [])
        self.true_lbl = kw.get('true_lbl')
        self.false_lbl = kw.get('false_lbl')
        self.target = kw.get('target')
        self.fname = kw.get('fname')
        self.dead = False

    def uses(self):
        s = set()
        if self.kind in (BINOP, UNOP, ASSIGN_COPY):
            for a in self.args:
                if not is_literal(a):
                    s.add(a)
        elif self.kind == PRINT:
            if not is_literal(self.args[0]):
                s.add(self.args[0])
        elif self.kind == IF:
            if not is_literal(self.args[0]):
                s.add(self.args[0])
        elif self.kind == RETURN:
            if not is_literal(self.args[0]):
                s.add(self.args[0])
        elif self.kind == CALL:
            for a in self.args:
                if not is_literal(a):
                    s.add(a)
        return s

    def defs(self):
        if self.kind in HAS_DEST:
            return self.dest
        return None

    def emit(self):
        if self.dead:
            return None
        k = self.kind
        if k == ASSIGN_CONST: return f"    {self.dest} = {self.args[0]}"
        if k == ASSIGN_COPY:  return f"    {self.dest} = {self.args[0]}"
        if k == BINOP:        return f"    {self.dest} = {self.args[0]} {self.op} {self.args[1]}"
        if k == UNOP:         return f"    {self.dest} = {self.op} {self.args[0]}"
        if k == CALL:
            a = ", ".join(str(x) for x in self.args)
            return f"    {self.dest} = CALL {self.fname}({a})"
        if k == PRINT:  return f"    PRINT {self.args[0]}"
        if k == IF:     return f"    IF {self.args[0]} GOTO {self.true_lbl} ELSE GOTO {self.false_lbl}"
        if k == GOTO:   return f"    GOTO {self.target}"
        if k == RETURN: return f"    RETURN {self.args[0]}"
        if k == NOP:    return None
        return None


class Block:
    __slots__ = ('label', 'instrs', 'succs', 'preds')
    def __init__(self, label):
        self.label = label
        self.instrs = []
        self.succs = []
        self.preds = []


class Func:
    __slots__ = ('name', 'params', 'blocks')
    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.blocks = OrderedDict()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_RE_FUNC   = re.compile(r'FUNC\s+(\w+)\s*\((.*?)\)\s*:')
_RE_LABEL  = re.compile(r'^(\w+)\s*:\s*$')
_RE_RET    = re.compile(r'RETURN\s+(.+)$')
_RE_PRINT  = re.compile(r'PRINT\s+(.+)$')
_RE_IF     = re.compile(r'IF\s+(\S+)\s+GOTO\s+(\w+)\s+ELSE\s+GOTO\s+(\w+)$')
_RE_GOTO   = re.compile(r'GOTO\s+(\w+)$')
_RE_CALL   = re.compile(r'(\w+)\s*=\s*CALL\s+(\w+)\s*\((.*?)\)$')
_RE_UNOP   = re.compile(r'(\w+)\s*=\s*(-|!)\s*(\w+)\s*$')
_RE_BINOP  = re.compile(
    r'(\w+)\s*=\s*(\w+)\s*([\+\-\*/%]|==|!=|<=|>=|<|>|&&|\|\|)\s*(\w+)\s*$')
_RE_ASSIGN = re.compile(r'(\w+)\s*=\s*(.+)$')


def parse_instr(line):
    line = line.strip()
    if not line or line.startswith('#') or line == 'NOP':
        return None if (not line or line.startswith('#')) else Instr(NOP)

    m = _RE_RET.match(line)
    if m: return Instr(RETURN, args=[m.group(1).strip()])

    m = _RE_PRINT.match(line)
    if m: return Instr(PRINT, args=[m.group(1).strip()])

    m = _RE_IF.match(line)
    if m: return Instr(IF, args=[m.group(1)], true_lbl=m.group(2), false_lbl=m.group(3))

    m = _RE_GOTO.match(line)
    if m: return Instr(GOTO, target=m.group(1))

    m = _RE_CALL.match(line)
    if m:
        a = m.group(3).strip()
        args = [x.strip() for x in a.split(',') if x.strip()] if a else []
        return Instr(CALL, dest=m.group(1), fname=m.group(2), args=args)

    m = _RE_UNOP.match(line)
    if m: return Instr(UNOP, dest=m.group(1), op=m.group(2), args=[m.group(3)])

    m = _RE_BINOP.match(line)
    if m: return Instr(BINOP, dest=m.group(1), op=m.group(3),
                       args=[m.group(2), m.group(4)])

    m = _RE_ASSIGN.match(line)
    if m:
        val = m.group(2).strip()
        if is_literal(val):
            return Instr(ASSIGN_CONST, dest=m.group(1), args=[val])
        else:
            return Instr(ASSIGN_COPY, dest=m.group(1), args=[val])
    return None


def parse_program(text):
    funcs = []
    lines = text.strip().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1; continue
        m = _RE_FUNC.match(line)
        if m:
            fn = Func(m.group(1),
                      [p.strip() for p in m.group(2).split(',') if p.strip()])
            i += 1
            cur_lbl = None
            cur_blk = None
            while i < len(lines) and lines[i].strip() != 'END':
                fl = lines[i].strip()
                if not fl or fl.startswith('#'):
                    i += 1; continue
                lm = _RE_LABEL.match(fl)
                if lm:
                    cur_lbl = lm.group(1)
                    cur_blk = Block(cur_lbl)
                    fn.blocks[cur_lbl] = cur_blk
                else:
                    ins = parse_instr(fl)
                    if ins and cur_blk is not None:
                        cur_blk.instrs.append(ins)
                i += 1
            funcs.append(fn)
            i += 1
        else:
            i += 1
    return funcs


# ---------------------------------------------------------------------------
# CFG construction
# ---------------------------------------------------------------------------

def build_cfg(fn):
    labels = list(fn.blocks.keys())
    for b in fn.blocks.values():
        b.succs = []
        b.preds = []
    for idx, lbl in enumerate(labels):
        blk = fn.blocks[lbl]
        if not blk.instrs:
            if idx + 1 < len(labels):
                blk.succs.append(labels[idx + 1])
            continue
        last = blk.instrs[-1]
        if last.kind == GOTO:
            blk.succs.append(last.target)
        elif last.kind == IF:
            blk.succs.append(last.true_lbl)
            if last.false_lbl != last.true_lbl:
                blk.succs.append(last.false_lbl)
        elif last.kind == RETURN:
            pass
        else:
            if idx + 1 < len(labels):
                blk.succs.append(labels[idx + 1])
    for lbl in labels:
        for s in fn.blocks[lbl].succs:
            if s in fn.blocks:
                fn.blocks[s].preds.append(lbl)


# ---------------------------------------------------------------------------
# Constant propagation + folding
# ---------------------------------------------------------------------------

def constant_propagation(fn):
    changed = False
    all_defs = defaultdict(list)
    for blk in fn.blocks.values():
        for ins in blk.instrs:
            if ins.dead:
                continue
            d = ins.defs()
            if d:
                all_defs[d].append(ins)

    non_const = set(fn.params)
    constants = {}

    for _ in range(100):
        old = dict(constants)
        for var, defs in all_defs.items():
            if var in non_const:
                continue
            vals = set()
            ok = True
            for ins in defs:
                if ins.dead:
                    continue
                if ins.kind == ASSIGN_CONST:
                    vals.add(lit_val(ins.args[0]))
                elif ins.kind == ASSIGN_COPY:
                    a = ins.args[0]
                    if is_literal(a):
                        vals.add(lit_val(a))
                    elif a in constants:
                        vals.add(constants[a])
                    else:
                        ok = False; break
                elif ins.kind == BINOP:
                    a1, a2 = ins.args
                    v1 = lit_val(a1) if is_literal(a1) else constants.get(a1)
                    v2 = lit_val(a2) if is_literal(a2) else constants.get(a2)
                    if v1 is not None and v2 is not None:
                        r = eval_binop(v1, ins.op, v2)
                        if r is not None:
                            vals.add(r)
                        else:
                            ok = False; break
                    else:
                        ok = False; break
                elif ins.kind == UNOP:
                    a = ins.args[0]
                    v = lit_val(a) if is_literal(a) else constants.get(a)
                    if v is not None:
                        r = eval_unop(ins.op, v)
                        if r is not None:
                            vals.add(r)
                        else:
                            ok = False; break
                    else:
                        ok = False; break
                else:
                    ok = False; break
            if ok and len(vals) == 1:
                constants[var] = next(iter(vals))
            elif not ok or len(vals) > 1:
                non_const.add(var)
                constants.pop(var, None)
        if constants == old:
            break

    for blk in fn.blocks.values():
        for ins in blk.instrs:
            if ins.dead:
                continue
            new_args = []
            for a in ins.args:
                if not is_literal(a) and a in constants:
                    new_args.append(str(constants[a]))
                    changed = True
                else:
                    new_args.append(a)
            ins.args = new_args
            if ins.kind == BINOP and is_literal(ins.args[0]) and is_literal(ins.args[1]):
                r = eval_binop(lit_val(ins.args[0]), ins.op, lit_val(ins.args[1]))
                if r is not None:
                    ins.kind = ASSIGN_CONST
                    ins.args = [str(r)]
                    ins.op = None
                    changed = True
            elif ins.kind == UNOP and is_literal(ins.args[0]):
                r = eval_unop(ins.op, lit_val(ins.args[0]))
                if r is not None:
                    ins.kind = ASSIGN_CONST
                    ins.args = [str(r)]
                    ins.op = None
                    changed = True
            elif ins.kind == ASSIGN_COPY and is_literal(ins.args[0]):
                ins.kind = ASSIGN_CONST
                changed = True
            if ins.kind == IF and is_literal(ins.args[0]):
                v = lit_val(ins.args[0])
                ins.kind = GOTO
                ins.target = ins.true_lbl if v else ins.false_lbl
                ins.args = []
                changed = True
    return changed


# ---------------------------------------------------------------------------
# Liveness analysis + dead-code elimination
# ---------------------------------------------------------------------------

def liveness(fn):
    labels = list(fn.blocks.keys())
    use_s, def_s = {}, {}
    for lbl, blk in fn.blocks.items():
        u, d = set(), set()
        for ins in blk.instrs:
            if ins.dead:
                continue
            for v in ins.uses():
                if v not in d:
                    u.add(v)
            dd = ins.defs()
            if dd:
                d.add(dd)
        use_s[lbl] = u
        def_s[lbl] = d
    li = {l: set() for l in labels}
    lo = {l: set() for l in labels}
    for _ in range(200):
        old_li = {k: set(v) for k, v in li.items()}
        for lbl in reversed(labels):
            blk = fn.blocks[lbl]
            new_lo = set()
            for s in blk.succs:
                if s in li:
                    new_lo |= li[s]
            lo[lbl] = new_lo
            li[lbl] = use_s[lbl] | (lo[lbl] - def_s[lbl])
        if li == old_li:
            break
    return li, lo


def dead_code_elim(fn):
    changed = False
    _, lo = liveness(fn)
    for lbl, blk in fn.blocks.items():
        live = set(lo[lbl])
        for i in range(len(blk.instrs) - 1, -1, -1):
            ins = blk.instrs[i]
            if ins.dead:
                continue
            d = ins.defs()
            if d and d not in live and ins.kind != CALL:
                ins.dead = True
                changed = True
            else:
                if d:
                    live.discard(d)
                live |= ins.uses()
    return changed


# ---------------------------------------------------------------------------
# Common sub-expression elimination (local)
# ---------------------------------------------------------------------------

def cse(fn):
    changed = False
    for blk in fn.blocks.values():
        avail = {}
        for ins in blk.instrs:
            if ins.dead:
                continue
            if ins.kind == BINOP:
                key = (ins.op, ins.args[0], ins.args[1])
                comm = None
                if ins.op in ('+', '*', '==', '!=', '&&', '||'):
                    comm = (ins.op, ins.args[1], ins.args[0])
                if key in avail:
                    ins.kind = ASSIGN_COPY
                    ins.args = [avail[key]]
                    ins.op = None
                    changed = True
                elif comm and comm in avail:
                    ins.kind = ASSIGN_COPY
                    ins.args = [avail[comm]]
                    ins.op = None
                    changed = True
                else:
                    avail[key] = ins.dest
            elif ins.kind == UNOP:
                key = (ins.op, ins.args[0])
                if key in avail:
                    ins.kind = ASSIGN_COPY
                    ins.args = [avail[key]]
                    ins.op = None
                    changed = True
                else:
                    avail[key] = ins.dest

            d = ins.defs()
            if d:
                rm = [k for k, v in avail.items() if d in k or v == d]
                for k in rm:
                    del avail[k]
                if ins.kind == BINOP:
                    avail[(ins.op, ins.args[0], ins.args[1])] = ins.dest
                elif ins.kind == UNOP:
                    avail[(ins.op, ins.args[0])] = ins.dest
    return changed


# ---------------------------------------------------------------------------
# Copy propagation (local)
# ---------------------------------------------------------------------------

def copy_prop(fn):
    changed = False
    for blk in fn.blocks.values():
        copies = {}
        for ins in blk.instrs:
            if ins.dead:
                continue
            new_args = []
            for a in ins.args:
                if not is_literal(a):
                    resolved = a
                    seen = set()
                    while resolved in copies and resolved not in seen:
                        seen.add(resolved)
                        resolved = copies[resolved]
                    if resolved != a:
                        new_args.append(resolved)
                        changed = True
                    else:
                        new_args.append(a)
                else:
                    new_args.append(a)
            ins.args = new_args
            d = ins.defs()
            if d:
                copies = {k: v for k, v in copies.items() if v != d}
                copies.pop(d, None)
                if ins.kind == ASSIGN_COPY and not is_literal(ins.args[0]):
                    copies[d] = ins.args[0]
    return changed


# ---------------------------------------------------------------------------
# Unreachable code elimination
# ---------------------------------------------------------------------------

def unreach_elim(fn):
    if not fn.blocks:
        return False
    entry = next(iter(fn.blocks))
    reachable = set()
    wl = [entry]
    while wl:
        l = wl.pop()
        if l in reachable:
            continue
        reachable.add(l)
        for s in fn.blocks[l].succs:
            if s in fn.blocks and s not in reachable:
                wl.append(s)
    removed = [l for l in fn.blocks if l not in reachable]
    if removed:
        for l in removed:
            del fn.blocks[l]
        return True
    return False


# ---------------------------------------------------------------------------
# Top-level optimiser
# ---------------------------------------------------------------------------

def optimize(fn):
    build_cfg(fn)
    for _ in range(50):
        c1 = constant_propagation(fn)
        build_cfg(fn)
        c2 = unreach_elim(fn)
        if c2:
            build_cfg(fn)
        c3 = copy_prop(fn)
        c4 = cse(fn)
        c5 = dead_code_elim(fn)
        if not any([c1, c2, c3, c4, c5]):
            break


def emit(funcs):
    parts = []
    for fn in funcs:
        ps = ", ".join(fn.params)
        parts.append(f"FUNC {fn.name}({ps}):")
        for lbl, blk in fn.blocks.items():
            parts.append(f"  {lbl}:")
            for ins in blk.instrs:
                s = ins.emit()
                if s:
                    parts.append(s)
        parts.append("END")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Graphviz DOT CFG generation
# ---------------------------------------------------------------------------

def generate_dot(funcs, basename):
    """Generate Graphviz DOT file for the optimized CFG."""
    os.makedirs('/app/cfg_output', exist_ok=True)
    dot_path = f'/app/cfg_output/{basename}.dot'
    lines = ['digraph CFG {']
    lines.append('  rankdir=TB;')
    lines.append('  node [shape=box, fontname="Courier"];')
    for fn in funcs:
        lines.append(f'  subgraph cluster_{fn.name} {{')
        lines.append(f'    label="{fn.name}";')
        lines.append('    style=dashed;')
        for lbl, blk in fn.blocks.items():
            n = sum(1 for i in blk.instrs
                    if not i.dead and i.emit() is not None)
            nid = f'{fn.name}_{lbl}'
            lines.append(
                f'    "{nid}" [label="{lbl}\\n({n} instrs)"];'
            )
        for lbl, blk in fn.blocks.items():
            nid = f'{fn.name}_{lbl}'
            for s in blk.succs:
                if s in fn.blocks:
                    sid = f'{fn.name}_{s}'
                    lines.append(f'    "{nid}" -> "{sid}";')
        lines.append('  }')
    lines.append('}')
    with open(dot_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


# ---------------------------------------------------------------------------
# LLVM IR generation
# ---------------------------------------------------------------------------

def generate_llvm_ir(funcs, basename):
    """Generate LLVM IR translation of optimized TAC."""
    os.makedirs('/app/llvm_output', exist_ok=True)
    ll_path = f'/app/llvm_output/{basename}.ll'

    out = []
    out.append(f'; ModuleID = \'{basename}\'')
    out.append('')
    out.append('@.fmt = private unnamed_addr constant [5 x i8] c"%ld\\0A\\00"')
    out.append('declare i32 @printf(ptr, ...)')
    out.append('')

    for fn in funcs:
        # Collect all variables used in this function
        all_vars = set(fn.params)
        for blk in fn.blocks.values():
            for ins in blk.instrs:
                if ins.dead:
                    continue
                d = ins.defs()
                if d:
                    all_vars.add(d)
                for u in ins.uses():
                    all_vars.add(u)

        # Function signature — all params and returns are i64
        param_str = ', '.join(f'i64 %p.{p}' for p in fn.params)
        out.append(f'define i64 @{fn.name}({param_str}) {{')

        # Alloca entry block: allocate stack space for all variables
        out.append('alloca_entry:')
        for v in sorted(all_vars):
            out.append(f'  %v.{v} = alloca i64')
        for p in fn.params:
            out.append(f'  store i64 %p.{p}, ptr %v.{p}')
        first_label = list(fn.blocks.keys())[0]
        out.append(f'  br label %{first_label}')
        out.append('')

        # Emit each basic block
        block_labels = list(fn.blocks.keys())
        tc = [0]

        def nt():
            tc[0] += 1
            return f'%t.{tc[0]}'

        def load_val(a):
            """Load a TAC operand: literal → immediate, variable → load."""
            if is_literal(a):
                return str(lit_val(a))
            t = nt()
            out.append(f'  {t} = load i64, ptr %v.{a}')
            return t

        for idx, lbl in enumerate(block_labels):
            blk = fn.blocks[lbl]
            out.append(f'{lbl}:')
            has_term = False

            for ins in blk.instrs:
                if ins.dead or ins.kind == NOP:
                    continue

                if ins.kind == ASSIGN_CONST:
                    out.append(f'  store i64 {lit_val(ins.args[0])}, ptr %v.{ins.dest}')

                elif ins.kind == ASSIGN_COPY:
                    v = load_val(ins.args[0])
                    out.append(f'  store i64 {v}, ptr %v.{ins.dest}')

                elif ins.kind == BINOP:
                    v1 = load_val(ins.args[0])
                    v2 = load_val(ins.args[1])
                    r = nt()
                    op = ins.op
                    if op == '+':
                        out.append(f'  {r} = add i64 {v1}, {v2}')
                    elif op == '-':
                        out.append(f'  {r} = sub i64 {v1}, {v2}')
                    elif op == '*':
                        out.append(f'  {r} = mul i64 {v1}, {v2}')
                    elif op == '/':
                        out.append(f'  {r} = sdiv i64 {v1}, {v2}')
                    elif op == '%':
                        out.append(f'  {r} = srem i64 {v1}, {v2}')
                    elif op in ('==', '!=', '<', '>', '<=', '>='):
                        cmp_map = {
                            '==': 'eq', '!=': 'ne',
                            '<': 'slt', '>': 'sgt',
                            '<=': 'sle', '>=': 'sge',
                        }
                        cr = nt()
                        out.append(f'  {cr} = icmp {cmp_map[op]} i64 {v1}, {v2}')
                        out.append(f'  {r} = zext i1 {cr} to i64')
                    elif op == '&&':
                        c1 = nt()
                        c2 = nt()
                        a = nt()
                        out.append(f'  {c1} = icmp ne i64 {v1}, 0')
                        out.append(f'  {c2} = icmp ne i64 {v2}, 0')
                        out.append(f'  {a} = and i1 {c1}, {c2}')
                        out.append(f'  {r} = zext i1 {a} to i64')
                    elif op == '||':
                        c1 = nt()
                        c2 = nt()
                        o = nt()
                        out.append(f'  {c1} = icmp ne i64 {v1}, 0')
                        out.append(f'  {c2} = icmp ne i64 {v2}, 0')
                        out.append(f'  {o} = or i1 {c1}, {c2}')
                        out.append(f'  {r} = zext i1 {o} to i64')
                    out.append(f'  store i64 {r}, ptr %v.{ins.dest}')

                elif ins.kind == UNOP:
                    v = load_val(ins.args[0])
                    r = nt()
                    if ins.op == '-':
                        out.append(f'  {r} = sub i64 0, {v}')
                    elif ins.op == '!':
                        c = nt()
                        out.append(f'  {c} = icmp eq i64 {v}, 0')
                        out.append(f'  {r} = zext i1 {c} to i64')
                    out.append(f'  store i64 {r}, ptr %v.{ins.dest}')

                elif ins.kind == CALL:
                    arg_vals = [load_val(a) for a in ins.args]
                    args_str = ', '.join(f'i64 {v}' for v in arg_vals)
                    r = nt()
                    out.append(f'  {r} = call i64 @{ins.fname}({args_str})')
                    out.append(f'  store i64 {r}, ptr %v.{ins.dest}')

                elif ins.kind == PRINT:
                    v = load_val(ins.args[0])
                    r = nt()
                    out.append(f'  {r} = call i32 (ptr, ...) @printf(ptr @.fmt, i64 {v})')

                elif ins.kind == IF:
                    v = load_val(ins.args[0])
                    c = nt()
                    out.append(f'  {c} = icmp ne i64 {v}, 0')
                    out.append(f'  br i1 {c}, label %{ins.true_lbl}, label %{ins.false_lbl}')
                    has_term = True

                elif ins.kind == GOTO:
                    out.append(f'  br label %{ins.target}')
                    has_term = True

                elif ins.kind == RETURN:
                    v = load_val(ins.args[0])
                    out.append(f'  ret i64 {v}')
                    has_term = True

            # Every LLVM basic block must end with a terminator
            if not has_term:
                if idx + 1 < len(block_labels):
                    out.append(f'  br label %{block_labels[idx + 1]}')
                else:
                    out.append('  ret i64 0')
            out.append('')

        out.append('}')
        out.append('')

    with open(ll_path, 'w') as f:
        f.write('\n'.join(out))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 optimizer.py <file.tac>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        text = f.read()
    funcs = parse_program(text)
    for fn in funcs:
        optimize(fn)

    basename = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    for fn in funcs:
        build_cfg(fn)

    generate_dot(funcs, basename)
    generate_llvm_ir(funcs, basename)
    print(emit(funcs))


if __name__ == '__main__':
    main()
