#!/usr/bin/env python3

"""Complete IR optimizer implementing constant propagation, CSE, and DCE."""

import sys
import copy

sys.path.insert(0, "/app")
from ir_types import Instruction, BasicBlock, Function, Program
from ir_parser import parse_program
from ir_emitter import emit_program


BINARY_OPS = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a // b if b != 0 else 0,
    "mod": lambda a, b: a % b if b != 0 else 0,
    "lt":  lambda a, b: 1 if a < b else 0,
    "gt":  lambda a, b: 1 if a > b else 0,
    "le":  lambda a, b: 1 if a <= b else 0,
    "ge":  lambda a, b: 1 if a >= b else 0,
    "eq":  lambda a, b: 1 if a == b else 0,
    "ne":  lambda a, b: 1 if a != b else 0,
    "and": lambda a, b: 1 if (a and b) else 0,
    "or":  lambda a, b: 1 if (a or b) else 0,
}

UNARY_OPS = {
    "not": lambda a: 1 if not a else 0,
    "neg": lambda a: -a,
}

SIDE_EFFECT_OPS = {"print", "call", "br", "cbr", "ret", "nop"}


# ── helpers ────────────────────────────────────────────────────────────────

def build_cfg(func):
    block_map = {b.label: b for b in func.blocks}
    succs = {b.label: [] for b in func.blocks}
    preds = {b.label: [] for b in func.blocks}
    for block in func.blocks:
        if not block.instructions:
            continue
        last = block.instructions[-1]
        if last.op == "br":
            t = last.args[0]
            if t in block_map:
                succs[block.label].append(t)
                preds[t].append(block.label)
        elif last.op == "cbr":
            for t in {last.args[1], last.args[2]}:
                if t in block_map:
                    succs[block.label].append(t)
                    preds[t].append(block.label)
    return block_map, succs, preds


# ── pass 1: local constant folding ────────────────────────────────────────

def local_constant_fold(func):
    """Fold constant expressions within each basic block and convert
    conditional branches with known conditions to unconditional."""
    changed = False
    for block in func.blocks:
        local = {}
        for instr in block.instructions:
            if instr.op == "const" and instr.dest:
                if isinstance(instr.args[0], int):
                    local[instr.dest] = instr.args[0]

            elif instr.op in BINARY_OPS and instr.dest:
                a, b = instr.args[0], instr.args[1]
                av = a if isinstance(a, int) else local.get(a)
                bv = b if isinstance(b, int) else local.get(b)
                if av is not None and bv is not None:
                    result = BINARY_OPS[instr.op](av, bv)
                    instr.op = "const"
                    instr.args = [result]
                    local[instr.dest] = result
                    changed = True
                else:
                    local.pop(instr.dest, None)

            elif instr.op in UNARY_OPS and instr.dest:
                a = instr.args[0]
                av = a if isinstance(a, int) else local.get(a)
                if av is not None:
                    result = UNARY_OPS[instr.op](av)
                    instr.op = "const"
                    instr.args = [result]
                    local[instr.dest] = result
                    changed = True
                else:
                    local.pop(instr.dest, None)

            elif instr.op == "copy" and instr.dest:
                a = instr.args[0]
                av = a if isinstance(a, int) else local.get(a)
                if av is not None:
                    instr.op = "const"
                    instr.args = [av]
                    local[instr.dest] = av
                    changed = True
                else:
                    local.pop(instr.dest, None)

            elif instr.dest:
                local.pop(instr.dest, None)

            # cbr with known condition → br
            if instr.op == "cbr":
                cond = instr.args[0]
                cv = cond if isinstance(cond, int) else local.get(cond)
                if cv is not None:
                    target = instr.args[1] if cv else instr.args[2]
                    instr.op = "br"
                    instr.args = [target]
                    changed = True
    return changed


# ── pass 2: global constant propagation ───────────────────────────────────

def propagate_constants(func):
    """If a register has exactly one definition and it is ``const``,
    replace every use of that register with the literal value."""
    defs = {}
    for block in func.blocks:
        for instr in block.instructions:
            if instr.dest:
                defs.setdefault(instr.dest, []).append(instr)

    constants = {}
    for reg, deflist in defs.items():
        if len(deflist) == 1 and deflist[0].op == "const":
            v = deflist[0].args[0]
            if isinstance(v, int):
                constants[reg] = v
    if not constants:
        return False

    changed = False
    for block in func.blocks:
        for instr in block.instructions:
            new_args = []
            for i, arg in enumerate(instr.args):
                if isinstance(arg, str) and arg in constants:
                    # preserve label positions
                    if instr.op == "br":
                        new_args.append(arg)
                    elif instr.op == "cbr" and i >= 1:
                        new_args.append(arg)
                    elif instr.op == "call" and i == 0:
                        new_args.append(arg)
                    else:
                        new_args.append(constants[arg])
                        changed = True
                else:
                    new_args.append(arg)
            instr.args = new_args
    return changed


