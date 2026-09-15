
"""
x86-64 assembly emitter for allocated pseudo-x86 programs.

Produces AT&T-syntax assembly text with:
  - Function prologue/epilogue with callee-saved register preservation
  - 16-byte stack alignment for System V AMD64 ABI compliance
  - Block-structured control flow matching the IR labels
"""

# Callee-saved registers used by the allocator that must be preserved
CALLEE_SAVED = ['rbx', 'r12', 'r13', 'r14']


def _arg_to_asm(arg):
    """Convert an IR argument tuple to AT&T syntax string."""
    kind = arg[0]
    if kind == 'imm':
        return f"${arg[1]}"
    elif kind == 'reg':
        return f"%{arg[1]}"
    elif kind == 'deref':
        return f"{arg[2]}(%{arg[1]})"
    else:
        raise ValueError(f"Cannot emit argument: {arg}")


def _instr_to_asm(instr):
    """Convert an IR instruction tuple to AT&T syntax assembly line."""
    op = instr[0]

    if op == 'jmp':
        return f"jmp {instr[1]}"
    elif op in ('je', 'jne', 'jl', 'jle', 'jg', 'jge'):
        return f"{op} {instr[1]}"
    elif op == 'callq':
        return f"call {instr[1]}"
    elif op == 'negq':
        return f"negq {_arg_to_asm(instr[1])}"
    elif op in ('pushq', 'popq'):
        return f"{op} {_arg_to_asm(instr[1])}"
    elif op in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
        return f"{op} {_arg_to_asm(instr[1])}"
    elif op == 'movzbq':
        return f"movzbq {_arg_to_asm(instr[1])}, {_arg_to_asm(instr[2])}"
    elif op in ('movq', 'addq', 'subq', 'xorq', 'cmpq'):
        return f"{op} {_arg_to_asm(instr[1])}, {_arg_to_asm(instr[2])}"
    else:
        raise ValueError(f"Unknown instruction opcode: {op}")


def _compute_max_spill_offset(blocks):
    """Find the largest absolute rbp-relative offset used for stack spills."""
    max_offset = 0
    for instrs in blocks.values():
        for instr in instrs:
            for arg in instr[1:]:
                if isinstance(arg, tuple) and arg[0] == 'deref' and arg[1] == 'rbp':
                    offset = abs(arg[2])
                    if offset > max_offset:
                        max_offset = offset
    return max_offset


def emit_x86(program, func_name="program_entry"):
    """Generate AT&T-syntax x86-64 assembly for an allocated program.

    The emitted function is callable from C:
        extern long <func_name>(void);

    Stack layout relative to rbp:
        rbp+8                : return address
        rbp                  : saved rbp
        rbp-8 .. rbp-S       : spill slots (S = max_spill_offset)
        rbp-S-8 .. rbp-S-32  : saved callee-saved registers (rbx, r12-r14)

    Args:
        program: dict with 'blocks' mapping labels to instruction lists.
                 All instructions must already be allocated (no 'var' args).
        func_name: symbol name for the generated function.

    Returns:
        AT&T-syntax x86-64 assembly text as a string.
    """
    blocks = program['blocks']

    max_spill = _compute_max_spill_offset(blocks)
    num_callee_saved = len(CALLEE_SAVED)

    # Total frame: spill area + callee-saved save area
    # After pushq %rbp, rsp is 16-byte aligned.
    # subq $frame_size must keep it 16-byte aligned for calls.
    frame_size = max_spill + num_callee_saved * 8
    # Round up to next multiple of 16
    frame_size = (frame_size + 15) // 16 * 16

    # Callee-saved save offsets (below spill area)
    save_offsets = {}
    for i, reg in enumerate(CALLEE_SAVED):
        save_offsets[reg] = -(max_spill + (i + 1) * 8)

    lines = []

    # Assembler directives
    lines.append(f"    .text")
    lines.append(f"    .globl {func_name}")
    lines.append(f"    .type {func_name}, @function")

    # Function entry
    lines.append(f"{func_name}:")

    # Prologue: save rbp, set up frame
    lines.append(f"    pushq %rbp")
    lines.append(f"    movq %rsp, %rbp")
    if frame_size > 0:
        lines.append(f"    subq ${frame_size}, %rsp")

    # Save callee-saved registers
    for reg in CALLEE_SAVED:
        lines.append(f"    movq %{reg}, {save_offsets[reg]}(%rbp)")

    # Jump to entry block
    lines.append(f"    jmp start")

    # Emit all basic blocks
    for label, instrs in blocks.items():
        lines.append(f"{label}:")
        for instr in instrs:
            lines.append(f"    {_instr_to_asm(instr)}")

    # Conclusion block: restore and return
    lines.append(f"conclusion:")
    for reg in CALLEE_SAVED:
        lines.append(f"    movq {save_offsets[reg]}(%rbp), %{reg}")
    if frame_size > 0:
        lines.append(f"    addq ${frame_size}, %rsp")
    lines.append(f"    popq %rbp")
    lines.append(f"    retq")
    lines.append("")

    return "\n".join(lines)
