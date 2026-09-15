#!/usr/bin/env python3
"""
Multi-pass bytecode optimizer for a stack-based VM assembly language.
Implements cascading constant propagation through variables, copy
propagation, branch elimination, peephole constant folding, algebraic
simplification, dead code/store elimination, jump threading, and
load consolidation.

"""
import sys


def parse_asm(filename):
    instructions = []
    with open(filename) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            parts = stripped.split(None, 1)
            op = parts[0]
            arg = parts[1] if len(parts) > 1 else None
            instructions.append((op, arg))
    return instructions


def emit_asm(instructions, filename):
    with open(filename, 'w') as f:
        for op, arg in instructions:
            if arg is not None:
                f.write(f"{op} {arg}\n")
            else:
                f.write(f"{op}\n")


def get_jump_targets(insns):
    targets = set()
    for op, arg in insns:
        if op in ('JUMP', 'JUMP_TRUE', 'JUMP_FALSE') and arg:
            targets.add(arg)
    return targets


def count_stores(insns):
    counts = {}
    for op, arg in insns:
        if op == 'STORE' and arg:
            counts[arg] = counts.get(arg, 0) + 1
    return counts


# --- Peephole constant folding ---

def constant_fold(insns):
    arith = {
        'ADD': lambda a, b: a + b,
        'SUB': lambda a, b: a - b,
        'MUL': lambda a, b: a * b,
        'MOD': lambda a, b: a % b if b != 0 else None,
    }
    cmp = {
        'CMP_EQ': lambda a, b: 1 if a == b else 0,
        'CMP_NE': lambda a, b: 1 if a != b else 0,
        'CMP_LT': lambda a, b: 1 if a < b else 0,
        'CMP_LE': lambda a, b: 1 if a <= b else 0,
        'CMP_GT': lambda a, b: 1 if a > b else 0,
        'CMP_GE': lambda a, b: 1 if a >= b else 0,
    }
    changed = True
    while changed:
        changed = False
        new = []
        i = 0
        while i < len(insns):
            if (i + 2 < len(insns)
                    and insns[i][0] == 'PUSH_INT'
                    and insns[i+1][0] == 'PUSH_INT'):
                a = int(insns[i][1])
                b = int(insns[i+1][1])
                op3 = insns[i+2][0]
                if op3 in arith:
                    r = arith[op3](a, b)
                    if r is not None:
                        new.append(('PUSH_INT', str(int(r))))
                        i += 3
                        changed = True
                        continue
                if op3 == 'DIV' and b != 0:
                    new.append(('PUSH_INT', str(int(a / b))))
                    i += 3
                    changed = True
                    continue
                if op3 in cmp:
                    new.append(('PUSH_INT', str(cmp[op3](a, b))))
                    i += 3
                    changed = True
                    continue
            if (i + 1 < len(insns) and insns[i][0] == 'PUSH_INT'):
                a = int(insns[i][1])
                if insns[i+1][0] == 'NEG':
                    new.append(('PUSH_INT', str(-a)))
                    i += 2
                    changed = True
                    continue
                if insns[i+1][0] == 'NOT':
                    new.append(('PUSH_INT', '0' if a != 0 else '1'))
                    i += 2
                    changed = True
                    continue
            new.append(insns[i])
            i += 1
        insns = new
    return insns


# --- Algebraic identity removal ---

def algebraic_simplify(insns):
    patterns = [
        ('PUSH_INT', '0', 'ADD'),
        ('PUSH_INT', '0', 'SUB'),
        ('PUSH_INT', '1', 'MUL'),
        ('PUSH_INT', '1', 'DIV'),
    ]
    changed = True
    while changed:
        changed = False
        new = []
        i = 0
        while i < len(insns):
            matched = False
            if i + 1 < len(insns):
                for po, pv, ao in patterns:
                    if (insns[i][0] == po
                            and insns[i][1] == pv
                            and insns[i+1][0] == ao):
                        i += 2
                        changed = True
                        matched = True
                        break
            if not matched:
                new.append(insns[i])
                i += 1
        insns = new
    return insns


