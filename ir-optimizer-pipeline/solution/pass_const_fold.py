"""Constant folding and propagation pass."""
from collections import defaultdict
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)

PURE_OPS = frozenset({
    '+', '-', '*', '/', '%',
    '==', '!=', '<', '<=', '>', '>=',
    'unary_-', 'not',
})


def _get_written_var(insn):
    if isinstance(insn, (LoadIntConst, LoadBoolConst, Copy, Call)):
        return insn.dest
    return None


def _def_counts(instructions):
    counts = defaultdict(int)
    for insn in instructions:
        v = _get_written_var(insn)
        if v is not None:
            counts[v.name] += 1
    return counts


def _eval_op(name, args):
    try:
        if name == '+':   return args[0] + args[1]
        if name == '-':   return args[0] - args[1]
        if name == '*':   return args[0] * args[1]
        if name == '/':
            if args[1] == 0: return None
            q = abs(args[0]) // abs(args[1])
            if (args[0] < 0) != (args[1] < 0): q = -q
            return q
        if name == '%':
            if args[1] == 0: return None
            r = abs(args[0]) % abs(args[1])
            if args[0] < 0: r = -r
            return r
        if name == '==':  return args[0] == args[1]
        if name == '!=':  return args[0] != args[1]
        if name == '<':   return args[0] < args[1]
        if name == '<=':  return args[0] <= args[1]
        if name == '>':   return args[0] > args[1]
        if name == '>=':  return args[0] >= args[1]
        if name == 'unary_-': return -args[0]
        if name == 'not': return not args[0]
    except Exception:
        return None
    return None


def _make_const(value, dest):
    if isinstance(value, bool):
        return LoadBoolConst(value, dest)
    return LoadIntConst(value, dest)


def run(instructions):
    defs = _def_counts(instructions)
    constants = {}
    changed = True
    while changed:
        changed = False
        for insn in instructions:
            if isinstance(insn, LoadIntConst):
                if defs[insn.dest.name] == 1 and insn.dest.name not in constants:
                    constants[insn.dest.name] = insn.value
                    changed = True
            elif isinstance(insn, LoadBoolConst):
                if defs[insn.dest.name] == 1 and insn.dest.name not in constants:
                    constants[insn.dest.name] = insn.value
                    changed = True
            elif isinstance(insn, Copy):
                if (defs[insn.dest.name] == 1
                        and insn.dest.name not in constants
                        and insn.source.name in constants):
                    constants[insn.dest.name] = constants[insn.source.name]
                    changed = True
            elif isinstance(insn, Call) and insn.fun.name in PURE_OPS:
                if defs[insn.dest.name] == 1 and insn.dest.name not in constants:
                    vals = []
                    ok = True
                    for a in insn.args:
                        if a.name in constants:
                            vals.append(constants[a.name])
                        else:
                            ok = False
                            break
                    if ok:
                        v = _eval_op(insn.fun.name, vals)
                        if v is not None:
                            constants[insn.dest.name] = v
                            changed = True

    result = []
    for insn in instructions:
        if isinstance(insn, Copy) and insn.dest.name in constants:
            result.append(_make_const(constants[insn.dest.name], insn.dest))
        elif (isinstance(insn, Call) and insn.fun.name in PURE_OPS
              and insn.dest.name in constants):
            result.append(_make_const(constants[insn.dest.name], insn.dest))
        else:
            result.append(insn)
    return result