# ── pass 3: unreachable-code elimination ──────────────────────────────────

def eliminate_unreachable(func):
    if not func.blocks:
        return False
    _, succs, _ = build_cfg(func)
    reachable = set()
    wl = [func.blocks[0].label]
    while wl:
        b = wl.pop()
        if b in reachable:
            continue
        reachable.add(b)
        for s in succs.get(b, []):
            wl.append(s)
    before = len(func.blocks)
    func.blocks = [b for b in func.blocks if b.label in reachable]
    return len(func.blocks) < before


# ── pass 4: local CSE ─────────────────────────────────────────────────────

def local_cse(func):
    """Eliminate common subexpressions within each basic block."""
    changed = False
    for block in func.blocks:
        expr_map = {}       # (op, args_tuple) -> dest register
        replacements = {}   # old_reg -> replacement_reg
        new_instrs = []

        for instr in block.instructions:
            # apply accumulated replacements to args
            new_args = []
            for i, arg in enumerate(instr.args):
                if isinstance(arg, str) and arg in replacements:
                    if instr.op == "br":
                        new_args.append(arg)
                    elif instr.op == "cbr" and i >= 1:
                        new_args.append(arg)
                    elif instr.op == "call" and i == 0:
                        new_args.append(arg)
                    else:
                        new_args.append(replacements[arg])
                        changed = True
                else:
                    new_args.append(arg)
            instr.args = new_args

            # check for duplicate expression
            is_candidate = instr.dest and (
                instr.op in BINARY_OPS or instr.op in UNARY_OPS
            )
            if is_candidate:
                key = (instr.op, tuple(instr.args))
                if key in expr_map:
                    replacements[instr.dest] = expr_map[key]
                    changed = True
                    continue           # drop this instruction

            # invalidate on redefinition (before recording new expr)
            if instr.dest:
                to_remove = [
                    k for k, v in expr_map.items()
                    if instr.dest in k[1] or v == instr.dest
                ]
                for k in to_remove:
                    del expr_map[k]

            # record new expression after invalidation
            if is_candidate:
                expr_map[key] = instr.dest

            new_instrs.append(instr)
        block.instructions = new_instrs
    return changed


# ── pass 5: dead-code elimination ─────────────────────────────────────────

def dead_code_elimination(func):
    """Remove instructions whose destination register is never read."""
    changed = False
    for _ in range(30):
        used = set()
        for block in func.blocks:
            for instr in block.instructions:
                if instr.op == "br":
                    pass
                elif instr.op == "cbr":
                    a = instr.args[0]
                    if isinstance(a, str):
                        used.add(a)
                elif instr.op == "call":
                    for a in instr.args[1:]:
                        if isinstance(a, str):
                            used.add(a)
                else:
                    for a in instr.args:
                        if isinstance(a, str):
                            used.add(a)

        round_changed = False
        for block in func.blocks:
            new_instrs = []
            for instr in block.instructions:
                if (instr.dest
                        and instr.dest not in used
                        and instr.op not in SIDE_EFFECT_OPS):
                    round_changed = True
                    changed = True
                    continue
                new_instrs.append(instr)
            block.instructions = new_instrs
        if not round_changed:
            break
    return changed


# ── driver ────────────────────────────────────────────────────────────────

def optimize_function(func):
    for _ in range(20):
        c = False
        if local_constant_fold(func):
            c = True
        if propagate_constants(func):
            c = True
        if eliminate_unreachable(func):
            c = True
        if local_cse(func):
            c = True
        if dead_code_elimination(func):
            c = True
        if not c:
            break


def optimize(program):
    program = copy.deepcopy(program)
    for func in program.functions:
        optimize_function(func)
    return program


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.ir output.ir", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        source = f.read()
    prog = parse_program(source)
    optimized = optimize(prog)
    with open(sys.argv[2], "w") as f:
        f.write(emit_program(optimized))
