#!/usr/bin/env python3
"""BF optimizing compiler -- bytecode IR with optimization passes and x86-64 NASM backend.

Compiles Brainfuck source to an intermediate bytecode representation,
applies optimization passes, and can execute via bytecode VM or generate
native x86-64 Linux executables via NASM.

Usage:
    python3 bfcomp.py run <file.bf>           Execute via bytecode VM
    python3 bfcomp.py bytecode <file.bf>      Print optimized bytecode listing
    python3 bfcomp.py stats <file.bf>         Print optimization statistics (JSON)
    python3 bfcomp.py asm <file.bf> <out.asm> Generate NASM x86-64 assembly
    python3 bfcomp.py build <file.bf> <out>   Build native executable (nasm+ld)
"""

import sys
import json
import os
import subprocess
import tempfile


class Op:
    """A single bytecode instruction."""
    __slots__ = ['type', 'arg1', 'arg2']

    def __init__(self, op_type, arg1=0, arg2=0):
        self.type = op_type
        self.arg1 = arg1
        self.arg2 = arg2

    def __str__(self):
        if self.type == 'MUL_COPY':
            return f"MUL_COPY {self.arg1} {self.arg2}"
        elif self.type in ('INC_PTR', 'DEC_PTR', 'INC_DATA', 'DEC_DATA', 'SCAN'):
            return f"{self.type} {self.arg1}"
        elif self.type in ('JUMP_IF_ZERO', 'JUMP_IF_NONZERO'):
            return f"{self.type} {self.arg1}"
        return self.type


# --- Bytecode IR instruction types ---
#
# Basic ops:
#   INC_PTR n        move data pointer right by n
#   DEC_PTR n        move data pointer left by n
#   INC_DATA n       add n to current cell
#   DEC_DATA n       subtract n from current cell
#   READ_STDIN       read one byte from stdin into current cell
#   WRITE_STDOUT     write current cell byte to stdout
#
# Control flow:
#   JUMP_IF_ZERO t   jump to target t if current cell is zero
#   JUMP_IF_NONZERO t jump to target t if current cell is nonzero
#
# Optimized ops:
#   SET_ZERO         set current cell to zero
#   MUL_COPY o f     add current_cell * f to cell at ptr+o
#   SCAN s           move pointer by s until a zero cell is found


def parse_bf(source):
    """Extract BF instruction characters from source."""
    return [ch for ch in source if ch in '><+-.,[]']


def compile_basic(tokens):
    """Convert BF tokens to basic unoptimized bytecode."""
    ops = []
    for t in tokens:
        if t == '>':   ops.append(Op('INC_PTR', 1))
        elif t == '<': ops.append(Op('DEC_PTR', 1))
        elif t == '+': ops.append(Op('INC_DATA', 1))
        elif t == '-': ops.append(Op('DEC_DATA', 1))
        elif t == '.': ops.append(Op('WRITE_STDOUT'))
        elif t == ',': ops.append(Op('READ_STDIN'))
        elif t == '[': ops.append(Op('JUMP_IF_ZERO'))
        elif t == ']': ops.append(Op('JUMP_IF_NONZERO'))
    return ops


def opt_contraction(ops):
    """Merge consecutive identical pointer/data ops into single ops with count.

    Example: +++ becomes INC_DATA 3, >>>> becomes INC_PTR 4.
    Returns (optimized_ops, contraction_count).
    """
    if not ops:
        return ops, 0
    mergeable = {'INC_PTR', 'DEC_PTR', 'INC_DATA', 'DEC_DATA'}
    result = [Op(ops[0].type, ops[0].arg1, ops[0].arg2)]
    count = 0
    for i in range(1, len(ops)):
        cur = ops[i]
        prev = result[-1]
        if cur.type == prev.type and cur.type in mergeable:
            prev.arg1 += cur.arg1
            count += 1
        else:
            result.append(Op(cur.type, cur.arg1, cur.arg2))
    return result, count


def opt_clear_loops(ops):
    """Detect clear loop patterns and replace with SET_ZERO.

    The pattern [-] sets the current cell to zero by decrementing
    until the cell wraps to 0.

    Returns (optimized_ops, clear_loop_count).
    """
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if (i + 2 < len(ops) and
            ops[i].type == 'JUMP_IF_ZERO' and
            ops[i+1].type == 'DEC_DATA' and ops[i+1].arg1 == 1 and
            ops[i+2].type == 'JUMP_IF_NONZERO'):
            result.append(Op('SET_ZERO'))
            count += 1
            i += 3
        else:
            result.append(ops[i])
            i += 1
    return result, count


