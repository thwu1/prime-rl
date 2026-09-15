#!/usr/bin/env python3
"""Three-Address Code IR Optimizer.

Implements global constant propagation (forward iterative fixed-point),
local common subexpression elimination, and dead code elimination via
backward liveness analysis. Iterates all passes until convergence.

"""

import sys
import re

# ---------------------------------------------------------------------------
# Instruction types
# ---------------------------------------------------------------------------
ASSIGN = 'assign'
BINOP = 'binop'
CALL = 'call'
IF_GOTO = 'if_goto'
GOTO = 'goto'
RETURN = 'return'
PRINT = 'print'

# Lattice elements for constant propagation
TOP = object()   # not yet determined
BOT = object()   # known non-constant


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
class Instruction:
    __slots__ = ('type', 'dest', 'op1', 'operator', 'op2',
                 'label', 'func_name', 'args')

    def __init__(self, itype, dest=None, op1=None, operator=None, op2=None,
                 label=None, func_name=None, args=None):
        self.type = itype
        self.dest = dest
        self.op1 = op1
        self.operator = operator
        self.op2 = op2
        self.label = label
        self.func_name = func_name
        self.args = args

    def used_vars(self):
        r = set()
        if self.type == ASSIGN:
            if self.op1 and not _isc(self.op1): r.add(self.op1)
        elif self.type == BINOP:
            if self.op1 and not _isc(self.op1): r.add(self.op1)
            if self.op2 and not _isc(self.op2): r.add(self.op2)
        elif self.type == CALL:
            for a in (self.args or []):
                if not _isc(a): r.add(a)
        elif self.type in (IF_GOTO, RETURN, PRINT):
            if self.op1 and not _isc(self.op1): r.add(self.op1)
        return r

    def defined_var(self):
        return self.dest if self.type in (ASSIGN, BINOP, CALL) else None

    def has_side_effect(self):
        return self.type in (CALL, PRINT, RETURN, IF_GOTO, GOTO)

    def to_ir(self):
        if self.type == ASSIGN:
            return f"    {self.dest} = {self.op1}"
        if self.type == BINOP:
            return f"    {self.dest} = {self.op1} {self.operator} {self.op2}"
        if self.type == CALL:
            a = ", ".join(self.args) if self.args else ""
            return f"    {self.dest} = CALL {self.func_name}({a})"
        if self.type == IF_GOTO:
            return f"    IF {self.op1} GOTO {self.label}"
        if self.type == GOTO:
            return f"    GOTO {self.label}"
        if self.type == RETURN:
            return f"    RETURN {self.op1}"
        if self.type == PRINT:
            return f"    PRINT {self.op1}"
        return ""


class BasicBlock:
    def __init__(self, label):
        self.label = label
        self.instructions = []
        self.succs = []
        self.preds = []


class Function:
    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.blocks = {}
        self.block_order = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _isc(op):
    """Is operand a constant (integer literal string)?"""
    try:
        int(str(op))
        return True
    except (ValueError, TypeError):
        return False


def _cv(op):
    """Constant value of an operand."""
    return int(str(op))


def _eb(l, op, r):
    """Evaluate a binary operation on two ints."""
    if op == '+': return l + r
    if op == '-': return l - r
    if op == '*': return l * r
    if op == '/':
        if r == 0: return 0
        v = abs(l) // abs(r)
        return -v if (l < 0) != (r < 0) else v
    if op == '%':
        if r == 0: return 0
        v = abs(l) % abs(r)
        return -v if l < 0 else v
    if op == '==': return 1 if l == r else 0
    if op == '!=': return 1 if l != r else 0
    if op == '<': return 1 if l < r else 0
    if op == '>': return 1 if l > r else 0
    if op == '<=': return 1 if l <= r else 0
    if op == '>=': return 1 if l >= r else 0
    return 0


def _resolve(op, env):
    """Resolve an operand to its lattice value."""
    if _isc(op):
        return _cv(op)
    return env.get(op, TOP)


