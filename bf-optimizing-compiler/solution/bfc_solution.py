#!/usr/bin/env python3
"""BF Multi-Backend Compiler - Reference Solution.

"""
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Tuple, Optional


class OpKind(Enum):
    ADD_PTR = auto()
    SUB_PTR = auto()
    ADD_DATA = auto()
    SUB_DATA = auto()
    OUTPUT = auto()
    INPUT = auto()
    LOOP_START = auto()
    LOOP_END = auto()
    SET = auto()
    MUL_ADD = auto()
    SCAN_RIGHT = auto()
    SCAN_LEFT = auto()


@dataclass
class Op:
    kind: OpKind
    arg1: int = 0
    arg2: int = 0


# -- Parsing -----------------------------------------------------------------

def parse_bf(source: str) -> List[str]:
    return [c for c in source if c in "><+-.,[]"]


def bf_to_ir(chars: List[str]) -> List[Op]:
    ops = []
    mapping = {
        ">": OpKind.ADD_PTR, "<": OpKind.SUB_PTR,
        "+": OpKind.ADD_DATA, "-": OpKind.SUB_DATA,
        ".": OpKind.OUTPUT, ",": OpKind.INPUT,
        "[": OpKind.LOOP_START, "]": OpKind.LOOP_END,
    }
    for c in chars:
        k = mapping[c]
        if k in (OpKind.OUTPUT, OpKind.INPUT, OpKind.LOOP_START, OpKind.LOOP_END):
            ops.append(Op(k))
        else:
            ops.append(Op(k, 1))
    return ops


# -- Optimization passes -----------------------------------------------------

def pass_contraction(ops: List[Op]) -> Tuple[List[Op], int]:
    if not ops:
        return [], 0
    result = []
    count = 0
    i = 0
    ptr_kinds = {OpKind.ADD_PTR, OpKind.SUB_PTR}
    data_kinds = {OpKind.ADD_DATA, OpKind.SUB_DATA}

    while i < len(ops):
        op = ops[i]
        if op.kind in ptr_kinds:
            net = op.arg1 if op.kind == OpKind.ADD_PTR else -op.arg1
            j = i + 1
            while j < len(ops) and ops[j].kind in ptr_kinds:
                net += ops[j].arg1 if ops[j].kind == OpKind.ADD_PTR else -ops[j].arg1
                j += 1
            if j > i + 1:
                count += 1
            if net > 0:
                result.append(Op(OpKind.ADD_PTR, net))
            elif net < 0:
                result.append(Op(OpKind.SUB_PTR, -net))
            i = j
        elif op.kind in data_kinds:
            net = op.arg1 if op.kind == OpKind.ADD_DATA else -op.arg1
            j = i + 1
            while j < len(ops) and ops[j].kind in data_kinds:
                net += ops[j].arg1 if ops[j].kind == OpKind.ADD_DATA else -ops[j].arg1
                j += 1
            if j > i + 1:
                count += 1
            if net > 0:
                result.append(Op(OpKind.ADD_DATA, net))
            elif net < 0:
                result.append(Op(OpKind.SUB_DATA, -net))
            i = j
        else:
            result.append(Op(op.kind, op.arg1, op.arg2))
            i += 1
    return result, count


def pass_clear_loop(ops: List[Op]) -> Tuple[List[Op], int]:
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if (i + 2 < len(ops)
                and ops[i].kind == OpKind.LOOP_START
                and ops[i + 1].kind in (OpKind.ADD_DATA, OpKind.SUB_DATA)
                and ops[i + 1].arg1 == 1
                and ops[i + 2].kind == OpKind.LOOP_END):
            result.append(Op(OpKind.SET, 0))
            count += 1
            i += 3
        else:
            result.append(Op(ops[i].kind, ops[i].arg1, ops[i].arg2))
            i += 1
    return result, count