def find_matching_bracket(ops, start):
    """Find the index of the matching ] for a [ at position start."""
    depth = 1
    i = start + 1
    while i < len(ops):
        if ops[i].type == 'JUMP_IF_ZERO':
            depth += 1
        elif ops[i].type == 'JUMP_IF_NONZERO':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def opt_multiply_loops(ops):
    """Detect multiply/copy loop patterns and replace with MUL_COPY + SET_ZERO.

    A multiply loop like [->>+++<<] multiplies the current cell value
    by a factor and adds it to another cell.

    Returns (optimized_ops, multiply_loop_count).
    """
    # TODO: Not yet implemented
    return ops, 0


def opt_scan_loops(ops):
    """Detect scan loop patterns and replace with SCAN instruction.

    A scan loop like [>] moves the pointer until it finds a zero cell.

    Returns (optimized_ops, scan_loop_count).
    """
    # TODO: Not yet implemented
    return ops, 0


def opt_dead_code(ops):
    """Eliminate dead code following SET_ZERO.

    A loop immediately after SET_ZERO is dead code because the cell is
    already zero and the loop condition is never true.

    Returns (optimized_ops, dead_code_count).
    """
    # TODO: Not yet implemented
    return ops, 0


def resolve_jumps(ops):
    """Set jump target addresses for [ and ] instructions."""
    stack = []
    for i, op in enumerate(ops):
        if op.type == 'JUMP_IF_ZERO':
            stack.append(i)
        elif op.type == 'JUMP_IF_NONZERO':
            if stack:
                j = stack.pop()
                ops[j].arg1 = i
                op.arg1 = j
    return ops


def execute(ops, input_bytes=b""):
    """Execute compiled bytecode on the BF virtual machine.

    Memory: 30,000 byte cells (0-255 wrapping), pointer wraps at boundaries.
    """
    MEM_SIZE = 30000
    memory = bytearray(MEM_SIZE)
    ptr = 0
    pc = 0
    ip = 0
    output = bytearray()

    while pc < len(ops):
        op = ops[pc]
        t = op.type

        if t == 'INC_PTR':
            ptr = (ptr + op.arg1) % MEM_SIZE
        elif t == 'DEC_PTR':
            ptr = (ptr - op.arg1) % MEM_SIZE
        elif t == 'INC_DATA':
            memory[ptr] = (memory[ptr] + op.arg1) & 0xFF
        elif t == 'DEC_DATA':
            memory[ptr] = (memory[ptr] - op.arg1) & 0xFF
        elif t == 'WRITE_STDOUT':
            output.append(memory[ptr])
        elif t == 'READ_STDIN':
            if ip < len(input_bytes):
                memory[ptr] = input_bytes[ip]
                ip += 1
            else:
                memory[ptr] = 0
        elif t == 'JUMP_IF_ZERO':
            if memory[ptr] == 0:
                pc = op.arg1
        elif t == 'JUMP_IF_NONZERO':
            if memory[ptr] != 0:
                pc = op.arg1
        elif t == 'SET_ZERO':
            memory[ptr] = 0
        # NOTE: MUL_COPY and SCAN are defined in the bytecode IR but
        # not handled here since no optimization pass emits them yet.

        pc += 1

    return bytes(output)


