"""
x86-64 assembly emitter for allocated pseudo-x86 programs.

Emits AT&T-syntax assembly compilable with gcc when linked against
the C runtime at /opt/regalloc/runtime.c.
"""
from ir import Immediate, Register, Deref, Instr, Callq, Jump, JumpIf


def format_operand(op):
    """Convert an IR operand to AT&T assembly syntax string."""
    raise NotImplementedError("Implement format_operand")


def emit_program(program, stack_size, used_callee_saved):
    """
    Emit a complete x86-64 assembly source defining a ``main`` function.

    Must comply with the System V AMD64 ABI (stack alignment, callee-saved
    register preservation) and correctly linearize the program's basic blocks.

    Returns the assembly source as a single string.
    """
    raise NotImplementedError("Implement emit_program")