# --- Global constant propagation through STORE/LOAD ---

def constant_propagation(insns):
    stores = count_stores(insns)
    constants = {}
    for i in range(len(insns) - 1):
        op, arg = insns[i]
        nop, narg = insns[i + 1]
        if (op in ('PUSH_INT', 'PUSH_STR')
                and nop == 'STORE'
                and narg is not None
                and stores.get(narg, 0) == 1):
            constants[narg] = (op, arg)
    if not constants:
        return insns, False
    changed = False
    new = []
    for op, arg in insns:
        if op == 'LOAD' and arg in constants:
            new.append(constants[arg])
            changed = True
        else:
            new.append((op, arg))
    return new, changed


# --- Copy propagation (LOAD x / STORE y where y single-def) ---

def copy_propagation(insns):
    stores = count_stores(insns)
    copies = {}
    for i in range(len(insns) - 1):
        op, arg = insns[i]
        nop, narg = insns[i + 1]
        if (op == 'LOAD' and arg is not None
                and nop == 'STORE' and narg is not None
                and stores.get(narg, 0) == 1):
            copies[narg] = arg
    if not copies:
        return insns, False

    def resolve(var, visited=None):
        if visited is None:
            visited = set()
        if var in visited:
            return var
        visited.add(var)
        if var in copies:
            return resolve(copies[var], visited)
        return var

    changed = False
    new = []
    for op, arg in insns:
        if op == 'LOAD' and arg in copies:
            resolved = resolve(arg)
            if resolved != arg:
                new.append(('LOAD', resolved))
                changed = True
            else:
                new.append((op, arg))
        else:
            new.append((op, arg))
    return new, changed


# --- Branch elimination (constant condition) ---

def branch_elimination(insns):
    changed = False
    new = []
    i = 0
    while i < len(insns):
        if i + 1 < len(insns) and insns[i][0] == 'PUSH_INT':
            val = int(insns[i][1])
            if insns[i+1][0] == 'JUMP_FALSE':
                if val != 0:
                    i += 2
                    changed = True
                    continue
                else:
                    new.append(('JUMP', insns[i+1][1]))
                    i += 2
                    changed = True
                    continue
            elif insns[i+1][0] == 'JUMP_TRUE':
                if val != 0:
                    new.append(('JUMP', insns[i+1][1]))
                    i += 2
                    changed = True
                    continue
                else:
                    i += 2
                    changed = True
                    continue
        new.append(insns[i])
        i += 1
    return new, changed


# --- Dead code elimination (unreachable after HALT/JUMP) ---

def dead_code_eliminate(insns):
    jump_targets = get_jump_targets(insns)
    new = []
    i = 0
    while i < len(insns):
        op, arg = insns[i]
        new.append(insns[i])
        i += 1
        if op in ('HALT', 'JUMP'):
            while i < len(insns):
                nop, narg = insns[i]
                if nop == 'LABEL' and narg in jump_targets:
                    break
                i += 1
    return new


# --- Dead store elimination ---

def dead_store_eliminate(insns):
    changed = True
    while changed:
        changed = False
        loaded = set()
        for op, arg in insns:
            if op == 'LOAD' and arg:
                loaded.add(arg)
        new = []
        for op, arg in insns:
            if op == 'STORE' and arg and arg not in loaded:
                new.append(('DROP', None))
                changed = True
            else:
                new.append((op, arg))
        insns = new
        new = []
        i = 0
        while i < len(insns):
            if i + 1 < len(insns) and insns[i+1][0] == 'DROP':
                if insns[i][0] in ('PUSH_INT', 'PUSH_STR', 'LOAD', 'DUP'):
                    i += 2
                    changed = True
                    continue
            new.append(insns[i])
            i += 1
        insns = new
    return insns