def emit_nasm(ops):
    """Generate x86-64 NASM assembly from compiled bytecode.

    Register convention:
      r13 = data pointer (points into the 30,000-byte memory array)

    System calls follow the Linux x86-64 ABI:
      rax = syscall number, rdi = arg1, rsi = arg2, rdx = arg3
    """
    lines = []
    lines.append("default rel")
    lines.append("")
    lines.append("section .bss")
    lines.append("memory: resb 30000")
    lines.append("")
    lines.append("section .text")
    lines.append("global _start")
    lines.append("")
    lines.append("_start:")
    lines.append("    lea r13, [memory]")
    lines.append("")

    scan_counter = 0

    for i, op in enumerate(ops):
        t = op.type

        if t == 'INC_PTR':
            lines.append(f"    add r13, {op.arg1}")

        elif t == 'DEC_PTR':
            # Moves the data pointer left
            lines.append(f"    add r13, {op.arg1}")

        elif t == 'INC_DATA':
            # Adds to the current cell
            lines.append(f"    add byte [r13], 1")

        elif t == 'DEC_DATA':
            lines.append(f"    sub byte [r13], {op.arg1}")

        elif t == 'WRITE_STDOUT':
            # write(1, &cell, 1) via syscall
            lines.append("    mov rax, 1")       # sys_write
            lines.append("    mov rdi, 1")       # fd = stdout
            lines.append("    mov rsi, rdi")     # buf = pointer to cell
            lines.append("    mov rdx, 1")       # count = 1
            lines.append("    syscall")

        elif t == 'READ_STDIN':
            # read(0, &cell, 1) via syscall
            lines.append("    mov rax, 0")       # sys_read
            lines.append("    mov rdi, 0")       # fd = stdin
            lines.append("    mov rsi, r13")     # buf = pointer to cell
            lines.append("    mov rdx, 1")       # count = 1
            lines.append("    syscall")

        elif t == 'JUMP_IF_ZERO':
            lines.append(f"    cmp byte [r13], 0")
            lines.append(f"    je .loop_end_{i}")
            lines.append(f".loop_start_{i}:")

        elif t == 'JUMP_IF_NONZERO':
            start_idx = op.arg1
            lines.append(f"    cmp byte [r13], 0")
            lines.append(f"    jne .loop_start_{start_idx}")
            lines.append(f".loop_end_{start_idx}:")

        elif t == 'SET_ZERO':
            lines.append("    mov byte [r13], 0")

        elif t == 'MUL_COPY':
            # Optimized multiply-copy: add (current_cell * factor) to cell at ptr+offset
            lines.append("    nop  ; MUL_COPY stub")

        elif t == 'SCAN':
            # Optimized scan: move pointer until zero cell found
            lines.append("    nop  ; SCAN stub")

    lines.append("")
    lines.append("    ; exit(0)")
    lines.append("    mov rax, 60")
    lines.append("    xor rdi, rdi")
    lines.append("    syscall")

    return "\n".join(lines) + "\n"


def compile_and_optimize(source):
    """Full compilation pipeline: parse -> compile -> optimize -> resolve jumps."""
    tokens = parse_bf(source)
    source_length = len(tokens)

    ops = compile_basic(tokens)

    stats = {
        'contractions': 0,
        'cancellations': 0,
        'clear_loops': 0,
        'multiply_loops': 0,
        'scan_loops': 0,
        'dead_code_eliminated': 0,
    }

    # Optimization pipeline
    ops, n = opt_contraction(ops)
    stats['contractions'] = n

    # Note: cancellation pass (adjacent opposite ops) not in pipeline yet

    ops, n = opt_clear_loops(ops)
    stats['clear_loops'] = n

    ops, n = opt_multiply_loops(ops)
    stats['multiply_loops'] = n

    ops, n = opt_scan_loops(ops)
    stats['scan_loops'] = n

    ops, n = opt_dead_code(ops)
    stats['dead_code_eliminated'] = n

    ops = resolve_jumps(ops)

    return ops, source_length, stats


def main():
    if len(sys.argv) < 3:
        print("Usage: bfcomp.py <run|bytecode|stats|asm|build> <file.bf> [output]",
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    with open(sys.argv[2]) as f:
        source = f.read()

    ops, source_length, stats = compile_and_optimize(source)

    if cmd == 'run':
        if not sys.stdin.isatty():
            input_bytes = sys.stdin.buffer.read()
        else:
            input_bytes = b""
        output = execute(ops, input_bytes)
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()

    elif cmd == 'bytecode':
        for i, op in enumerate(ops):
            print(f"{i}: {op}")

    elif cmd == 'stats':
        result = {
            'source_length': source_length,
            'bytecode_length': len(ops),
            'optimizations': stats,
        }
        print(json.dumps(result))

    elif cmd == 'asm':
        if len(sys.argv) < 4:
            print("Usage: bfcomp.py asm <file.bf> <output.asm>", file=sys.stderr)
            sys.exit(1)
        asm_code = emit_nasm(ops)
        with open(sys.argv[3], 'w') as f:
            f.write(asm_code)

    elif cmd == 'build':
        if len(sys.argv) < 4:
            print("Usage: bfcomp.py build <file.bf> <output>", file=sys.stderr)
            sys.exit(1)
        output_path = sys.argv[3]
        asm_code = emit_nasm(ops)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.asm', delete=False) as f:
            f.write(asm_code)
            asm_path = f.name
        obj_path = asm_path.replace('.asm', '.o')
        try:
            r = subprocess.run(
                ['nasm', '-f', 'elf64', '-o', obj_path, asm_path],
                check=True, capture_output=True
            )
            r = subprocess.run(
                ['ld', '-o', output_path, obj_path],
                check=True, capture_output=True
            )
        finally:
            for p in [asm_path, obj_path]:
                if os.path.exists(p):
                    os.unlink(p)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
