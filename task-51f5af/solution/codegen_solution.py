"""Complete x86-64 assembly code emitter.


Converts an allocated X86Program (no Variable nodes) into AT&T-syntax
x86-64 assembly text suitable for GAS.  The 'main' block is emitted as
the global symbol 'compiler_main'; all other block labels are .L-prefixed
local labels.
"""

from x86_ast import (
    X86Program, Instr, Callq, Jump, JumpIf,
    Immediate, Reg, ByteReg, Deref,
)


def _fmt_arg(a):
    """Format an operand in AT&T syntax."""
    if isinstance(a, Immediate):
        return f'${a.value}'
    elif isinstance(a, ByteReg):
        return f'%{a.id}'
    elif isinstance(a, Reg):
        return f'%{a.id}'
    elif isinstance(a, Deref):
        return f'{a.offset}(%{a.reg})'
    else:
        raise ValueError(f'Cannot emit operand: {a!r}')


def _fmt_label(label):
    """Map a block label to its assembly symbol."""
    if label == 'main':
        return 'compiler_main'
    return f'.L{label}'


def emit_x86(program: X86Program) -> str:
    """Emit AT&T-syntax x86-64 assembly text from an allocated X86Program."""
    lines = ['.text', '.globl compiler_main', '']

    # Determine block order: main first, then sorted, conclusion last.
    ordered = []
    if 'main' in program.body:
        ordered.append('main')
    for label in sorted(program.body.keys()):
        if label not in ('main', 'conclusion'):
            ordered.append(label)
    if 'conclusion' in program.body:
        ordered.append('conclusion')

    for label in ordered:
        instrs = program.body[label]
        lines.append(f'{_fmt_label(label)}:')

        for node in instrs:
            if isinstance(node, Instr):
                if len(node.args) == 0:
                    lines.append(f'    {node.instr}')
                else:
                    args_str = ', '.join(_fmt_arg(a) for a in node.args)
                    lines.append(f'    {node.instr} {args_str}')
            elif isinstance(node, Callq):
                lines.append(f'    callq {node.func}')
            elif isinstance(node, Jump):
                lines.append(f'    jmp {_fmt_label(node.label)}')
            elif isinstance(node, JumpIf):
                lines.append(f'    j{node.cc} {_fmt_label(node.label)}')

    lines.append('')
    return '\n'.join(lines)
