"""Dead branch elimination pass."""
from collections import defaultdict
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)


def run(instructions):
    defs = defaultdict(int)
    for insn in instructions:
        if isinstance(insn, (LoadIntConst, LoadBoolConst, Copy, Call)):
            if insn.dest is not None:
                defs[insn.dest.name] += 1

    constants = {}
    for insn in instructions:
        if isinstance(insn, LoadBoolConst) and defs[insn.dest.name] == 1:
            constants[insn.dest.name] = insn.value
        elif isinstance(insn, LoadIntConst) and defs[insn.dest.name] == 1:
            constants[insn.dest.name] = insn.value

    result = []
    for insn in instructions:
        if isinstance(insn, CondJump) and insn.cond.name in constants:
            if constants[insn.cond.name]:
                result.append(Jump(insn.then_label))
            else:
                result.append(Jump(insn.else_label))
        else:
            result.append(insn)
    return result
