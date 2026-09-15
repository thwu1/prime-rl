"""Dead code elimination pass (liveness-based)."""
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)

SIDE_EFFECT_FUNS = frozenset({'print_int', 'print_bool', 'read_int'})


def _written(insn):
    if isinstance(insn, (LoadIntConst, LoadBoolConst, Copy, Call)):
        return insn.dest
    return None


def _read_vars(insn):
    if isinstance(insn, Copy):
        return {insn.source.name}
    if isinstance(insn, Call):
        return {a.name for a in insn.args}
    if isinstance(insn, CondJump):
        return {insn.cond.name}
    return set()


def run(instructions):
    n = len(instructions)
    if n == 0:
        return instructions

    label_index = {}
    for i, insn in enumerate(instructions):
        if isinstance(insn, Label):
            label_index[insn.name] = i

    succs = [set() for _ in range(n)]
    for i, insn in enumerate(instructions):
        if isinstance(insn, Jump):
            t = label_index.get(insn.label)
            if t is not None:
                succs[i].add(t)
        elif isinstance(insn, CondJump):
            for lbl in (insn.then_label, insn.else_label):
                t = label_index.get(lbl)
                if t is not None:
                    succs[i].add(t)
        else:
            if i + 1 < n:
                succs[i].add(i + 1)

    live_in = [set() for _ in range(n)]
    live_out = [set() for _ in range(n)]

    changed = True
    while changed:
        changed = False
        for i in range(n - 1, -1, -1):
            insn = instructions[i]
            new_out = set()
            for j in succs[i]:
                new_out |= live_in[j]
            new_in = set(new_out)
            w = _written(insn)
            if w is not None:
                new_in.discard(w.name)
            new_in |= _read_vars(insn)
            if new_in != live_in[i] or new_out != live_out[i]:
                live_in[i] = new_in
                live_out[i] = new_out
                changed = True

    result = []
    for i, insn in enumerate(instructions):
        if isinstance(insn, (Jump, CondJump, Label)):
            result.append(insn)
        elif isinstance(insn, Call) and insn.fun.name in SIDE_EFFECT_FUNS:
            result.append(insn)
        else:
            w = _written(insn)
            if w is not None and w.name in live_out[i]:
                result.append(insn)
    return result
