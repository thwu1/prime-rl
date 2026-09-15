
"""
Complete IR optimizer implementation.

Implements the following passes, iterated to a fixed point:
1. Constant folding and propagation (conservative: single-definition vars only)
2. Copy propagation (single-definition source and dest only)
3. Dead branch elimination (CondJump with constant condition → Jump)
4. Unreachable code elimination (BFS from entry, remove unreachable)
5. Dead code elimination (backward liveness analysis)
"""

from collections import defaultdict
from ir import (
    Instruction, IRVar, LoadIntConst, LoadBoolConst, Copy, Call,
    Jump, CondJump, Label,
)

SIDE_EFFECT_FUNS = frozenset({'print_int', 'print_bool', 'read_int'})
PURE_OPS = frozenset({
    '+', '-', '*', '/', '%',
    '==', '!=', '<', '<=', '>', '>=',
    'unary_-', 'not',
})


def optimize(instructions: list[Instruction]) -> list[Instruction]:
    """Main optimization loop — iterate all passes until fixed point."""
    prev = None
    while instructions != prev:
        prev = instructions
        instructions = _constant_fold_and_propagate(instructions)
        instructions = _copy_propagation(instructions)
        instructions = _dead_branch_elimination(instructions)
        instructions = _unreachable_code_elimination(instructions)
        instructions = _dead_code_elimination(instructions)
    return instructions


# ---- helpers ---------------------------------------------------------------

def _get_written_var(insn: Instruction):
    """Return the IRVar written by an instruction, or None."""
    if isinstance(insn, (LoadIntConst, LoadBoolConst)):
        return insn.dest
    if isinstance(insn, Copy):
        return insn.dest
    if isinstance(insn, Call):
        return insn.dest
    return None


def _get_read_vars(insn: Instruction) -> set[str]:
    """Return variable names read by an instruction."""
    if isinstance(insn, Copy):
        return {insn.source.name}
    if isinstance(insn, Call):
        return {a.name for a in insn.args}
    if isinstance(insn, CondJump):
        return {insn.cond.name}
    return set()


def _def_counts(instructions: list[Instruction]) -> dict[str, int]:
    """Count how many times each variable is defined across all instructions."""
    counts: dict[str, int] = defaultdict(int)
    for insn in instructions:
        v = _get_written_var(insn)
        if v is not None:
            counts[v.name] += 1
    return counts


def _eval_pure_op(name: str, args: list):
    """Evaluate a pure operator on constant arguments. Returns None on failure."""
    try:
        if name == '+':   return args[0] + args[1]
        if name == '-':   return args[0] - args[1]
        if name == '*':   return args[0] * args[1]
        if name == '/':
            if args[1] == 0:
                return None
            q = abs(args[0]) // abs(args[1])
            if (args[0] < 0) != (args[1] < 0):
                q = -q
            return q
        if name == '%':
            if args[1] == 0:
                return None
            r = abs(args[0]) % abs(args[1])
            if args[0] < 0:
                r = -r
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


def _make_const_load(value, dest: IRVar) -> Instruction:
    """Create a LoadIntConst or LoadBoolConst for the given value."""
    if isinstance(value, bool):
        return LoadBoolConst(value, dest)
    return LoadIntConst(value, dest)


# ---- pass 1: constant folding & propagation --------------------------------

def _constant_fold_and_propagate(
    instructions: list[Instruction],
) -> list[Instruction]:
    """
    Conservative constant propagation: only treat a variable as constant
    if it has exactly one definition in the entire program and that
    definition is a compile-time constant (or computable from constants).
    """
    defs = _def_counts(instructions)

    # Phase 1: discover constants (iterate until stable)
    constants: dict[str, object] = {}  # var name → constant value

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
                src = insn.source.name
                dst = insn.dest.name
                if defs[dst] == 1 and dst not in constants and src in constants:
                    constants[dst] = constants[src]
                    changed = True
            elif isinstance(insn, Call) and insn.fun.name in PURE_OPS:
                dst = insn.dest.name
                if defs[dst] == 1 and dst not in constants:
                    arg_vals = []
                    all_const = True
                    for a in insn.args:
                        if a.name in constants:
                            arg_vals.append(constants[a.name])
                        else:
                            all_const = False
                            break
                    if all_const:
                        val = _eval_pure_op(insn.fun.name, arg_vals)
                        if val is not None:
                            constants[dst] = val
                            changed = True

    # Phase 2: rewrite instructions
    result = []
    for insn in instructions:
        if isinstance(insn, Copy):
            if insn.dest.name in constants:
                result.append(_make_const_load(constants[insn.dest.name], insn.dest))
                continue
        elif isinstance(insn, Call) and insn.fun.name in PURE_OPS:
            if insn.dest.name in constants:
                result.append(_make_const_load(constants[insn.dest.name], insn.dest))
                continue
        result.append(insn)

    return result


# ---- pass 2: copy propagation ---------------------------------------------

