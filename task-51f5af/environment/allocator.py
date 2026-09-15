"""Register allocator for x86 programs.

"""

import copy

from x86_ast import (
    X86Program, Instr, Callq, Jump, JumpIf,
    Variable, Immediate, Reg, ByteReg, Deref,
)

# ── Register configuration ────────────────────────────────────────────

# Physical registers available for allocation
ALLOCATABLE_REGS = [
    'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10',  # caller-saved
    'rbx', 'r12', 'r13', 'r14',                        # callee-saved
]

# Caller-saved: trashed by every callq
CALLER_SAVED = frozenset({'rax', 'rcx', 'rdx', 'rsi', 'rdi',
                           'r8', 'r9', 'r10', 'r11'})

# Callee-saved among the allocatable set
CALLEE_SAVED = frozenset({'rbx', 'r12', 'r13', 'r14'})


def allocate_registers(program: X86Program) -> X86Program:
    """Replace all Variable operands with physical Reg or stack-slot Deref.

    The returned program must:
    - Contain no Variable nodes
    - Produce the same (rax, output) as the original via the emulator
    - Have a 'main' block (prologue) and 'conclusion' block (epilogue)
    - Have no two-operand instructions with two Deref operands
    """
    raise NotImplementedError("implement register allocation")
