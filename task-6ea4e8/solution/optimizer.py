#!/usr/bin/env python3
"""TAC optimizer — multi-pass optimization pipeline."""
import sys
import re


def parse_inst(line):
    """Parse a TAC instruction string into a tuple representation."""
    line = line.strip()
    if line.startswith('LABEL '):
        return ('LABEL', line[6:].strip())
    if line.startswith('GOTO '):
        return ('GOTO', line[5:].strip())
    m = re.match(r'IF\s+(\S+)\s+(==|!=|<=|>=|<|>)\s+(\S+)\s+GOTO\s+(\S+)', line)
    if m:
        return ('IF', m.group(1), m.group(2), m.group(3), m.group(4))
    if line.startswith('PRINT '):
        return ('PRINT', line[6:].strip())
    m = re.match(r'(\w+)\s*=\s*(.+)', line)
    if m:
        lhs = m.group(1)
        tokens = m.group(2).strip().split()
        if len(tokens) == 1:
            return ('ASSIGN', lhs, tokens[0])
        elif len(tokens) == 2:
            return ('UNARY', lhs, tokens[0], tokens[1])
        elif len(tokens) == 3:
            return ('BINOP', lhs, tokens[0], tokens[1], tokens[2])
    raise ValueError(f"Cannot parse: {line}")


def to_str(inst):
    """Convert instruction tuple back to string."""
    t = inst[0]
    if t == 'LABEL':
        return f'LABEL {inst[1]}'
    if t == 'GOTO':
        return f'GOTO {inst[1]}'
    if t == 'IF':
        return f'IF {inst[1]} {inst[2]} {inst[3]} GOTO {inst[4]}'
    if t == 'PRINT':
        return f'PRINT {inst[1]}'
    if t == 'ASSIGN':
        return f'{inst[1]} = {inst[2]}'
    if t == 'UNARY':
        return f'{inst[1]} = {inst[2]} {inst[3]}'
    if t == 'BINOP':
        return f'{inst[1]} = {inst[2]} {inst[3]} {inst[4]}'
    return str(inst)


def is_const(s):
    """Check if a string represents an integer constant."""
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False


def get_jump_targets(insts):
    """Return set of labels that are targets of GOTO or IF instructions."""
    targets = set()
    for inst in insts:
        if inst[0] == 'GOTO':
            targets.add(inst[1])
        elif inst[0] == 'IF':
            targets.add(inst[4])
    return targets


def eval_binop(a, op, b):
    """Evaluate a binary operation on integer values."""
    ops = {
        '+': a + b, '-': a - b, '*': a * b,
        '/': a // b if b != 0 else 0,
        '%': a % b if b != 0 else 0,
    }
    return ops.get(op)


def eval_relop(a, op, b):
    """Evaluate a relational operation."""
    return {
        '==': a == b, '!=': a != b,
        '<': a < b, '>': a > b,
        '<=': a <= b, '>=': a >= b,
    }[op]


def pass_const_prop_and_fold(insts):
    """Forward constant propagation with simultaneous folding."""
    changed = False
    targets = get_jump_targets(insts)
    consts = {}
    result = []

    for inst in insts:
        if inst[0] == 'LABEL' and inst[1] in targets:
            consts = {}

        if inst[0] == 'ASSIGN':
            lhs, rhs = inst[1], inst[2]
            if not is_const(rhs) and rhs in consts:
                rhs = consts[rhs]
                inst = ('ASSIGN', lhs, rhs)
                changed = True
            if is_const(rhs):
                consts[lhs] = rhs
            else:
                consts.pop(lhs, None)

        elif inst[0] == 'BINOP':
            lhs, a, op, b = inst[1], inst[2], inst[3], inst[4]
            na = consts[a] if (not is_const(a) and a in consts) else a
            nb = consts[b] if (not is_const(b) and b in consts) else b
            if na != a or nb != b:
                changed = True
            if is_const(na) and is_const(nb):
                val = eval_binop(int(na), op, int(nb))
                if val is not None:
                    s = str(val)
                    inst = ('ASSIGN', lhs, s)
                    consts[lhs] = s
                    changed = True
                else:
                    inst = ('BINOP', lhs, na, op, nb)
                    consts.pop(lhs, None)
            else:
                inst = ('BINOP', lhs, na, op, nb)
                consts.pop(lhs, None)

        elif inst[0] == 'UNARY':
            lhs, uop, operand = inst[1], inst[2], inst[3]
            nop = consts[operand] if (not is_const(operand) and operand in consts) else operand
            if nop != operand:
                changed = True
            if is_const(nop) and uop == 'NEG':
                s = str(-int(nop))
                inst = ('ASSIGN', lhs, s)
                consts[lhs] = s
                changed = True
            else:
                if nop != operand:
                    inst = ('UNARY', lhs, uop, nop)
                consts.pop(lhs, None)

        elif inst[0] == 'IF':
            _, lv, relop, rv, target = inst
            nl = consts[lv] if (not is_const(lv) and lv in consts) else lv
            nr = consts[rv] if (not is_const(rv) and rv in consts) else rv
            if nl != lv or nr != rv:
                inst = ('IF', nl, relop, nr, target)
                changed = True

        elif inst[0] == 'PRINT':
            v = inst[1]
            nv = consts[v] if (not is_const(v) and v in consts) else v
            if nv != v:
                inst = ('PRINT', nv)
                changed = True

        result.append(inst)
    return result, changed


