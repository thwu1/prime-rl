#!/usr/bin/env python3
"""Optimizing BF compiler with bytecode IR and x86-64 NASM backend.

"""

import sys
import json
import os
import subprocess
import tempfile


class Op:
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


def parse_bf(source):
    return [ch for ch in source if ch in '><+-.,[]']


def compile_basic(tokens):
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


def opt_cancellation(ops):
    """Cancel adjacent opposite ops (INC_DATA/DEC_DATA, INC_PTR/DEC_PTR)."""
    opposites = {
        'INC_DATA': 'DEC_DATA', 'DEC_DATA': 'INC_DATA',
        'INC_PTR': 'DEC_PTR', 'DEC_PTR': 'INC_PTR',
    }
    mergeable = {'INC_PTR', 'DEC_PTR', 'INC_DATA', 'DEC_DATA'}
    count = 0
    changed = True
    while changed:
        changed = False
        result = []
        i = 0
        while i < len(ops):
            if i + 1 < len(ops):
                a, b = ops[i], ops[i + 1]
                if a.type in opposites and opposites[a.type] == b.type:
                    if a.arg1 == b.arg1:
                        count += 1
                        i += 2
                        changed = True
                        continue
                    elif a.arg1 > b.arg1:
                        result.append(Op(a.type, a.arg1 - b.arg1))
                        count += 1
                        i += 2
                        changed = True
                        continue
                    else:
                        result.append(Op(b.type, b.arg1 - a.arg1))
                        count += 1
                        i += 2
                        changed = True
                        continue
                elif a.type == b.type and a.type in mergeable:
                    result.append(Op(a.type, a.arg1 + b.arg1))
                    i += 2
                    changed = True
                    continue
            result.append(ops[i])
            i += 1
        ops = result
    return ops, count


def opt_clear_loops(ops):
    """Detect [-] and [+] clear loops and replace with SET_ZERO."""
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if (i + 2 < len(ops) and
            ops[i].type == 'JUMP_IF_ZERO' and
            ops[i+1].type in ('DEC_DATA', 'INC_DATA') and ops[i+1].arg1 == 1 and
            ops[i+2].type == 'JUMP_IF_NONZERO'):
            result.append(Op('SET_ZERO'))
            count += 1
            i += 3
        else:
            result.append(ops[i])
            i += 1
    return result, count


def find_matching_bracket(ops, start):
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
    """Detect multiply/copy loop patterns and replace with MUL_COPY + SET_ZERO."""
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if ops[i].type == 'JUMP_IF_ZERO':
            match = find_matching_bracket(ops, i)
            if match is not None:
                body = ops[i+1:match]
                allowed = {'DEC_DATA', 'INC_DATA', 'INC_PTR', 'DEC_PTR'}
                if all(op.type in allowed for op in body) and len(body) > 1:
                    ptr_offset = 0
                    changes = {}
                    for op in body:
                        if op.type == 'INC_PTR':
                            ptr_offset += op.arg1
                        elif op.type == 'DEC_PTR':
                            ptr_offset -= op.arg1
                        elif op.type == 'INC_DATA':
                            changes[ptr_offset] = changes.get(ptr_offset, 0) + op.arg1
                        elif op.type == 'DEC_DATA':
                            changes[ptr_offset] = changes.get(ptr_offset, 0) - op.arg1
                    if ptr_offset == 0 and changes.get(0, 0) == -1:
                        del changes[0]
                        if changes:
                            count += 1
                            for offset in sorted(changes.keys()):
                                result.append(Op('MUL_COPY', offset, changes[offset]))
                            result.append(Op('SET_ZERO'))
                            i = match + 1
                            continue
        result.append(ops[i])
        i += 1
    return result, count


def opt_scan_loops(ops):
    """Detect scan loop patterns and replace with SCAN instruction."""
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if ops[i].type == 'JUMP_IF_ZERO':
            match = find_matching_bracket(ops, i)
            if match is not None:
                body = ops[i+1:match]
                if len(body) == 1:
                    if body[0].type == 'INC_PTR':
                        result.append(Op('SCAN', body[0].arg1))
                        count += 1
                        i = match + 1
                        continue
                    elif body[0].type == 'DEC_PTR':
                        result.append(Op('SCAN', -body[0].arg1))
                        count += 1
                        i = match + 1
                        continue
        result.append(ops[i])
        i += 1
    return result, count


def opt_dead_code(ops):
    """Eliminate loops immediately after SET_ZERO (dead code)."""
    result = []
    count = 0
    i = 0
    while i < len(ops):
        if (ops[i].type == 'JUMP_IF_ZERO' and
            len(result) > 0 and result[-1].type == 'SET_ZERO'):
            match = find_matching_bracket(ops, i)
            if match is not None:
                count += 1
                i = match + 1
                continue
        result.append(ops[i])
        i += 1
    return result, count


def resolve_jumps(ops):
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
        elif t == 'MUL_COPY':
            target = (ptr + op.arg1) % MEM_SIZE
            memory[target] = (memory[target] + memory[ptr] * op.arg2) & 0xFF
        elif t == 'SCAN':
            while memory[ptr] != 0:
                ptr = (ptr + op.arg1) % MEM_SIZE

        pc += 1

    return bytes(output)


def emit_nasm(ops):
    """Generate x86-64 NASM assembly from compiled bytecode."""
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
            lines.append(f"    sub r13, {op.arg1}")

        elif t == 'INC_DATA':
            lines.append(f"    add byte [r13], {op.arg1}")

        elif t == 'DEC_DATA':
            lines.append(f"    sub byte [r13], {op.arg1}")

        elif t == 'WRITE_STDOUT':
            lines.append("    mov rax, 1")
            lines.append("    mov rdi, 1")
            lines.append("    mov rsi, r13")
            lines.append("    mov rdx, 1")
            lines.append("    syscall")

        elif t == 'READ_STDIN':
            lines.append("    mov rax, 0")
            lines.append("    mov rdi, 0")
            lines.append("    mov rsi, r13")
            lines.append("    mov rdx, 1")
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
            offset = op.arg1
            factor = op.arg2
            lines.append("    movzx eax, byte [r13]")
            lines.append(f"    imul eax, eax, {factor}")
            if offset >= 0:
                lines.append(f"    add byte [r13 + {offset}], al")
            else:
                lines.append(f"    add byte [r13 - {-offset}], al")

        elif t == 'SCAN':
            scan_counter += 1
            step = op.arg1
            lines.append(f".scan_{scan_counter}:")
            lines.append(f"    cmp byte [r13], 0")
            lines.append(f"    je .scan_end_{scan_counter}")
            if step > 0:
                lines.append(f"    add r13, {step}")
            else:
                lines.append(f"    sub r13, {-step}")
            lines.append(f"    jmp .scan_{scan_counter}")
            lines.append(f".scan_end_{scan_counter}:")

    lines.append("")
    lines.append("    ; exit(0)")
    lines.append("    mov rax, 60")
    lines.append("    xor rdi, rdi")
    lines.append("    syscall")

    return "\n".join(lines) + "\n"


def compile_and_optimize(source):
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

    ops, n = opt_contraction(ops)
    stats['contractions'] = n

    ops, n = opt_cancellation(ops)
    stats['cancellations'] = n

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
            subprocess.run(
                ['nasm', '-f', 'elf64', '-o', obj_path, asm_path],
                check=True, capture_output=True
            )
            subprocess.run(
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
