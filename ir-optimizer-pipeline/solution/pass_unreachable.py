"""Unreachable code elimination pass."""
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)


def run(instructions):
    if not instructions:
        return instructions

    n = len(instructions)
    label_index = {}
    for i, insn in enumerate(instructions):
        if isinstance(insn, Label):
            label_index[insn.name] = i

    reachable = set()
    queue = [0]
    while queue:
        idx = queue.pop()
        if idx in reachable or idx < 0 or idx >= n:
            continue
        reachable.add(idx)
        insn = instructions[idx]
        if isinstance(insn, Jump):
            t = label_index.get(insn.label)
            if t is not None:
                queue.append(t)
        elif isinstance(insn, CondJump):
            for lbl in (insn.then_label, insn.else_label):
                t = label_index.get(lbl)
                if t is not None:
                    queue.append(t)
        else:
            queue.append(idx + 1)

    needed_labels = set()
    for i in reachable:
        insn = instructions[i]
        if isinstance(insn, Jump):
            needed_labels.add(insn.label)
        elif isinstance(insn, CondJump):
            needed_labels.add(insn.then_label)
            needed_labels.add(insn.else_label)

    result = []
    for i, insn in enumerate(instructions):
        if i in reachable:
            result.append(insn)
        elif isinstance(insn, Label) and insn.name in needed_labels:
            result.append(insn)
    return result
