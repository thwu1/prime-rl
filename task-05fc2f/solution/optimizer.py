#!/usr/bin/env python3
"""
Peephole optimizer for chibicc-generated x86-64 assembly.

Applies iterative passes of safe local transformations:
  1. LEA+load folding (lea disp, %rax + load (%rax), %rax -> load disp, %rax)
  2. Integer push/pop elimination with look-ahead window
  3. Floating-point push/pop elimination (sub/movsd...movsd/add)
  4. Condition-jump folding (setCC + movzbl + cmp $0 + je/jne -> jCC)
  5. Self-move removal (mov %reg, %reg)
  6. Redundant jump elimination (jmp to immediately following label)
"""

import sys
import re

# ── Register alias families ──────────────────────────────────────────────────
_FAMILIES = [
    frozenset({"%rax", "%eax", "%ax", "%al", "%ah"}),
    frozenset({"%rbx", "%ebx", "%bx", "%bl", "%bh"}),
    frozenset({"%rcx", "%ecx", "%cx", "%cl", "%ch"}),
    frozenset({"%rdx", "%edx", "%dx", "%dl", "%dh"}),
    frozenset({"%rsi", "%esi", "%si", "%sil"}),
    frozenset({"%rdi", "%edi", "%di", "%dil"}),
    frozenset({"%rsp", "%esp", "%sp", "%spl"}),
    frozenset({"%rbp", "%ebp", "%bp", "%bpl"}),
    frozenset({"%r8", "%r8d", "%r8w", "%r8b"}),
    frozenset({"%r9", "%r9d", "%r9w", "%r9b"}),
    frozenset({"%r10", "%r10d", "%r10w", "%r10b"}),
    frozenset({"%r11", "%r11d", "%r11w", "%r11b"}),
    frozenset({"%r12", "%r12d", "%r12w", "%r12b"}),
    frozenset({"%r13", "%r13d", "%r13w", "%r13b"}),
    frozenset({"%r14", "%r14d", "%r14w", "%r14b"}),
    frozenset({"%r15", "%r15d", "%r15w", "%r15b"}),
]

_REG_TO_FAMILY = {}
for _fam in _FAMILIES:
    for _r in _fam:
        _REG_TO_FAMILY[_r] = _fam

# ── Condition code inversion ─────────────────────────────────────────────────
_CC_INVERT = {
    'e': 'ne', 'ne': 'e',
    'l': 'ge', 'ge': 'l',
    'le': 'g', 'g': 'le',
    'b': 'ae', 'ae': 'b',
    'be': 'a', 'a': 'be',
    'z': 'nz', 'nz': 'z',
    's': 'ns', 'ns': 's',
    'o': 'no', 'no': 'o',
    'p': 'np', 'np': 'p',
}


def _get_family(reg):
    return _REG_TO_FAMILY.get(reg, frozenset({reg}))


def _line_touches_reg(line, reg):
    """True if *line* references any alias of *reg*."""
    for alias in _get_family(reg):
        if alias in line:
            return True
    return False


def _is_any_label(line):
    s = line.strip()
    return bool(s) and s.endswith(":")


_BRANCH_RE = re.compile(
    r"\s+(call|ret|syscall|jmp|je|jne|jz|jnz|jl|jle|jg|jge|ja|jae|jb|jbe"
    r"|js|jns|jo|jno|jp|jnp|jrcxz)\b"
)


def _is_branch(line):
    return bool(_BRANCH_RE.match(line))


# ── Optimization passes ─────────────────────────────────────────────────────

def _opt_lea_load_fold(lines):
    """Fold adjacent lea DISP, %rax + load (%rax), %DEST -> load DISP, %DEST.

    chibicc emits lea DISP(%rbp), %rax (gen_addr) immediately followed by
    a load through (%rax) for every variable read.  Folding these into a
    single instruction with the displacement addressing mode eliminates one
    instruction per variable access.

    Safety: only applied when DEST is %rax or %eax, so the intermediate
    address in %rax is dead after the load overwrites it.
    """
    result = []
    i = 0
    n = len(lines)
    changed = False

    while i < n:
        if i + 1 < n:
            m_lea = re.match(r'(\s+)lea\s+([^,]+),\s*%rax\s*$', lines[i])
            if m_lea:
                indent = m_lea.group(1)
                mem_op = m_lea.group(2)
                m_load = re.match(
                    r'\s+(movsxd|movslq|movsbl|movswl|movzbl|movzwl'
                    r'|movl|movq|mov)\s+\(%rax\),\s*%(rax|eax)\s*$',
                    lines[i + 1],
                )
                if m_load:
                    insn = m_load.group(1)
                    dest = '%' + m_load.group(2)
                    result.append(f'{indent}{insn} {mem_op}, {dest}\n')
                    i += 2
                    changed = True
                    continue

        result.append(lines[i])
        i += 1

    return result, changed


