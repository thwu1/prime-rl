#!/usr/bin/env python3
"""
Peephole optimizer for Mugo-generated x86-64 NASM assembly.

The Mugo compiler uses a naive stack-machine code generation strategy where
every operation pushes operands to the stack and pops them into registers.
This optimizer identifies and eliminates redundant push/pop sequences:

1. Adjacent pairs: push X; pop Y  ->  mov Y, X  (or eliminated if X == Y)
2. Multi-push/pop: N pushes followed by N pops  ->  N movs (LIFO order)
3. Look-through: push X; <neutral instrs>; pop Y  ->  <neutral instrs>; mov Y, X
"""
import sys
import re

REGS_64 = frozenset([
    'rax', 'rbx', 'rcx', 'rdx', 'rsi', 'rdi', 'rsp', 'rbp',
    'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15',
])


def is_reg(s):
    """Check if operand is a 64-bit register."""
    return s.strip() in REGS_64


def get_push_op(line):
    """If line is a push instruction, return operand; else None."""
    m = re.match(r'\s*push\s+(.*?)\s*$', line)
    return m.group(1) if m else None


def get_pop_op(line):
    """If line is a pop instruction, return operand; else None."""
    m = re.match(r'\s*pop\s+(.*?)\s*$', line)
    return m.group(1) if m else None


def is_label(line):
    """Check if line is a label definition."""
    s = line.strip()
    return bool(s) and s.endswith(':') and not s.startswith(('section', 'global'))


def is_control_flow(line):
    """Check if line is a jump, call, ret, or syscall."""
    s = line.strip()
    if not s:
        return False
    parts = s.split()
    mnemonic = parts[0].lower()
    return mnemonic.startswith('j') or mnemonic in ('call', 'ret', 'syscall')


def is_stack_neutral(line):
    """Check if instruction doesn't affect stack pointer or control flow."""
    s = line.strip()
    if not s:
        return False
    if s.startswith(';'):
        return False
    if is_label(line):
        return False
    if get_push_op(line) is not None or get_pop_op(line) is not None:
        return False
    if is_control_flow(line):
        return False
    # Check for instructions that modify rsp
    if 'rsp' in s:
        return False
    # Directives are not stack-neutral (they're not instructions)
    for d in ('section ', 'global ', 'db ', 'dq ', 'equ ', 'align ',
              'resq ', 'resb '):
        if s.startswith(d):
            return False
    if s.endswith(':'):
        return False
    return True


def make_mov(dst, src):
    """Generate a mov instruction from push/pop operands.

    Handles qword prefix stripping when the destination is a register
    (register width determines operand size, making qword redundant).
    """
    src_clean = src.strip()
    dst_clean = dst.strip()

    # Strip qword prefix to get inner operand
    src_inner = src_clean[6:].strip() if src_clean.startswith('qword ') else src_clean
    dst_inner = dst_clean[6:].strip() if dst_clean.startswith('qword ') else dst_clean

    # When destination is a register, no size specifier needed
    if is_reg(dst_inner):
        return f'mov {dst_inner}, {src_inner}\n'
    # When source is a register, register width determines size
    if is_reg(src_inner):
        return f'mov {dst_inner}, {src_inner}\n'
    # Both are memory/immediate: need explicit size
    return f'mov qword {dst_inner}, {src_inner}\n'


def writes_register(line, reg):
    """Check if an instruction writes to a specific register.

    Conservatively checks the destination operand (first operand before comma).
    """
    s = line.strip()
    if not s:
        return False
    parts = s.split(None, 1)
    if len(parts) < 2:
        return False
    mnemonic = parts[0].lower()
    operands = parts[1]

    # Instructions that write to the first operand
    dst = operands.split(',')[0].strip()
    if re.search(r'\b' + re.escape(reg) + r'\b', dst):
        return True

    # Some instructions have implicit register writes
    if mnemonic in ('cqo',) and reg in ('rdx', 'rax'):
        return True
    if mnemonic in ('imul', 'idiv') and reg in ('rax', 'rdx'):
        return True

    return False