def _analyze_copy_mul(body: List[Op]) -> Optional[List[Op]]:
    forbidden = {
        OpKind.OUTPUT, OpKind.INPUT,
        OpKind.LOOP_START, OpKind.LOOP_END,
        OpKind.SET, OpKind.MUL_ADD, OpKind.SCAN_RIGHT, OpKind.SCAN_LEFT,
    }
    for op in body:
        if op.kind in forbidden:
            return None

    ptr = 0
    changes: dict = {}
    for op in body:
        if op.kind == OpKind.ADD_PTR:
            ptr += op.arg1
        elif op.kind == OpKind.SUB_PTR:
            ptr -= op.arg1
        elif op.kind == OpKind.ADD_DATA:
            changes[ptr] = changes.get(ptr, 0) + op.arg1
        elif op.kind == OpKind.SUB_DATA:
            changes[ptr] = changes.get(ptr, 0) - op.arg1

    if ptr != 0:
        return None
    if changes.get(0, 0) != -1:
        return None

    mul_ops = []
    for offset in sorted(changes.keys()):
        if offset == 0:
            continue
        factor = changes[offset]
        if factor != 0:
            mul_ops.append(Op(OpKind.MUL_ADD, offset, factor))
    return mul_ops


def pass_copy_mul_loop(ops: List[Op]) -> Tuple[List[Op], int]:
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if ops[i].kind == OpKind.LOOP_START:
            j = i + 1
            depth = 1
            while j < len(ops) and depth > 0:
                if ops[j].kind == OpKind.LOOP_START:
                    depth += 1
                elif ops[j].kind == OpKind.LOOP_END:
                    depth -= 1
                j += 1
            body = ops[i + 1:j - 1]
            mul_ops = _analyze_copy_mul(body)
            if mul_ops is not None:
                result.extend(mul_ops)
                result.append(Op(OpKind.SET, 0))
                count += 1
                i = j
            else:
                result.append(Op(ops[i].kind, ops[i].arg1, ops[i].arg2))
                i += 1
        else:
            result.append(Op(ops[i].kind, ops[i].arg1, ops[i].arg2))
            i += 1
    return result, count


def pass_scan_loop(ops: List[Op]) -> Tuple[List[Op], int]:
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if (i + 2 < len(ops)
                and ops[i].kind == OpKind.LOOP_START
                and ops[i + 2].kind == OpKind.LOOP_END):
            inner = ops[i + 1]
            if inner.kind == OpKind.ADD_PTR:
                result.append(Op(OpKind.SCAN_RIGHT, inner.arg1))
                count += 1
                i += 3
                continue
            elif inner.kind == OpKind.SUB_PTR:
                result.append(Op(OpKind.SCAN_LEFT, inner.arg1))
                count += 1
                i += 3
                continue
        result.append(Op(ops[i].kind, ops[i].arg1, ops[i].arg2))
        i += 1
    return result, count


def pass_set_fold(ops: List[Op]) -> Tuple[List[Op], int]:
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if (i + 1 < len(ops)
                and ops[i].kind == OpKind.SET and ops[i].arg1 == 0):
            nxt = ops[i + 1]
            if nxt.kind == OpKind.ADD_DATA:
                result.append(Op(OpKind.SET, nxt.arg1 % 256))
                count += 1
                i += 2
                continue
            elif nxt.kind == OpKind.SUB_DATA:
                result.append(Op(OpKind.SET, (256 - nxt.arg1) % 256))
                count += 1
                i += 2
                continue
        result.append(Op(ops[i].kind, ops[i].arg1, ops[i].arg2))
        i += 1
    return result, count


def optimize(ops: List[Op]) -> Tuple[List[Op], dict]:
    stats = {}
    ops, n = pass_contraction(ops)
    stats["contraction"] = n
    ops, n = pass_clear_loop(ops)
    stats["clear_loop"] = n
    ops, n = pass_copy_mul_loop(ops)
    stats["copy_mul_loop"] = n
    ops, n = pass_scan_loop(ops)
    stats["scan_loop"] = n
    ops, n = pass_set_fold(ops)
    stats["set_fold"] = n
    return ops, stats


# -- IR interpreter ----------------------------------------------------------

