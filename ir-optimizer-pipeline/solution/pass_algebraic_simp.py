"""Algebraic identity simplification pass.

Recognizes and simplifies algebraic identities where one operand is a
known constant:
    x + 0 = x,  0 + x = x
    x - 0 = x
    x * 1 = x,  1 * x = x
    x * 0 = 0,  0 * x = 0
    x / 1 = x
    x - x = 0   (only when x has a single static definition)

Requires integration with constant analysis: the pass must know which
variables hold constant 0 or 1 to identify the identities, even when
the other operand is dynamic.
"""
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


def _def_counts(instructions):
    counts = defaultdict(int)
    for insn in instructions:
        if isinstance(insn, (LoadIntConst, LoadBoolConst, Copy, Call)):
            counts[insn.dest.name] += 1
    return counts


def _build_const_map(instructions, defs):
    constants = {}
    for insn in instructions:
        if isinstance(insn, LoadIntConst) and defs[insn.dest.name] == 1:
            constants[insn.dest.name] = insn.value
        elif isinstance(insn, LoadBoolConst) and defs[insn.dest.name] == 1:
            constants[insn.dest.name] = insn.value
    return constants


def _try_simplify(insn, constants, defs):
    op = insn.fun.name
    args = insn.args

    if op == '+' and len(args) == 2:
        a0, a1 = args
        if a1.name in constants and constants[a1.name] == 0:
            return Copy(a0, insn.dest)
        if a0.name in constants and constants[a0.name] == 0:
            return Copy(a1, insn.dest)

    elif op == '-' and len(args) == 2:
        a0, a1 = args
        if a1.name in constants and constants[a1.name] == 0:
            return Copy(a0, insn.dest)
        if a0.name == a1.name and defs[a0.name] == 1:
            return LoadIntConst(0, insn.dest)

    elif op == '*' and len(args) == 2:
        a0, a1 = args
        for x, y in [(a0, a1), (a1, a0)]:
            if x.name in constants:
                if constants[x.name] == 1:
                    return Copy(y, insn.dest)
                if constants[x.name] == 0:
                    return LoadIntConst(0, insn.dest)

    elif op == '/' and len(args) == 2:
        if args[1].name in constants and constants[args[1].name] == 1:
            return Copy(args[0], insn.dest)

    return None


def run(instructions):
    defs = _def_counts(instructions)
    constants = _build_const_map(instructions, defs)

    result = []
    for insn in instructions:
        if isinstance(insn, Call) and insn.fun.name in PURE_OPS:
            simplified = _try_simplify(insn, constants, defs)
            if simplified is not None:
                result.append(simplified)
                continue
        result.append(insn)
    return result
