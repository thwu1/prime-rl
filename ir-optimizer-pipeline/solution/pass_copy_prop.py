"""Copy propagation pass."""
from collections import defaultdict
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)


def _def_counts(instructions):
    counts = defaultdict(int)
    for insn in instructions:
        if isinstance(insn, (LoadIntConst, LoadBoolConst, Copy, Call)):
            if insn.dest is not None:
                counts[insn.dest.name] += 1
    return counts


def run(instructions):
    defs = _def_counts(instructions)

    copy_map = {}
    for insn in instructions:
        if isinstance(insn, Copy):
            if defs[insn.dest.name] == 1 and defs.get(insn.source.name, 0) == 1:
                copy_map[insn.dest.name] = insn.source.name

    def resolve(name):
        visited = set()
        while name in copy_map and name not in visited:
            visited.add(name)
            name = copy_map[name]
        return name

    result = []
    for insn in instructions:
        if isinstance(insn, Copy):
            new_src = IRVar(resolve(insn.source.name))
            if new_src.name == insn.dest.name:
                continue
            result.append(Copy(new_src, insn.dest))
        elif isinstance(insn, Call):
            new_args = tuple(IRVar(resolve(a.name)) for a in insn.args)
            result.append(Call(insn.fun, new_args, insn.dest))
        elif isinstance(insn, CondJump):
            result.append(CondJump(
                IRVar(resolve(insn.cond.name)),
                insn.then_label,
                insn.else_label,
            ))
        else:
            result.append(insn)
    return result