def _opt_push_pop(lines):
    """Eliminate integer push/pop pairs with a look-ahead window."""
    result = []
    i = 0
    n = len(lines)
    changed = False

    while i < n:
        m_push = re.match(r"(\s+)push\s+(%\w+)\s*$", lines[i])
        if not m_push:
            result.append(lines[i])
            i += 1
            continue

        indent = m_push.group(1)
        push_reg = m_push.group(2)
        matched = False

        for j in range(i + 1, min(i + 20, n)):
            # Stop at labels or branches — cannot cross basic-block boundaries
            if _is_any_label(lines[j]) or _is_branch(lines[j]):
                break
            # Stop at nested push (handle innermost first on next iteration)
            if re.match(r"\s+push\s+", lines[j]):
                break

            m_pop = re.match(r"\s+pop\s+(%\w+)\s*$", lines[j])
            if not m_pop:
                continue

            pop_reg = m_pop.group(1)

            # Verify none of the middle instructions touch pop_reg or %rsp family
            middle = lines[i + 1 : j]
            safe = True
            for mid in middle:
                if _line_touches_reg(mid, pop_reg) or _line_touches_reg(mid, "%rsp"):
                    safe = False
                    break
            if not safe:
                break  # unsafe — keep this push as-is

            # Safe to replace
            if push_reg == pop_reg:
                result.extend(middle)
            else:
                result.append(f"{indent}mov {push_reg}, {pop_reg}\n")
                result.extend(middle)
            i = j + 1
            matched = True
            changed = True
            break

        if not matched:
            result.append(lines[i])
            i += 1

    return result, changed


def _opt_fp_push_pop(lines):
    """Eliminate floating-point push/pop sequences.

    Pattern:
        sub $8, %rsp
        movsd %xmmA, (%rsp)
        ... (no stack/push/pop touching)
        movsd (%rsp), %xmmB
        add $8, %rsp
    """
    result = []
    i = 0
    n = len(lines)
    changed = False

    while i < n:
        if not re.match(r"\s+sub\s+\$8,\s*%rsp\s*$", lines[i]):
            result.append(lines[i])
            i += 1
            continue

        if i + 1 >= n:
            result.append(lines[i])
            i += 1
            continue

        m_store = re.match(r"(\s+)movsd\s+(%xmm\d+),\s*\(%rsp\)\s*$", lines[i + 1])
        if not m_store:
            result.append(lines[i])
            i += 1
            continue

        indent = m_store.group(1)
        src_xmm = m_store.group(2)
        matched = False

        for j in range(i + 2, min(i + 20, n)):
            if _is_any_label(lines[j]) or _is_branch(lines[j]):
                break
            if re.match(r"\s+(push|pop|sub\s+.*%rsp|add\s+.*%rsp)\b", lines[j]):
                # Avoid crossing stack-manipulating instructions
                m_load = re.match(r"\s+movsd\s+\(%rsp\),\s*(%xmm\d+)\s*$", lines[j])
                if m_load and j + 1 < n:
                    m_add = re.match(r"\s+add\s+\$8,\s*%rsp\s*$", lines[j + 1])
                    if m_add:
                        dst_xmm = m_load.group(1)
                        middle = lines[i + 2 : j]
                        if src_xmm == dst_xmm:
                            result.extend(middle)
                        else:
                            result.append(f"{indent}movsd {src_xmm}, {dst_xmm}\n")
                            result.extend(middle)
                        i = j + 2
                        matched = True
                        changed = True
                break

            m_load = re.match(r"\s+movsd\s+\(%rsp\),\s*(%xmm\d+)\s*$", lines[j])
            if m_load and j + 1 < n:
                m_add = re.match(r"\s+add\s+\$8,\s*%rsp\s*$", lines[j + 1])
                if m_add:
                    dst_xmm = m_load.group(1)
                    # Check middle safety (no (%rsp) refs, no push/pop)
                    middle = lines[i + 2 : j]
                    safe = True
                    for mid in middle:
                        if "(%rsp)" in mid or re.match(r"\s+(push|pop)\s+", mid):
                            safe = False
                            break
                    if safe:
                        if src_xmm == dst_xmm:
                            result.extend(middle)
                        else:
                            result.append(f"{indent}movsd {src_xmm}, {dst_xmm}\n")
                            result.extend(middle)
                        i = j + 2
                        matched = True
                        changed = True
                break

        if not matched:
            result.append(lines[i])
            i += 1

    return result, changed