def pass_branch_resolution(insts):
    """Replace constant-condition branches with GOTOs or remove them."""
    changed = False
    result = []
    for inst in insts:
        if inst[0] == 'IF':
            lv, relop, rv, target = inst[1], inst[2], inst[3], inst[4]
            if is_const(lv) and is_const(rv):
                cond = eval_relop(int(lv), relop, int(rv))
                if cond:
                    result.append(('GOTO', target))
                changed = True
                continue
        result.append(inst)
    return result, changed


def pass_unreachable_removal(insts):
    """Remove code after unconditional GOTO until next LABEL."""
    changed = False
    result = []
    skip = False
    for inst in insts:
        if skip:
            if inst[0] == 'LABEL':
                skip = False
                result.append(inst)
            else:
                changed = True
        else:
            result.append(inst)
            if inst[0] == 'GOTO':
                skip = True
    return result, changed


def pass_unused_label_removal(insts):
    """Remove labels that are not targets of any jump."""
    targets = get_jump_targets(insts)
    changed = False
    result = []
    for inst in insts:
        if inst[0] == 'LABEL' and inst[1] not in targets:
            changed = True
            continue
        result.append(inst)
    return result, changed


def pass_copy_propagation(insts):
    """Propagate variable copies: x = y then replace uses of x with y."""
    changed = False
    copies = {}
    targets = get_jump_targets(insts)
    result = []

    for inst in insts:
        if inst[0] == 'LABEL' and inst[1] in targets:
            copies = {}

        # Substitute copies in operands
        if inst[0] == 'BINOP':
            a, b = inst[2], inst[4]
            na = copies.get(a, a) if not is_const(a) else a
            nb = copies.get(b, b) if not is_const(b) else b
            if na != a or nb != b:
                inst = ('BINOP', inst[1], na, inst[3], nb)
                changed = True
        elif inst[0] == 'UNARY':
            operand = inst[3]
            nop = copies.get(operand, operand) if not is_const(operand) else operand
            if nop != operand:
                inst = ('UNARY', inst[1], inst[2], nop)
                changed = True
        elif inst[0] == 'ASSIGN' and not is_const(inst[2]):
            rhs = inst[2]
            nrhs = copies.get(rhs, rhs)
            if nrhs != rhs:
                inst = ('ASSIGN', inst[1], nrhs)
                changed = True
        elif inst[0] == 'IF':
            lv, rv = inst[1], inst[3]
            nl = copies.get(lv, lv) if not is_const(lv) else lv
            nr = copies.get(rv, rv) if not is_const(rv) else rv
            if nl != lv or nr != rv:
                inst = ('IF', nl, inst[2], nr, inst[4])
                changed = True
        elif inst[0] == 'PRINT':
            v = inst[1]
            nv = copies.get(v, v) if not is_const(v) else v
            if nv != v:
                inst = ('PRINT', nv)
                changed = True

        # Update copy map for definitions
        if inst[0] in ('ASSIGN', 'BINOP', 'UNARY'):
            defvar = inst[1]
            # Invalidate any copies whose source was redefined
            copies = {d: s for d, s in copies.items() if s != defvar}
            copies.pop(defvar, None)
            # Record new copy for var = var assignments
            if inst[0] == 'ASSIGN' and not is_const(inst[2]):
                src = inst[2]
                visited = {defvar}
                while src in copies and src not in visited:
                    visited.add(src)
                    src = copies[src]
                if src != defvar:
                    copies[defvar] = src

        result.append(inst)
    return result, changed


def pass_dead_code_elimination(insts):
    """Remove assignments to variables that are never used."""
    changed = False
    while True:
        used = set()
        for inst in insts:
            if inst[0] == 'BINOP':
                if not is_const(inst[2]):
                    used.add(inst[2])
                if not is_const(inst[4]):
                    used.add(inst[4])
            elif inst[0] == 'UNARY':
                if not is_const(inst[3]):
                    used.add(inst[3])
            elif inst[0] == 'ASSIGN':
                if not is_const(inst[2]):
                    used.add(inst[2])
            elif inst[0] == 'IF':
                if not is_const(inst[1]):
                    used.add(inst[1])
                if not is_const(inst[3]):
                    used.add(inst[3])
            elif inst[0] == 'PRINT':
                if not is_const(inst[1]):
                    used.add(inst[1])

        new_insts = []
        removed_any = False
        for inst in insts:
            if inst[0] in ('ASSIGN', 'BINOP', 'UNARY') and inst[1] not in used:
                removed_any = True
                changed = True
                continue
            new_insts.append(inst)

        insts = new_insts
        if not removed_any:
            break
    return insts, changed


def pass_goto_simplification(insts):
    """Remove GOTO to immediately following LABEL."""
    changed = False
    result = []
    for i, inst in enumerate(insts):
        if (inst[0] == 'GOTO'
                and i + 1 < len(insts)
                and insts[i + 1][0] == 'LABEL'
                and insts[i + 1][1] == inst[1]):
            changed = True
            continue
        result.append(inst)
    return result, changed


def optimize(text):
    """Run all optimization passes iteratively until fixed point."""
    insts = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            insts.append(parse_inst(line))

    passes = [
        pass_const_prop_and_fold,
        pass_branch_resolution,
        pass_unreachable_removal,
        pass_unused_label_removal,
        pass_copy_propagation,
        pass_dead_code_elimination,
        pass_goto_simplification,
    ]

    for _ in range(100):
        any_changed = False
        for p in passes:
            insts, c = p(insts)
            any_changed = any_changed or c
        if not any_changed:
            break

    return '\n'.join(to_str(i) for i in insts)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 optimizer.py <program.tac>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        text = f.read()
    print(optimize(text))


if __name__ == '__main__':
    main()
