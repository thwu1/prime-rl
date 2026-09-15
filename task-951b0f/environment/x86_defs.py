"""x86-64 register definitions and instruction analysis utilities.

Provides metadata about the x86-64 register file and functions to determine
which locations each instruction reads and writes. These are essential for
liveness analysis and interference graph construction.

"""
from ir import VReg, PReg, Imm, Deref, Instr

# Physical registers available for allocation.
# Order determines the color-to-register mapping used in graph coloring.
CALLER_SAVED = [PReg(r) for r in
                ['rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11']]
CALLEE_SAVED = [PReg(r) for r in
                ['rbx', 'r12', 'r13', 'r14', 'r15']]
ALLOCATABLE = CALLER_SAVED + CALLEE_SAVED   # 14 registers total

CALLER_SAVED_SET = frozenset(CALLER_SAVED)
CALLEE_SAVED_SET = frozenset(CALLEE_SAVED)
ALLOCATABLE_SET  = frozenset(ALLOCATABLE)

# Color  <->  register bijection used by graph-coloring allocators.
REG_TO_COLOR = {reg: i for i, reg in enumerate(ALLOCATABLE)}
COLOR_TO_REG = {i: reg for i, reg in enumerate(ALLOCATABLE)}
NUM_REGS     = len(ALLOCATABLE)    # 14


# ---------------------------------------------------------------------------
# Instruction analysis
# ---------------------------------------------------------------------------

def locations_read(instr: Instr) -> set:
    """Return the set of VReg/PReg locations read by *instr*."""
    op, args = instr.op, instr.args
    result = set()

    if op == 'movq':
        src, dst = args
        if isinstance(src, (VReg, PReg)):
            result.add(src)
        elif isinstance(src, Deref):
            result.add(PReg(src.reg))
        if isinstance(dst, Deref):
            result.add(PReg(dst.reg))

    elif op in ('addq', 'subq', 'imulq'):
        for a in args:
            if isinstance(a, (VReg, PReg)):
                result.add(a)
            elif isinstance(a, Deref):
                result.add(PReg(a.reg))

    elif op == 'negq':
        a = args[0]
        if isinstance(a, (VReg, PReg)):
            result.add(a)

    elif op == 'cmpq':
        for a in args:
            if isinstance(a, (VReg, PReg)):
                result.add(a)

    elif op == 'retq':
        result.add(PReg('rax'))

    elif op == 'pushq':
        a = args[0]
        if isinstance(a, (VReg, PReg)):
            result.add(a)

    # callq, jmp, je/jne/jl/jg/jle/jge, popq  -->  read nothing
    return result


def locations_written(instr: Instr) -> set:
    """Return the set of VReg/PReg locations written by *instr*."""
    op, args = instr.op, instr.args
    result = set()

    if op == 'movq':
        dst = args[1]
        if isinstance(dst, (VReg, PReg)):
            result.add(dst)

    elif op in ('addq', 'subq', 'imulq'):
        dst = args[1]
        if isinstance(dst, (VReg, PReg)):
            result.add(dst)

    elif op == 'negq':
        a = args[0]
        if isinstance(a, (VReg, PReg)):
            result.add(a)

    elif op == 'callq':
        # A call clobbers every caller-saved register.
        result.update(CALLER_SAVED_SET)

    elif op == 'popq':
        a = args[0]
        if isinstance(a, (VReg, PReg)):
            result.add(a)

    return result


def is_move_instr(instr: Instr) -> bool:
    """True when *instr* is a register-to-register ``movq``."""
    return (instr.op == 'movq'
            and isinstance(instr.args[0], (VReg, PReg))
            and isinstance(instr.args[1], (VReg, PReg)))


def successor_labels(block) -> list:
    """Return the labels of *block*'s successor blocks in the CFG.

    A well-formed block ends with either:
    * ``retq``  -> no successors
    * ``jmp L`` -> one successor
    * ``jCC L1; jmp L2`` -> two successors (conditional + fallthrough)
    """
    instrs = block.instrs
    if not instrs:
        return []
    last = instrs[-1]
    if last.op == 'retq':
        return []
    if last.op == 'jmp':
        succs = [last.args[0]]
        if len(instrs) >= 2:
            prev = instrs[-2]
            if prev.op in ('je', 'jne', 'jl', 'jg', 'jle', 'jge'):
                succs.append(prev.args[0])
        return succs
    return []
