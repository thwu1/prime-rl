"""
Register Allocator — implement this module.

Given a Program with virtual registers (v0, v1, ...), produce an
equivalent Program using only physical registers (r0–r5) and stack
slots (s0, s1, ...) for spills.

The allocated program must produce the same output as the original
when executed by the emulator.
"""

from ir import *

NUM_PHYS_REGS = 6  # r0 through r5


def allocate_registers(program: Program) -> Program:
    """
    Replace every virtual register in *program* with a physical
    register (r0–r5) or a stack slot (s0, s1, ...).

    Returns a new Program; the original is not modified.
    """
    raise NotImplementedError("Implement register allocation")