def _get_const(var, env):
    """Return integer constant for var, or None."""
    if _isc(var):
        return _cv(var)
    v = env.get(var, TOP)
    return v if isinstance(v, int) else None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_RF = re.compile(r'FUNC\s+(\w+)\s*\(([^)]*)\)\s*:')
_RL = re.compile(r'LABEL\s+(\w+)\s*:')
_RR = re.compile(r'RETURN\s+(.+)')
_RP = re.compile(r'PRINT\s+(.+)')
_RI = re.compile(r'IF\s+(.+?)\s+GOTO\s+(\w+)')
_RG = re.compile(r'GOTO\s+(\w+)')
_RC = re.compile(r'(\w+)\s*=\s*CALL\s+(\w+)\s*\(([^)]*)\)')
_RB = re.compile(r'(\w+)\s*=\s*(.+?)\s+(==|!=|<=|>=|<|>|[+\-*/%])\s+(.+)')
_RA = re.compile(r'(\w+)\s*=\s*(.+)')


def _parse_inst(line):
    s = line.strip()
    m = _RR.match(s)
    if m: return Instruction(RETURN, op1=m.group(1).strip())
    m = _RP.match(s)
    if m: return Instruction(PRINT, op1=m.group(1).strip())
    m = _RI.match(s)
    if m: return Instruction(IF_GOTO, op1=m.group(1).strip(), label=m.group(2))
    m = _RG.match(s)
    if m: return Instruction(GOTO, label=m.group(1))
    m = _RC.match(s)
    if m:
        args = [a.strip() for a in m.group(3).split(',') if a.strip()]
        return Instruction(CALL, dest=m.group(1), func_name=m.group(2), args=args)
    m = _RB.match(s)
    if m:
        return Instruction(BINOP, dest=m.group(1), op1=m.group(2).strip(),
                           operator=m.group(3), op2=m.group(4).strip())
    m = _RA.match(s)
    if m: return Instruction(ASSIGN, dest=m.group(1), op1=m.group(2).strip())
    return None


def parse_program(source):
    funcs = {}
    order = []
    cf = None
    cl = None
    for line in source.split('\n'):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        m = _RF.match(s)
        if m:
            name = m.group(1)
            params = [p.strip() for p in m.group(2).split(',') if p.strip()]
            cf = Function(name, params)
            funcs[name] = cf
            order.append(name)
            cl = None
            continue
        if s == 'ENDFUNC':
            cf = None
            cl = None
            continue
        m = _RL.match(s)
        if m:
            cl = m.group(1)
            blk = BasicBlock(cl)
            cf.blocks[cl] = blk
            cf.block_order.append(cl)
            continue
        if cf and cl:
            inst = _parse_inst(s)
            if inst:
                cf.blocks[cl].instructions.append(inst)
    return funcs, order


# ---------------------------------------------------------------------------
# CFG
# ---------------------------------------------------------------------------
def build_cfg(func):
    for lbl in func.block_order:
        func.blocks[lbl].succs = []
        func.blocks[lbl].preds = []
    for idx, lbl in enumerate(func.block_order):
        blk = func.blocks[lbl]
        has_term = False
        for inst in blk.instructions:
            if inst.type == GOTO:
                if inst.label in func.blocks and inst.label not in blk.succs:
                    blk.succs.append(inst.label)
                has_term = True
            elif inst.type == IF_GOTO:
                if inst.label in func.blocks and inst.label not in blk.succs:
                    blk.succs.append(inst.label)
                if idx + 1 < len(func.block_order):
                    ft = func.block_order[idx + 1]
                    if ft not in blk.succs:
                        blk.succs.append(ft)
                has_term = True
            elif inst.type == RETURN:
                has_term = True
        if not has_term and idx + 1 < len(func.block_order):
            ft = func.block_order[idx + 1]
            if ft not in blk.succs:
                blk.succs.append(ft)
    for lbl in func.block_order:
        for s in func.blocks[lbl].succs:
            if s in func.blocks and lbl not in func.blocks[s].preds:
                func.blocks[s].preds.append(lbl)