# --- Jump threading ---

def jump_thread(insns):
    label_idx = {}
    for i, (op, arg) in enumerate(insns):
        if op == 'LABEL':
            label_idx[arg] = i

    def resolve_label(label, visited=None):
        if visited is None:
            visited = set()
        if label in visited:
            return label
        visited.add(label)
        idx = label_idx.get(label)
        if idx is None:
            return label
        j = idx + 1
        while j < len(insns) and insns[j][0] == 'LABEL':
            j += 1
        if j < len(insns) and insns[j][0] == 'JUMP':
            return resolve_label(insns[j][1], visited)
        return label

    changed = False
    new = []
    for op, arg in insns:
        if op in ('JUMP', 'JUMP_TRUE', 'JUMP_FALSE') and arg:
            resolved = resolve_label(arg)
            if resolved != arg:
                new.append((op, resolved))
                changed = True
            else:
                new.append((op, arg))
        else:
            new.append((op, arg))
    return new, changed


# --- Jump-to-next removal ---

def remove_jump_to_next(insns):
    changed = False
    new = []
    i = 0
    while i < len(insns):
        if insns[i][0] == 'JUMP':
            target = insns[i][1]
            j = i + 1
            found = False
            while j < len(insns):
                if insns[j][0] == 'LABEL':
                    if insns[j][1] == target:
                        found = True
                        break
                    j += 1
                else:
                    break
            if found:
                i += 1
                changed = True
                continue
        new.append(insns[i])
        i += 1
    return new, changed


# --- Load consolidation (LOAD x / LOAD x -> LOAD x / DUP) ---

def load_consolidation(insns):
    changed = False
    new = []
    i = 0
    while i < len(insns):
        if (i + 1 < len(insns)
                and insns[i][0] == 'LOAD'
                and insns[i+1][0] == 'LOAD'
                and insns[i][1] == insns[i+1][1]):
            new.append(insns[i])
            new.append(('DUP', None))
            i += 2
            changed = True
        else:
            new.append(insns[i])
            i += 1
    return new, changed


# --- Redundant ops ---

def redundant_ops(insns):
    patterns = [('DUP', 'DROP'), ('SWAP', 'SWAP'), ('NEG', 'NEG')]
    changed = True
    while changed:
        changed = False
        new = []
        i = 0
        while i < len(insns):
            if i + 1 < len(insns):
                matched = False
                for p1, p2 in patterns:
                    if insns[i][0] == p1 and insns[i+1][0] == p2:
                        i += 2
                        changed = True
                        matched = True
                        break
                if matched:
                    continue
            new.append(insns[i])
            i += 1
        insns = new
    return insns


# --- Unused label cleanup ---

def remove_unused_labels(insns):
    targets = get_jump_targets(insns)
    return [(op, arg) for op, arg in insns if op != 'LABEL' or arg in targets]


# --- Main optimization loop ---

def optimize(insns):
    for _ in range(50):
        prev = insns[:]

        insns = constant_fold(insns)
        insns = algebraic_simplify(insns)

        propagated, _ = constant_propagation(insns)
        insns = propagated

        copied, _ = copy_propagation(insns)
        insns = copied

        branched, _ = branch_elimination(insns)
        insns = branched

        threaded, _ = jump_thread(insns)
        insns = threaded

        insns = dead_code_eliminate(insns)
        insns = dead_store_eliminate(insns)

        no_jump, _ = remove_jump_to_next(insns)
        insns = no_jump

        consolidated, _ = load_consolidation(insns)
        insns = consolidated

        insns = redundant_ops(insns)
        insns = remove_unused_labels(insns)

        if insns == prev:
            break
    return insns


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 optimizer.py <input.asm> <output.asm>",
              file=sys.stderr)
        sys.exit(1)
    insns = parse_asm(sys.argv[1])
    optimized = optimize(insns)
    emit_asm(optimized, sys.argv[2])


if __name__ == '__main__':
    main()