def execute_ir(ops: List[Op], input_data: bytes = b"") -> bytes:
    TAPE = 30000
    mem = bytearray(TAPE)
    ptr = 0
    pc = 0
    out = bytearray()
    inp_pos = 0

    jumps = {}
    stack = []
    for i, op in enumerate(ops):
        if op.kind == OpKind.LOOP_START:
            stack.append(i)
        elif op.kind == OpKind.LOOP_END:
            j = stack.pop()
            jumps[j] = i
            jumps[i] = j

    while pc < len(ops):
        op = ops[pc]
        k = op.kind
        if k == OpKind.ADD_PTR:
            ptr += op.arg1
        elif k == OpKind.SUB_PTR:
            ptr -= op.arg1
        elif k == OpKind.ADD_DATA:
            mem[ptr] = (mem[ptr] + op.arg1) % 256
        elif k == OpKind.SUB_DATA:
            mem[ptr] = (mem[ptr] - op.arg1) % 256
        elif k == OpKind.OUTPUT:
            out.append(mem[ptr])
        elif k == OpKind.INPUT:
            if inp_pos < len(input_data):
                mem[ptr] = input_data[inp_pos]
                inp_pos += 1
            else:
                mem[ptr] = 0
        elif k == OpKind.LOOP_START:
            if mem[ptr] == 0:
                pc = jumps[pc]
        elif k == OpKind.LOOP_END:
            if mem[ptr] != 0:
                pc = jumps[pc]
        elif k == OpKind.SET:
            mem[ptr] = op.arg1 % 256
        elif k == OpKind.MUL_ADD:
            target = ptr + op.arg1
            mem[target] = (mem[target] + mem[ptr] * op.arg2) % 256
        elif k == OpKind.SCAN_RIGHT:
            while mem[ptr] != 0:
                ptr += op.arg1
        elif k == OpKind.SCAN_LEFT:
            while mem[ptr] != 0:
                ptr -= op.arg1
        pc += 1
    return bytes(out)


# -- IR text output ----------------------------------------------------------

def ir_to_string(ops: List[Op]) -> str:
    lines = []
    for op in ops:
        k = op.kind
        if k == OpKind.MUL_ADD:
            lines.append(f"MUL_ADD {op.arg1} {op.arg2}")
        elif k in (OpKind.OUTPUT, OpKind.INPUT, OpKind.LOOP_START, OpKind.LOOP_END):
            lines.append(k.name)
        else:
            lines.append(f"{k.name} {op.arg1}")
    return "\n".join(lines)


# -- C code generation -------------------------------------------------------

def ir_to_c(ops: List[Op]) -> str:
    lines = [
        "#include <stdio.h>",
        "#include <string.h>",
        "",
        "int main(void) {",
        "    unsigned char mem[30000];",
        "    memset(mem, 0, sizeof(mem));",
        "    unsigned char *ptr = mem;",
        "",
    ]
    indent = 1

    for op in ops:
        pad = "    " * indent
        k = op.kind
        if k == OpKind.ADD_PTR:
            lines.append(f"{pad}ptr += {op.arg1};")
        elif k == OpKind.SUB_PTR:
            lines.append(f"{pad}ptr -= {op.arg1};")
        elif k == OpKind.ADD_DATA:
            lines.append(f"{pad}*ptr += {op.arg1};")
        elif k == OpKind.SUB_DATA:
            lines.append(f"{pad}*ptr -= {op.arg1};")
        elif k == OpKind.OUTPUT:
            lines.append(f"{pad}putchar(*ptr);")
        elif k == OpKind.INPUT:
            lines.append(f"{pad}*ptr = getchar();")
        elif k == OpKind.LOOP_START:
            lines.append(f"{pad}while (*ptr) {{")
            indent += 1
        elif k == OpKind.LOOP_END:
            indent -= 1
            pad = "    " * indent
            lines.append(f"{pad}}}")
        elif k == OpKind.SET:
            lines.append(f"{pad}*ptr = {op.arg1};")
        elif k == OpKind.MUL_ADD:
            offset = op.arg1
            factor = op.arg2
            if offset >= 0:
                ptr_expr = f"*(ptr + {offset})"
            else:
                ptr_expr = f"*(ptr - {-offset})"
            if factor >= 0:
                lines.append(f"{pad}{ptr_expr} += (*ptr) * {factor};")
            else:
                lines.append(f"{pad}{ptr_expr} -= (*ptr) * {-factor};")
        elif k == OpKind.SCAN_RIGHT:
            lines.append(f"{pad}while (*ptr) ptr += {op.arg1};")
        elif k == OpKind.SCAN_LEFT:
            lines.append(f"{pad}while (*ptr) ptr -= {op.arg1};")

    lines.append("")
    lines.append("    return 0;")
    lines.append("}")
    return "\n".join(lines)


