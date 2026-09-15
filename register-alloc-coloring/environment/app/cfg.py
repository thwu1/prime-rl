"""
Control flow graph and instruction representations for a simplified x86-64.

Instruction types:
  - Instr(op, args)      : general instruction, e.g. Instr('addq', [Var('x'), Var('y')])
  - Callq(label, arity)  : call instruction, e.g. Callq('read_int', 0)
  - JumpIf(cc, label)    : conditional jump, e.g. JumpIf('e', 'block_then')
  - Jump(label)          : unconditional jump

Argument types:
  - Var(name)            : a program variable
  - Reg(name)            : a physical register, e.g. Reg('rax')
  - Immediate(value)     : an integer constant
  - Deref(reg, offset)   : memory reference, e.g. Deref('rbp', -8)
"""
from dataclasses import dataclass, field
from typing import Union, Dict, List, Set, Optional


# ─── Arguments ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Var:
    name: str
    def __repr__(self): return f"Var({self.name!r})"

@dataclass(frozen=True)
class Reg:
    name: str
    def __repr__(self): return f"Reg({self.name!r})"

@dataclass(frozen=True)
class Immediate:
    value: int
    def __repr__(self): return f"Immediate({self.value})"

@dataclass(frozen=True)
class Deref:
    reg: str
    offset: int
    def __repr__(self): return f"Deref({self.reg!r}, {self.offset})"

Arg = Union[Var, Reg, Immediate, Deref]
Location = Union[Var, Reg]  # things that can be colored


# ─── Instructions ────────────────────────────────────────────────────────────

@dataclass
class Instr:
    op: str          # 'movq', 'addq', 'subq', 'negq', 'xorq', 'cmpq', 'movzbq', 'leaq'
    args: List[Arg]
    def __repr__(self):
        args_s = ", ".join(repr(a) for a in self.args)
        return f"Instr({self.op!r}, [{args_s}])"

@dataclass
class Callq:
    label: str
    arity: int
    def __repr__(self): return f"Callq({self.label!r}, {self.arity})"

@dataclass
class JumpIf:
    cc: str    # condition code: 'e', 'ne', 'l', 'le', 'g', 'ge'
    label: str
    def __repr__(self): return f"JumpIf({self.cc!r}, {self.label!r})"

@dataclass
class Jump:
    label: str
    def __repr__(self): return f"Jump({self.label!r})"

Instruction = Union[Instr, Callq, JumpIf, Jump]


# ─── Basic Block & CFG ──────────────────────────────────────────────────────

@dataclass
class BasicBlock:
    label: str
    instrs: List[Instruction]  # last instr should be Jump or JumpIf

    def successors(self) -> List[str]:
        """Return labels of successor blocks."""
        succs = []
        for instr in self.instrs:
            if isinstance(instr, Jump):
                succs.append(instr.label)
            elif isinstance(instr, JumpIf):
                succs.append(instr.label)
        return succs

@dataclass
class CFG:
    """A control flow graph: dict of label -> BasicBlock, with an entry label."""
    entry: str
    blocks: Dict[str, BasicBlock]

    def all_variables(self) -> Set[str]:
        """Return the set of all variable names appearing in the CFG."""
        vs = set()
        for block in self.blocks.values():
            for instr in block.instrs:
                if isinstance(instr, Instr):
                    for arg in instr.args:
                        if isinstance(arg, Var):
                            vs.add(arg.name)
                elif isinstance(instr, Callq):
                    pass  # no var args
                # Jumps don't have var args
        return vs


# ─── Register Definitions ───────────────────────────────────────────────────

CALLER_SAVE_REGS = ['rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11']
CALLEE_SAVE_REGS = ['rbx', 'r12', 'r13', 'r14']

# Registers available for allocation, in color order (color 0 = rbx, color 1 = rcx, ...)
ALLOCATABLE_REGS = ['rbx', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14']

# Mapping from register name to color index
REG_TO_COLOR = {reg: i for i, reg in enumerate(ALLOCATABLE_REGS)}

# Registers NOT available for allocation (used for special purposes)
RESERVED_REGS = {'rax', 'rsp', 'rbp', 'r15'}


def reads_of(instr: Instruction) -> Set[Location]:
    """Return the set of locations (Var or Reg) read by this instruction."""
    if isinstance(instr, Instr):
        if instr.op in ('movq', 'movzbq', 'leaq'):
            # reads source only (args[0])
            return _locations_in(instr.args[0:1])
        elif instr.op == 'negq':
            # reads and writes args[0]
            return _locations_in(instr.args)
        elif instr.op == 'cmpq':
            # reads both, writes neither (only flags)
            return _locations_in(instr.args)
        else:
            # addq, subq, xorq: reads both args
            return _locations_in(instr.args)
    elif isinstance(instr, Callq):
        # arguments passed in registers
        arg_regs = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']
        return {Reg(r) for r in arg_regs[:instr.arity]}
    elif isinstance(instr, (Jump, JumpIf)):
        return set()
    return set()


def writes_of(instr: Instruction) -> Set[Location]:
    """Return the set of locations (Var or Reg) written by this instruction."""
    if isinstance(instr, Instr):
        if instr.op in ('movq', 'movzbq', 'leaq'):
            # writes destination (args[-1])
            return _locations_in(instr.args[-1:])
        elif instr.op == 'negq':
            return _locations_in(instr.args)
        elif instr.op == 'cmpq':
            return set()  # only writes flags
        else:
            # addq, subq, xorq: writes destination (args[-1])
            return _locations_in(instr.args[-1:])
    elif isinstance(instr, Callq):
        # calls clobber all caller-save registers
        return {Reg(r) for r in CALLER_SAVE_REGS}
    elif isinstance(instr, (Jump, JumpIf)):
        return set()
    return set()


def _locations_in(args: List[Arg]) -> Set[Location]:
    result = set()
    for a in args:
        if isinstance(a, (Var, Reg)):
            result.add(a)
        elif isinstance(a, Deref):
            result.add(Reg(a.reg))
    return result