def _copy_propagation(instructions: list[Instruction]) -> list[Instruction]:
    """
    Replace uses of copy destinations with their ultimate sources.
    Only safe for variables with a single definition.
    """
    defs = _def_counts(instructions)

    # Build direct copy map: dest → source (only single-def on both sides)
    copy_map: dict[str, str] = {}
    for insn in instructions:
        if isinstance(insn, Copy):
            if defs[insn.dest.name] == 1 and defs.get(insn.source.name, 0) == 1:
                copy_map[insn.dest.name] = insn.source.name

    # Resolve transitive copies
    def resolve(name: str) -> str:
        visited: set[str] = set()
        while name in copy_map and name not in visited:
            visited.add(name)
            name = copy_map[name]
        return name

    # Rewrite
    result = []
    for insn in instructions:
        if isinstance(insn, Copy):
            new_src = IRVar(resolve(insn.source.name))
            if new_src.name == insn.dest.name:
                continue  # self-copy after propagation → remove
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


# ---- pass 3: dead branch elimination --------------------------------------

def _dead_branch_elimination(
    instructions: list[Instruction],
) -> list[Instruction]:
    """Replace CondJump with a constant condition by an unconditional Jump."""
    defs = _def_counts(instructions)

    # Gather known boolean/int constants (single-def only)
    constants: dict[str, object] = {}
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


# ---- pass 4: unreachable code elimination ----------------------------------

def _unreachable_code_elimination(
    instructions: list[Instruction],
) -> list[Instruction]:
    """Remove instructions that can never be reached from the entry point."""
    if not instructions:
        return instructions

    n = len(instructions)
    label_index: dict[str, int] = {}
    for i, insn in enumerate(instructions):
        if isinstance(insn, Label):
            label_index[insn.name] = i

    # BFS from instruction 0
    reachable: set[int] = set()
    queue = [0]
    while queue:
        idx = queue.pop()
        if idx in reachable or idx < 0 or idx >= n:
            continue
        reachable.add(idx)
        insn = instructions[idx]
        if isinstance(insn, Jump):
            target = label_index.get(insn.label)
            if target is not None:
                queue.append(target)
        elif isinstance(insn, CondJump):
            for lbl in (insn.then_label, insn.else_label):
                target = label_index.get(lbl)
                if target is not None:
                    queue.append(target)
        else:
            queue.append(idx + 1)

    # Also keep labels that are targets of reachable jumps
    needed_labels: set[str] = set()
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


# ---- pass 5: dead code elimination (liveness-based) -----------------------

def _dead_code_elimination(
    instructions: list[Instruction],
) -> list[Instruction]:
    """
    Remove instructions whose results are never used, preserving side effects.
    Uses backward liveness analysis with a worklist algorithm over the CFG.
    """
    n = len(instructions)
    if n == 0:
        return instructions

    # Build label index
    label_index: dict[str, int] = {}
    for i, insn in enumerate(instructions):
        if isinstance(insn, Label):
            label_index[insn.name] = i

    # Build successor relation
    successors: list[set[int]] = [set() for _ in range(n)]
    for i, insn in enumerate(instructions):
        if isinstance(insn, Jump):
            t = label_index.get(insn.label)
            if t is not None:
                successors[i].add(t)
        elif isinstance(insn, CondJump):
            for lbl in (insn.then_label, insn.else_label):
                t = label_index.get(lbl)
                if t is not None:
                    successors[i].add(t)
        else:
            if i + 1 < n:
                successors[i].add(i + 1)

    # Backward liveness: live_out[i] = set of var names live after insn i
    live_in: list[set[str]] = [set() for _ in range(n)]
    live_out: list[set[str]] = [set() for _ in range(n)]

    changed = True
    while changed:
        changed = False
        for i in range(n - 1, -1, -1):
            insn = instructions[i]

            # live_out[i] = ∪ live_in[j] for j in successors[i]
            new_out: set[str] = set()
            for j in successors[i]:
                new_out |= live_in[j]

            # live_in[i] = (live_out[i] − def[i]) ∪ use[i]
            new_in = set(new_out)
            written = _get_written_var(insn)
            if written is not None:
                new_in.discard(written.name)
            new_in |= _get_read_vars(insn)

            if new_in != live_in[i] or new_out != live_out[i]:
                live_in[i] = new_in
                live_out[i] = new_out
                changed = True

    # Keep an instruction if:
    #  - it's a control flow instruction (Jump, CondJump, Label)
    #  - it has side effects (print_int, print_bool, read_int)
    #  - it defines a variable that is live after it
    result = []
    for i, insn in enumerate(instructions):
        if isinstance(insn, (Jump, CondJump, Label)):
            result.append(insn)
        elif isinstance(insn, Call) and insn.fun.name in SIDE_EFFECT_FUNS:
            result.append(insn)
        else:
            written = _get_written_var(insn)
            if written is not None and written.name in live_out[i]:
                result.append(insn)
    return result