def _opt_cond_jump(lines):
    """Fold setCC + movzbl + cmp $0 + je/jne into a single conditional jump.

    chibicc evaluates boolean expressions into %al via setCC, zero-extends
    to %eax, then tests with cmp $0 + je/jne.  This can be replaced by a
    single conditional jump using the flags from the preceding comparison:

      setCC %al; movzbl %al, %eax; cmp $0, %rax; je  TARGET -> j(NOT CC) TARGET
      setCC %al; movzbl %al, %eax; cmp $0, %rax; jne TARGET -> jCC TARGET

    Safety: setCC and movzbl do not modify flags, so the flags from the
    preceding cmp/test are still live when the folded jCC executes.
    """
    result = []
    i = 0
    n = len(lines)
    changed = False

    while i < n:
        if i + 3 < n:
            m_set = re.match(
                r'(\s+)set(e|ne|l|le|g|ge|b|be|a|ae|z|nz|s|ns)\s+%al\s*$',
                lines[i],
            )
            if m_set:
                indent = m_set.group(1)
                cc = m_set.group(2)

                if (re.match(r'\s+movzbl\s+%al,\s*%eax\s*$', lines[i + 1])
                        and re.match(r'\s+cmp\s+\$0,\s*%(rax|eax)\s*$', lines[i + 2])):

                    m_jmp = re.match(r'\s+(je|jne)\s+(\S+)\s*$', lines[i + 3])
                    if m_jmp:
                        jtype = m_jmp.group(1)
                        target = m_jmp.group(2)

                        if jtype == 'je':
                            new_cc = _CC_INVERT.get(cc)
                        else:  # jne
                            new_cc = cc

                        if new_cc:
                            result.append(f'{indent}j{new_cc} {target}\n')
                            i += 4
                            changed = True
                            continue

        result.append(lines[i])
        i += 1

    return result, changed


def _opt_self_move(lines):
    """Remove mov %reg, %reg (no-ops)."""
    result = []
    changed = False
    for line in lines:
        m = re.match(r"\s+mov[lqwb]?\s+(%\w+),\s*(%\w+)\s*$", line)
        if m and m.group(1) == m.group(2):
            changed = True
            continue
        result.append(line)
    return result, changed


def _opt_redundant_jmp(lines):
    """Remove jmp to an immediately following label."""
    result = []
    i = 0
    n = len(lines)
    changed = False

    while i < n:
        m_jmp = re.match(r"\s+jmp\s+(\S+)\s*$", lines[i])
        if m_jmp:
            target = m_jmp.group(1)
            # Look ahead past blank lines and .loc directives for the label
            found_label = False
            for k in range(i + 1, min(i + 8, n)):
                stripped = lines[k].strip()
                if not stripped or stripped.startswith(".loc "):
                    continue
                if stripped == target + ":":
                    found_label = True
                break

            if found_label:
                changed = True
                i += 1  # skip the jmp; the label will be emitted normally
            else:
                result.append(lines[i])
                i += 1
        else:
            result.append(lines[i])
            i += 1

    return result, changed


# ── Main driver ──────────────────────────────────────────────────────────────

def optimize(lines):
    """Apply all optimization passes iteratively until fixpoint."""
    passes = [
        _opt_lea_load_fold,
        _opt_push_pop,
        _opt_fp_push_pop,
        _opt_cond_jump,
        _opt_self_move,
        _opt_redundant_jmp,
    ]
    for _ in range(30):  # bounded iteration
        any_changed = False
        for pass_fn in passes:
            lines, changed = pass_fn(lines)
            any_changed = any_changed or changed
        if not any_changed:
            break
    return lines


def main():
    if len(sys.argv) < 2:
        print("Usage: optimize <input.s>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        lines = f.readlines()

    lines = optimize(lines)
    sys.stdout.writelines(lines)


if __name__ == "__main__":
    main()