# ---------------------------------------------------------------------------
# Constant Propagation  (forward, iterative, two-phase)
# ---------------------------------------------------------------------------
def _meet(a, b):
    if a is TOP: return b
    if b is TOP: return a
    if a is BOT or b is BOT: return BOT
    return a if a == b else BOT


def _merge(envs):
    valid = [e for e in envs if e is not None]
    if not valid:
        return {}
    keys = set()
    for e in valid:
        keys |= set(e.keys())
    r = {}
    for k in keys:
        m = TOP
        for e in valid:
            m = _meet(m, e.get(k, TOP))
        if m is not TOP:
            r[k] = m
    return r


def _sim_block(block, in_env):
    """Simulate transfer function (read-only on instructions)."""
    env = dict(in_env)
    for inst in block.instructions:
        if inst.type == ASSIGN:
            env[inst.dest] = _resolve(inst.op1, env)
        elif inst.type == BINOP:
            v1 = _resolve(inst.op1, env)
            v2 = _resolve(inst.op2, env)
            if isinstance(v1, int) and isinstance(v2, int):
                env[inst.dest] = _eb(v1, inst.operator, v2)
            elif v1 is BOT or v2 is BOT:
                env[inst.dest] = BOT
            else:
                env[inst.dest] = TOP
        elif inst.type == CALL:
            env[inst.dest] = BOT
    return env


def const_prop(func):
    build_cfg(func)
    if not func.block_order:
        return False
    entry = func.block_order[0]
    entry_env = {p: BOT for p in func.params}

    out = {lbl: None for lbl in func.block_order}
    ins = {}

    # Phase 1: fixed-point computation
    for _ in range(50):
        changed = False
        for lbl in func.block_order:
            blk = func.blocks[lbl]
            if lbl == entry:
                if blk.preds:
                    pred_outs = [out[p] for p in blk.preds]
                    m = _merge(pred_outs)
                    all_k = set(entry_env) | set(m)
                    new_in = {}
                    for k in all_k:
                        v = _meet(entry_env.get(k, TOP), m.get(k, TOP))
                        if v is not TOP:
                            new_in[k] = v
                else:
                    new_in = dict(entry_env)
            else:
                if blk.preds:
                    new_in = _merge([out[p] for p in blk.preds])
                else:
                    new_in = {}
            ins[lbl] = new_in
            new_out = _sim_block(blk, new_in)
            if new_out != out[lbl]:
                changed = True
                out[lbl] = new_out
        if not changed:
            break

    # Phase 2: apply substitutions/folding
    any_changed = False
    for lbl in func.block_order:
        blk = func.blocks[lbl]
        env = dict(ins[lbl])
        for inst in blk.instructions:
            if inst.type == BINOP:
                c1 = _get_const(inst.op1, env)
                if c1 is not None and not _isc(inst.op1):
                    inst.op1 = str(c1)
                    any_changed = True
                c2 = _get_const(inst.op2, env)
                if c2 is not None and not _isc(inst.op2):
                    inst.op2 = str(c2)
                    any_changed = True
                if _isc(inst.op1) and _isc(inst.op2):
                    result = _eb(_cv(inst.op1), inst.operator, _cv(inst.op2))
                    inst.type = ASSIGN
                    inst.op1 = str(result)
                    inst.operator = None
                    inst.op2 = None
                    env[inst.dest] = result
                    any_changed = True
                else:
                    v1 = _resolve(inst.op1, env)
                    v2 = _resolve(inst.op2, env)
                    if isinstance(v1, int) and isinstance(v2, int):
                        env[inst.dest] = _eb(v1, inst.operator, v2)
                    elif v1 is BOT or v2 is BOT:
                        env[inst.dest] = BOT
                    else:
                        env[inst.dest] = TOP

            elif inst.type == ASSIGN:
                c = _get_const(inst.op1, env)
                if c is not None and not _isc(inst.op1):
                    inst.op1 = str(c)
                    any_changed = True
                env[inst.dest] = _resolve(inst.op1, env)

            elif inst.type == CALL:
                if inst.args:
                    na = []
                    for a in inst.args:
                        c = _get_const(a, env)
                        if c is not None and not _isc(a):
                            na.append(str(c))
                            any_changed = True
                        else:
                            na.append(a)
                    inst.args = na
                env[inst.dest] = BOT

            elif inst.type in (IF_GOTO, RETURN, PRINT):
                c = _get_const(inst.op1, env)
                if c is not None and not _isc(inst.op1):
                    inst.op1 = str(c)
                    any_changed = True

    return any_changed


