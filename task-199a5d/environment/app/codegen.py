"""
x86-64 Code Generator — implement this module.

Given an allocated Program (physical registers r0-r5 and stack slots
s0, s1, ...), produce AT&T-syntax x86-64 assembly that, when assembled
and linked with runtime.c, produces the same output as the emulator.

The generated assembly must:
  - Define a .globl symbol ``program_entry``
  - Call ``print_int`` (provided by runtime.c) for PRINT instructions,
    passing the value in %rdi per the System V AMD64 ABI
  - Map r0-r5 to actual x86-64 registers (callee-saved recommended)
  - Map s0, s1, ... to stack frame slots (%rsp-relative)
  - Maintain 16-byte stack alignment before every ``call``
"""


from ir import *


def generate_x86(program: Program) -> str:
    """
    Generate AT&T-syntax x86-64 assembly for an allocated Program.

    Returns a string containing the assembly source.
    """
    raise NotImplementedError("Implement x86-64 code generation")
