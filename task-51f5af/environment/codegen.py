"""x86-64 assembly code emitter.

"""

from x86_ast import X86Program


def emit_x86(program: X86Program) -> str:
    """Emit AT&T-syntax x86-64 assembly text from an allocated X86Program.

    The output must:
    - Use AT&T syntax (source, destination operand order)
    - Emit the 'main' block as global symbol 'compiler_main'
    - Use .L-prefixed local labels for all other blocks
    - Be assemblable by GAS and linkable with runtime.c via gcc

    Returns the complete assembly text as a string.
    """
    raise NotImplementedError("implement x86-64 assembly emission")