# ---------------------------------------------------------------------------
# Common Subexpression Elimination (local, per block)
# ---------------------------------------------------------------------------
def local_cse(func):
    any_changed = False
    for lbl in func.block_order:
        blk = func.blocks[lbl]
        avail = {}
        for inst in blk.instructions:
            if inst.type == BINOP:
                key = (inst.op1, inst.operator, inst.op2)
                if key in avail and avail[key] != inst.dest:
                    inst.type = ASSIGN
                    inst.op1 = avail[key]
                    inst.operator = None
                    inst.op2 = None
                    any_changed = True
                d = inst.dest if inst.type in (ASSIGN, BINOP, CALL) else None
                if d:
                    avail = {k: v for k, v in avail.items()
                             if d not in (k[0], k[2]) and v != d}
                if inst.type == BINOP:
                    avail[(inst.op1, inst.operator, inst.op2)] = inst.dest
            elif inst.type in (ASSIGN, CALL):
                if inst.dest:
                    avail = {k: v for k, v in avail.items()
                             if inst.dest not in (k[0], k[2]) and v != inst.dest}
    return any_changed


# ---------------------------------------------------------------------------
# Dead Code Elimination (backward liveness analysis)
# ---------------------------------------------------------------------------
def dce_pass(func):
    build_cfg(func)
    if not func.block_order:
        return False

    ud = {}
    for lbl in func.block_order:
        use, deff = set(), set()
        for inst in func.blocks[lbl].instructions:
            for v in inst.used_vars():
                if v not in deff:
                    use.add(v)
            d = inst.defined_var()
            if d:
                deff.add(d)
        ud[lbl] = (use, deff)

    li = {lbl: set() for lbl in func.block_order}
    lo = {lbl: set() for lbl in func.block_order}

    for _ in range(50):
        changed = False
        for lbl in reversed(func.block_order):
            blk = func.blocks[lbl]
            new_out = set()
            for s in blk.succs:
                if s in li:
                    new_out |= li[s]
            use, deff = ud[lbl]
            new_in = use | (new_out - deff)
            if new_in != li[lbl] or new_out != lo[lbl]:
                changed = True
                li[lbl] = new_in
                lo[lbl] = new_out
        if not changed:
            break

    any_changed = False
    for lbl in func.block_order:
        blk = func.blocks[lbl]
        live = set(lo[lbl])
        kept = []
        for inst in reversed(blk.instructions):
            d = inst.defined_var()
            if d and d not in live and not inst.has_side_effect():
                any_changed = True
                continue
            kept.append(inst)
            if d:
                live.discard(d)
            for v in inst.used_vars():
                live.add(v)
        kept.reverse()
        blk.instructions = kept

    return any_changed


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------
def emit(funcs, order):
    lines = []
    for fn in order:
        f = funcs[fn]
        p = ", ".join(f.params)
        lines.append(f"FUNC {f.name}({p}):")
        for lbl in f.block_order:
            lines.append(f"  LABEL {lbl}:")
            for inst in f.blocks[lbl].instructions:
                lines.append(inst.to_ir())
        lines.append("ENDFUNC")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def optimize(funcs, order):
    for _ in range(20):
        changed = False
        for fn in order:
            f = funcs[fn]
            changed |= const_prop(f)
            changed |= local_cse(f)
            changed |= dce_pass(f)
        if not changed:
            break


def main():
    if len(sys.argv) < 2:
        print("Usage: optimizer.py <file.ir>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    funcs, order = parse_program(source)
    optimize(funcs, order)
    print(emit(funcs, order))


if __name__ == '__main__':
    main()
