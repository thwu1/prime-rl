"""
Solution: x86-64 code generator.

Translates an allocated Program (r0-r5, s0, s1, ...) into AT&T-syntax
x86-64 assembly that links with runtime.c.
"""


import sys
sys.path.insert(0, '/app')

from ir import *

# Map IR physical registers to callee-saved x86-64 registers.
# Using all six callee-saved registers (including %rbp used as GPR,
# NOT as frame pointer — stack slots use %rsp-relative addressing).
_REG_MAP = {
    'r0': '%rbx',
    'r1': '%rbp',
    'r2': '%r12',
    'r3': '%r13',
    'r4': '%r14',
    'r5': '%r15',
}

# Callee-saved registers to push/pop in prologue/epilogue (order matters)
_CALLEE_SAVED = ['%rbx', '%rbp', '%r12', '%r13', '%r14', '%r15']


def _operand(name):
    """Convert an IR operand name to an x86-64 operand string."""
    if name in _REG_MAP:
        return _REG_MAP[name]
    if name.startswith('s') and name[1:].isdigit():
        offset = int(name[1:]) * 8
        return f'{offset}(%rsp)'
    raise ValueError(f"Unknown operand: {name}")


def generate_x86(program: Program) -> str:
    """Generate AT&T-syntax x86-64 assembly for an allocated Program."""

    # --- determine how many stack slots are used ---
    max_slot = -1
    for instrs in program.blocks.values():
        for instr in instrs:
            for reg in instr.defs() | instr.uses():
                if is_stack(reg):
                    idx = int(reg[1:])
                    if idx > max_slot:
                        max_slot = idx
    num_slots = max_slot + 1 if max_slot >= 0 else 0

    # --- compute stack frame size ---
    # After 6 pushes (48 bytes) + return address (8 bytes) = 56 bytes on
    # stack.  56 mod 16 = 8.  We need subq amount such that
    # (56 + stack_size) mod 16 == 0, i.e. stack_size mod 16 == 8.
    raw = num_slots * 8
    if raw % 16 == 8:
        stack_size = raw
    else:
        stack_size = raw + 8

    lines = []
    lines.append('    .text')
    lines.append('    .globl program_entry')
    lines.append('program_entry:')

    # prologue: save callee-saved registers
    for reg in _CALLEE_SAVED:
        lines.append(f'    pushq {reg}')
    lines.append(f'    subq ${stack_size}, %rsp')

    # jump to entry block
    lines.append(f'    jmp .L_{program.entry}')

    # --- generate code per block ---
    for label, instrs in program.blocks.items():
        lines.append(f'.L_{label}:')
        for instr in instrs:
            _emit(instr, lines, stack_size)

    return '\n'.join(lines) + '\n'


def _emit(instr, lines, stack_size):
    """Append x86-64 instructions for one IR instruction."""
    op = instr.op

    if op == 'CONST':
        dst = _operand(instr.dst)
        val = int(instr.src1)
        lines.append(f'    movq ${val}, {dst}')

    elif op in ('ADD', 'SUB'):
        src1 = _operand(instr.src1)
        src2 = _operand(instr.src2)
        dst = _operand(instr.dst)
        x86_op = 'addq' if op == 'ADD' else 'subq'
        lines.append(f'    movq {src1}, %rax')
        lines.append(f'    {x86_op} {src2}, %rax')
        lines.append(f'    movq %rax, {dst}')

    elif op == 'MUL':
        src1 = _operand(instr.src1)
        src2 = _operand(instr.src2)
        dst = _operand(instr.dst)
        lines.append(f'    movq {src1}, %rax')
        lines.append(f'    movq {src2}, %rcx')
        lines.append(f'    imulq %rcx, %rax')
        lines.append(f'    movq %rax, {dst}')

    elif op == 'MOD':
        src1 = _operand(instr.src1)
        src2 = _operand(instr.src2)
        dst = _operand(instr.dst)
        lines.append(f'    movq {src1}, %rax')
        lines.append(f'    cqo')
        lines.append(f'    movq {src2}, %rcx')
        lines.append(f'    idivq %rcx')
        lines.append(f'    movq %rdx, {dst}')

    elif op in ('CMP_LT', 'CMP_EQ'):
        src1 = _operand(instr.src1)
        src2 = _operand(instr.src2)
        dst = _operand(instr.dst)
        set_cc = 'setl' if op == 'CMP_LT' else 'sete'
        lines.append(f'    movq {src1}, %rax')
        lines.append(f'    movq {src2}, %rcx')
        lines.append(f'    cmpq %rcx, %rax')
        lines.append(f'    {set_cc} %al')
        lines.append(f'    movzbq %al, %rax')
        lines.append(f'    movq %rax, {dst}')

    elif op == 'MOV':
        src = _operand(instr.src1)
        dst = _operand(instr.dst)
        lines.append(f'    movq {src}, %rax')
        lines.append(f'    movq %rax, {dst}')

    elif op == 'PRINT':
        src = _operand(instr.src1)
        # System V AMD64: first integer arg in %rdi
        lines.append(f'    movq {src}, %rdi')
        lines.append(f'    call print_int')

    elif op == 'BR':
        cond = _operand(instr.src1)
        lines.append(f'    movq {cond}, %rax')
        lines.append(f'    testq %rax, %rax')
        lines.append(f'    jnz .L_{instr.label1}')
        lines.append(f'    jmp .L_{instr.label2}')

    elif op == 'JMP':
        lines.append(f'    jmp .L_{instr.label1}')

    elif op == 'RET':
        # epilogue: tear down stack frame and restore callee-saved regs
        lines.append(f'    addq ${stack_size}, %rsp')
        for reg in reversed(_CALLEE_SAVED):
            lines.append(f'    popq {reg}')
        lines.append(f'    ret')
