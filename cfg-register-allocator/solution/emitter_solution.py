"""GAS-syntax x86-64 assembly emitter for allocated X86Programs.

Translates an allocated program (no Var arguments) into AT&T-notation
assembly that links with runtime.c via gcc.
"""
import sys
sys.path.insert(0, '/app')
from ir import Imm, Reg, Deref


def _fmt(a):
    """Format an IR argument in AT&T/GAS syntax."""
    if isinstance(a, Imm):
        return f'${a.val}'
    if isinstance(a, Reg):
        return f'%{a.name}'
    if isinstance(a, Deref):
        return f'{a.offset}(%{a.reg})'
    raise ValueError(f'Cannot emit argument: {a!r}')


_BRANCH_OPS = frozenset(('jmp', 'je', 'jne', 'jl', 'jle', 'jg', 'jge'))
_TWO_ARG_OPS = frozenset(('movq', 'addq', 'subq', 'xorq', 'cmpq', 'movzbq'))


def emit_program(program, path):
    """Write an allocated X86Program as a GAS x86-64 assembly file.

    The emitted assembly defines a function ``_program_entry`` that
    runtime.c's ``main()`` calls.  The function returns the result
    in %rax.

    Args:
        program: An X86Program with no Var arguments and stack_space set.
        path: Output file path for the .s assembly file.
    """
    out = []
    out.append('    .text')
    out.append('    .globl _program_entry')
    out.append('    .type _program_entry, @function')
    out.append('_program_entry:')

    # Prologue: set up stack frame
    out.append('    pushq %rbp')
    out.append('    movq %rsp, %rbp')
    if program.stack_space > 0:
        out.append(f'    subq ${program.stack_space}, %rsp')

    # Emit blocks: start first, then remaining in sorted order
    order = ['start'] + sorted(l for l in program.blocks if l != 'start')
    for label in order:
        if label not in program.blocks:
            continue
        out.append(f'{label}:')
        for instr in program.blocks[label]:
            _emit_instr(out, instr)

    # Conclusion label: epilogue and return
    out.append('conclusion:')
    if program.stack_space > 0:
        out.append(f'    addq ${program.stack_space}, %rsp')
    out.append('    popq %rbp')
    out.append('    retq')
    out.append('')

    with open(path, 'w') as f:
        f.write('\n'.join(out))


def _emit_instr(out, instr):
    """Emit a single instruction in GAS AT&T syntax."""
    op = instr.op
    args = instr.args

    # Branch instructions: operand is a label string
    if op in _BRANCH_OPS:
        out.append(f'    {op} {args[0]}')
        return

    # Call: first arg is function name, second is arity (ignored in asm)
    if op == 'callq':
        out.append(f'    callq {args[0]}')
        return

    if op == 'retq':
        out.append('    retq')
        return

    # Two-operand instructions: check for illegal two-memory-operand case
    if (op in _TWO_ARG_OPS and len(args) == 2
            and isinstance(args[0], Deref) and isinstance(args[1], Deref)):
        # x86-64 forbids mem-mem; use %rax as scratch (reserved, not allocatable)
        out.append(f'    movq {_fmt(args[0])}, %rax')
        if op == 'movq':
            out.append(f'    movq %rax, {_fmt(args[1])}')
        else:
            out.append(f'    {op} %rax, {_fmt(args[1])}')
        return

    # General case: format all args
    parts = ', '.join(_fmt(a) for a in args)
    out.append(f'    {op} {parts}')