# -- x86-64 assembly generation (GNU as / AT&T syntax) -----------------------

def ir_to_asm(ops: List[Op]) -> str:
    lines = []
    lines.append("    .text")
    lines.append("    .globl main")
    lines.append("    .type main, @function")
    lines.append("main:")
    lines.append("    pushq %rbx")
    lines.append("    leaq tape(%rip), %rbx")

    label_n = [0]
    loop_stack = []

    def fresh():
        n = label_n[0]
        label_n[0] += 1
        return n

    for op in ops:
        k = op.kind
        if k == OpKind.ADD_PTR:
            lines.append(f"    addq ${op.arg1}, %rbx")
        elif k == OpKind.SUB_PTR:
            lines.append(f"    subq ${op.arg1}, %rbx")
        elif k == OpKind.ADD_DATA:
            lines.append(f"    addb ${op.arg1 & 0xFF}, (%rbx)")
        elif k == OpKind.SUB_DATA:
            lines.append(f"    subb ${op.arg1 & 0xFF}, (%rbx)")
        elif k == OpKind.OUTPUT:
            lines.append("    movzbl (%rbx), %edi")
            lines.append("    call putchar@PLT")
        elif k == OpKind.INPUT:
            lines.append("    call getchar@PLT")
            lines.append("    movb %al, (%rbx)")
        elif k == OpKind.LOOP_START:
            n = fresh()
            loop_stack.append(n)
            lines.append(f".L{n}b:")
            lines.append("    cmpb $0, (%rbx)")
            lines.append(f"    je .L{n}e")
        elif k == OpKind.LOOP_END:
            n = loop_stack.pop()
            lines.append(f"    jmp .L{n}b")
            lines.append(f".L{n}e:")
        elif k == OpKind.SET:
            lines.append(f"    movb ${op.arg1 & 0xFF}, (%rbx)")
        elif k == OpKind.MUL_ADD:
            offset = op.arg1
            factor = op.arg2
            lines.append("    movzbl (%rbx), %eax")
            if factor == 1:
                lines.append(f"    addb %al, {offset}(%rbx)")
            elif factor == -1:
                lines.append(f"    subb %al, {offset}(%rbx)")
            else:
                lines.append(f"    imull ${factor}, %eax, %eax")
                lines.append(f"    addb %al, {offset}(%rbx)")
        elif k == OpKind.SCAN_RIGHT:
            n = fresh()
            lines.append(f".L{n}b:")
            lines.append("    cmpb $0, (%rbx)")
            lines.append(f"    je .L{n}e")
            lines.append(f"    addq ${op.arg1}, %rbx")
            lines.append(f"    jmp .L{n}b")
            lines.append(f".L{n}e:")
        elif k == OpKind.SCAN_LEFT:
            n = fresh()
            lines.append(f".L{n}b:")
            lines.append("    cmpb $0, (%rbx)")
            lines.append(f"    je .L{n}e")
            lines.append(f"    subq ${op.arg1}, %rbx")
            lines.append(f"    jmp .L{n}b")
            lines.append(f".L{n}e:")

    lines.append("    xorl %eax, %eax")
    lines.append("    popq %rbx")
    lines.append("    ret")
    lines.append("    .section .bss")
    lines.append("    .lcomm tape, 30000")
    return "\n".join(lines)


# -- Main --------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 bfc.py <mode> <file>", file=sys.stderr)
        print("Modes: run, ir, gen-c, gen-asm, stats", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    filename = sys.argv[2]

    with open(filename) as f:
        source = f.read()

    chars = parse_bf(source)
    ops = bf_to_ir(chars)
    ops, stats = optimize(ops)

    if mode == "run":
        output = execute_ir(ops)
        sys.stdout.buffer.write(output)
    elif mode == "ir":
        print(ir_to_string(ops))
    elif mode == "gen-c":
        print(ir_to_c(ops))
    elif mode == "gen-asm":
        print(ir_to_asm(ops))
    elif mode == "stats":
        for key in ["contraction", "clear_loop", "copy_mul_loop", "scan_loop", "set_fold"]:
            print(f"{key}: {stats[key]}")
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
