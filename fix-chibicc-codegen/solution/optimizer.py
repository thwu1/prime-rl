#!/usr/bin/env python3
"""
Peephole optimizer for chibicc's x86-64 AT&T assembly output.

chibicc uses a stack-based code generator: every binary operation pushes
the left operand onto the stack, evaluates the right operand into %rax,
then pops the left operand into %rdi.  Every local variable access is a
two-instruction lea + load sequence.  This produces correct but
redundant assembly.

This optimizer applies three passes iteratively until convergence:

1. **lea+load folding** – `lea N(%rbp),%rax` immediately followed by a
   load from `(%rax)` is collapsed into a single load from `N(%rbp)`.

2. **push/pop elimination** – push/pop pairs are replaced with `mov`
   (or deleted when source == dest), provided no intermediate instruction
   references the pop's destination register (checked with full register
   aliasing: %rdi/%edi/%di/%dil share a physical register).

3. **identity-move removal** – `mov %r??, %r??` for 64-bit registers
   (which is a true NOP; 32-bit `mov %eax,%eax` zero-extends and must
   NOT be removed).

Reads from stdin, writes to stdout.
"""

import sys
import re

# -----------------------------------------------------------------------
# Register alias tables
# -----------------------------------------------------------------------
_REG_FAMILIES = {
    "rax": ["%rax", "%eax", "%ax", "%al", "%ah"],
    "rbx": ["%rbx", "%ebx", "%bx", "%bl", "%bh"],
    "rcx": ["%rcx", "%ecx", "%cx", "%cl", "%ch"],
    "rdx": ["%rdx", "%edx", "%dx", "%dl", "%dh"],
    "rsi": ["%rsi", "%esi", "%si", "%sil"],
    "rdi": ["%rdi", "%edi", "%di", "%dil"],
    "rsp": ["%rsp", "%esp", "%sp", "%spl"],
    "rbp": ["%rbp", "%ebp", "%bp", "%bpl"],
    "r8":  ["%r8",  "%r8d",  "%r8w",  "%r8b"],
    "r9":  ["%r9",  "%r9d",  "%r9w",  "%r9b"],
    "r10": ["%r10", "%r10d", "%r10w", "%r10b"],
    "r11": ["%r11", "%r11d", "%r11w", "%r11b"],
    "r12": ["%r12", "%r12d", "%r12w", "%r12b"],
    "r13": ["%r13", "%r13d", "%r13w", "%r13b"],
    "r14": ["%r14", "%r14d", "%r14w", "%r14b"],
    "r15": ["%r15", "%r15d", "%r15w", "%r15b"],
}

_ALIAS_MAP: dict[str, list[str]] = {}
for _fam, _regs in _REG_FAMILIES.items():
    for _r in _regs:
        _ALIAS_MAP[_r] = _regs

_64BIT_REGS = {
    "%rax", "%rbx", "%rcx", "%rdx", "%rsi", "%rdi", "%rsp", "%rbp",
    "%r8", "%r9", "%r10", "%r11", "%r12", "%r13", "%r14", "%r15",
}


def _aliases(reg: str) -> list[str]:
    return _ALIAS_MAP.get(reg, [reg])


def _line_refs_reg(line: str, reg: str) -> bool:
    """Does *line* mention any alias of *reg*?"""
    for alias in _aliases(reg):
        if alias in line:
            return True
    return False


# -----------------------------------------------------------------------
# Tiny parsers
# -----------------------------------------------------------------------
_RE_PUSH = re.compile(r"\s+push\s+(%\w+)\s*$")
_RE_POP  = re.compile(r"\s+pop\s+(%\w+)\s*$")


def _parse_push(line: str):
    m = _RE_PUSH.match(line)
    return m.group(1) if m else None


def _parse_pop(line: str):
    m = _RE_POP.match(line)
    return m.group(1) if m else None


def _is_control_flow(line: str) -> bool:
    s = line.strip()
    if s == "ret" or s == "syscall":
        return True
    for kw in ("call ", "ret ", "jmp ", "je ", "jne ", "jl ", "jle ",
               "jg ", "jge ", "ja ", "jae ", "jb ", "jbe ", "js ",
               "jns ", "jo ", "jno ", "jz ", "jnz ", "jp ", "jnp "):
        if s.startswith(kw):
            return True
    return False