def optimize_pass(lines):
    """Single optimization pass over the assembly lines."""
    result = []
    i = 0
    n = len(lines)
    changed = False

    while i < n:
        push_op = get_push_op(lines[i])

        if push_op is None:
            result.append(lines[i])
            i += 1
            continue

        # === Pattern 1: Multi-push / multi-pop (N pushes then N pops) ===
        matched_multi = False
        for count in [4, 3, 2]:
            if i + 2 * count > n:
                continue

            # Collect N consecutive pushes
            pushes = []
            ok = True
            for j in range(count):
                p = get_push_op(lines[i + j])
                if p is None:
                    ok = False
                    break
                pushes.append(p)
            if not ok:
                continue

            # Collect N consecutive pops immediately after
            pops = []
            for j in range(count):
                p = get_pop_op(lines[i + count + j])
                if p is None:
                    ok = False
                    break
                pops.append(p)
            if not ok:
                continue

            # Convert using LIFO ordering: pops[0] <- pushes[count-1], etc.
            can_convert = True
            movs = []
            for j in range(count):
                src = pushes[count - 1 - j]
                dst = pops[j]
                if src.strip() == dst.strip():
                    # Self push/pop: eliminate entirely
                    pass
                elif is_reg(dst.strip()) or is_reg(src.strip()):
                    movs.append(make_mov(dst, src))
                else:
                    # Can't convert mem-to-mem to a single mov
                    can_convert = False
                    break

            if can_convert:
                result.extend(movs)
                i += 2 * count
                changed = True
                matched_multi = True
                break

        if matched_multi:
            continue

        # === Pattern 2: Adjacent push/pop pair ===
        if i + 1 < n:
            pop_op = get_pop_op(lines[i + 1])
            if pop_op is not None:
                if push_op.strip() == pop_op.strip():
                    # push X; pop X -> eliminate both
                    i += 2
                    changed = True
                    continue
                elif is_reg(pop_op.strip()) or is_reg(push_op.strip()):
                    # push SRC; pop DST -> mov DST, SRC
                    result.append(make_mov(pop_op, push_op))
                    i += 2
                    changed = True
                    continue

        # === Pattern 3: Look-through optimization ===
        # push SRC; <stack-neutral instrs>; pop DST
        lookthrough_done = False
        for gap in range(1, 5):
            target = i + gap + 1
            if target >= n:
                break

            # All intermediate lines must be stack-neutral
            intermediates_ok = True
            for k in range(i + 1, target):
                if not is_stack_neutral(lines[k]):
                    intermediates_ok = False
                    break
            if not intermediates_ok:
                break

            pop_op_lt = get_pop_op(lines[target])
            if pop_op_lt is None:
                continue

            if push_op.strip() == pop_op_lt.strip():
                # push X; <neutral>; pop X -> just <neutral>
                for k in range(i + 1, target):
                    result.append(lines[k])
                i = target + 1
                changed = True
                lookthrough_done = True
                break

            if is_reg(pop_op_lt.strip()):
                dst_reg = pop_op_lt.strip()
                safe = True

                # Intermediate instructions must not write to dst register
                for k in range(i + 1, target):
                    if writes_register(lines[k], dst_reg):
                        safe = False
                        break

                # If source is a register, intermediates must not write to it
                if safe and is_reg(push_op.strip()):
                    src_reg = push_op.strip()
                    for k in range(i + 1, target):
                        if writes_register(lines[k], src_reg):
                            safe = False
                            break

                if safe:
                    # Keep intermediates, add mov at end
                    for k in range(i + 1, target):
                        result.append(lines[k])
                    result.append(make_mov(pop_op_lt, push_op))
                    i = target + 1
                    changed = True
                    lookthrough_done = True
                    break

        if lookthrough_done:
            continue

        # No optimization found for this line
        result.append(lines[i])
        i += 1

    return result, changed


def optimize(lines):
    """Run optimization passes until convergence."""
    for _ in range(50):
        lines, changed = optimize_pass(lines)
        if not changed:
            break
    return lines


if __name__ == '__main__':
    lines = sys.stdin.readlines()
    optimized = optimize(lines)
    sys.stdout.writelines(optimized)
