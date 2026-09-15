"""Complete x86-64 assembly emitter.

Translates an allocated CFG (no VRegs) into GNU Assembler (GAS) source
that compiles with gcc alongside runtime.c to produce a correct ELF binary.

"""
from ir import CFG, PReg, Imm, Deref

_CALLEE_SAVED = frozenset(['rbx', 'r12', 'r13', 'r14', 'r15'])


def _fmt(op):
    """Format an operand in AT&T / GAS syntax."""
    if isinstance(op, Imm):
        return f'${op.value}'
    if isinstance(op, PReg):
        return f'%{op.name}'
    if isinstance(op, Deref):
        return f'{op.offset}(%{op.reg})'
    return str(op)


def _is_mem(op):
    return isinstance(op, Deref)


def emit_x86(cfg: CFG) -> str:
    """Generate GAS x86-64 assembly from an allocated CFG."""
    # ---- scan CFG for callee-saved regs used and max spill offset ---------
    used_callee = set()
    max_spill = 0
    for block in cfg.blocks.values():
        for instr in block.instrs:
            for arg in instr.args:
                if isinstance(arg, PReg) and arg.name in _CALLEE_SAVED:
                    used_callee.add(arg.name)
                if isinstance(arg, Deref) and arg.reg == 'rbp' and arg.offset < 0:
                    max_spill = max(max_spill, abs(arg.offset))

    callee_list = sorted(used_callee)  # deterministic order

    # ---- compute frame size (16-byte aligned) ----------------------------
    # Layout below %rbp:
    #   -8(%rbp) .. -max_spill(%rbp)  :  spill slots (from allocator)
    #   -(max_spill+8) .. etc.        :  saved callee-saved registers
    callee_area = 8 * len(callee_list)
    frame_size = max_spill + callee_area
    if frame_size % 16 != 0:
        frame_size += 16 - (frame_size % 16)

    # ---- callee-save offsets (below spill area) --------------------------
    callee_offsets = {}
    for i, reg in enumerate(callee_list):
        callee_offsets[reg] = -(max_spill + 8 * (i + 1))

    # ---- prologue --------------------------------------------------------
    lines = ['.globl main', '.text', 'main:',
             '    pushq %rbp',
             '    movq %rsp, %rbp']
    if frame_size > 0:
        lines.append(f'    subq ${frame_size}, %rsp')
    for reg, off in callee_offsets.items():
        lines.append(f'    movq %{reg}, {off}(%rbp)')

    # ---- emit blocks (entry first, then rest) ----------------------------
    order = [cfg.entry] + [l for l in cfg.blocks if l != cfg.entry]
    for label in order:
        lines.append(f'.L_{label}:')
        for instr in cfg.blocks[label].instrs:
            lines.extend(_emit_instr(instr, callee_offsets))

    lines.append('')
    return '\n'.join(lines)


def _emit_instr(instr, callee_offsets):
    """Translate one IR instruction to GAS assembly lines.

    Handles x86-64 encoding constraints: no memory-to-memory operands,
    imulq requires a register destination.  Uses %r11 (and %r10 if needed)
    as scratch registers via pushq/popq to avoid clobbering live values.
    """
    op, args = instr.op, instr.args
    out = []

    if op == 'retq':
        # ---- epilogue: restore callee-saved, tear down frame, return -----
        for reg, off in callee_offsets.items():
            out.append(f'    movq {off}(%rbp), %{reg}')
        out.append('    movq %rbp, %rsp')
        out.append('    popq %rbp')
        out.append('    ret')

    elif op in ('movq', 'addq', 'subq', 'cmpq'):
        src, dst = args[0], args[1]
        if _is_mem(src) and _is_mem(dst):
            # x86-64 forbids two memory operands; use %r11 as scratch
            out.append('    pushq %r11')
            out.append(f'    movq {_fmt(src)}, %r11')
            if op == 'movq':
                out.append(f'    movq %r11, {_fmt(dst)}')
            else:
                out.append(f'    {op} %r11, {_fmt(dst)}')
            out.append('    popq %r11')
        else:
            out.append(f'    {op} {_fmt(src)}, {_fmt(dst)}')

    elif op == 'imulq':
        src, dst = args[0], args[1]
        if _is_mem(dst):
            # imulq requires a register destination
            out.append('    pushq %r11')
            out.append(f'    movq {_fmt(dst)}, %r11')
            if _is_mem(src):
                out.append('    pushq %r10')
                out.append(f'    movq {_fmt(src)}, %r10')
                out.append('    imulq %r10, %r11')
                out.append('    popq %r10')
            else:
                out.append(f'    imulq {_fmt(src)}, %r11')
            out.append(f'    movq %r11, {_fmt(dst)}')
            out.append('    popq %r11')
        else:
            out.append(f'    imulq {_fmt(src)}, {_fmt(dst)}')

    elif op == 'negq':
        out.append(f'    negq {_fmt(args[0])}')

    elif op == 'callq':
        out.append(f'    callq {args[0]}')

    elif op == 'jmp':
        out.append(f'    jmp .L_{args[0]}')

    elif op in ('je', 'jne', 'jl', 'jg', 'jle', 'jge'):
        out.append(f'    {op} .L_{args[0]}')

    elif op in ('pushq', 'popq'):
        out.append(f'    {op} {_fmt(args[0])}')

    else:
        raise ValueError(f"Unknown instruction: {op}")

    return out