def _is_label(line: str) -> bool:
    s = line.strip()
    return bool(s) and s.endswith(":") and not s.startswith("#")


# -----------------------------------------------------------------------
# Pass 1: lea + load folding
# -----------------------------------------------------------------------
_RE_LEA = re.compile(r"(\s+)lea\s+(-?\d+)\(%rbp\),\s*%rax\s*$")
_RE_LOAD2 = re.compile(
    r"\s+(movsxd|movsbl|movzbl|movswl|movzwl|mov|movss|movsd)"
    r"\s+\(%rax\),\s*(%\w+)\s*$"
)
_RE_LOAD1 = re.compile(r"\s+(fldt|flds|fldl)\s+\(%rax\)\s*$")


def _fold_lea_load(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        if i + 1 < len(lines):
            m_lea = _RE_LEA.match(lines[i])
            if m_lea:
                indent = m_lea.group(1)
                offset = m_lea.group(2)
                # two-operand loads
                m2 = _RE_LOAD2.match(lines[i + 1])
                if m2:
                    out.append(f"{indent}{m2.group(1)} {offset}(%rbp), {m2.group(2)}\n")
                    i += 2
                    continue
                # single-operand FP loads
                m1 = _RE_LOAD1.match(lines[i + 1])
                if m1:
                    out.append(f"{indent}{m1.group(1)} {offset}(%rbp)\n")
                    i += 2
                    continue
        out.append(lines[i])
        i += 1
    return out


# -----------------------------------------------------------------------
# Pass 2: push / pop elimination
# -----------------------------------------------------------------------
_MAX_LOOKAHEAD = 50


def _elim_push_pop(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        push_reg = _parse_push(lines[i])
        if push_reg is None:
            out.append(lines[i])
            i += 1
            continue

        # Find matching pop respecting nesting depth
        depth = 0
        matched = -1
        for j in range(i + 1, min(i + _MAX_LOOKAHEAD, len(lines))):
            if _parse_push(lines[j]) is not None:
                depth += 1
            elif _parse_pop(lines[j]) is not None:
                if depth > 0:
                    depth -= 1
                else:
                    matched = j
                    break
            elif _is_label(lines[j]):
                break
            elif _is_control_flow(lines[j]):
                break

        if matched == -1:
            out.append(lines[i])
            i += 1
            continue

        pop_reg = _parse_pop(lines[matched])
        mid = lines[i + 1 : matched]

        # Safety: no intermediate line may reference the pop register
        safe = True
        for ml in mid:
            if _is_label(ml):
                safe = False
                break
            if _is_control_flow(ml):
                safe = False
                break
            # Inner push/pop: check explicitly
            inner_pop = _parse_pop(ml)
            if inner_pop is not None:
                if _line_refs_reg(ml, pop_reg):
                    safe = False
                    break
                continue
            inner_push = _parse_push(ml)
            if inner_push is not None:
                if _line_refs_reg(ml, pop_reg):
                    safe = False
                    break
                continue
            # Regular instruction
            if _line_refs_reg(ml, pop_reg):
                safe = False
                break

        if safe:
            if push_reg != pop_reg:
                out.append(f"  mov {push_reg}, {pop_reg}\n")
            out.extend(mid)
            i = matched + 1
        else:
            out.append(lines[i])
            i += 1

    return out


# -----------------------------------------------------------------------
# Pass 3: identity-move removal (64-bit only — 32-bit has side effects)
# -----------------------------------------------------------------------
_RE_MOV_ID = re.compile(r"\s+mov\s+(%\w+),\s*(%\w+)\s*$")


def _remove_identity_mov(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        m = _RE_MOV_ID.match(line)
        if m and m.group(1) == m.group(2) and m.group(1) in _64BIT_REGS:
            continue
        out.append(line)
    return out


# -----------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------
def optimize(lines: list[str]) -> list[str]:
    cur = list(lines)
    for _ in range(15):
        prev = cur[:]
        cur = _fold_lea_load(cur)
        cur = _elim_push_pop(cur)
        cur = _remove_identity_mov(cur)
        if cur == prev:
            break
    return cur


def main() -> None:
    lines = sys.stdin.readlines()
    result = optimize(lines)
    sys.stdout.writelines(result)


if __name__ == "__main__":
    main()
