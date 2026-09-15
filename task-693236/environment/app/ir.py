
"""x86-64 Intermediate Representation for register allocation.

Defines instruction types, operand types, program structure,
and helper functions for read/write analysis of instructions.
"""

from dataclasses import dataclass, field
from typing import Union, Set, List, Dict, FrozenSet

# === Operand Types ===

@dataclass(frozen=True)
class Immediate:
    """Integer literal, e.g. $42"""
    value: int
    def __repr__(self): return f'${self.value}'

@dataclass(frozen=True)
class Reg:
    """Physical register, e.g. %rax"""
    name: str
    def __repr__(self): return f'%{self.name}'

@dataclass(frozen=True)
class Var:
    """Virtual variable to be allocated to a register or stack slot."""
    name: str
    def __repr__(self): return self.name

@dataclass(frozen=True)
class Deref:
    """Memory reference via base register + offset, e.g. -8(%rbp)"""
    reg: str
    offset: int
    def __repr__(self): return f'{self.offset}(%{self.reg})'

Location = Union[Reg, Var, Deref]
Operand = Union[Immediate, Reg, Var, Deref]

# === Instruction Types ===

@dataclass
class Instr:
    """General instruction: movq, addq, subq, negq, xorq, cmpq, sete, movzbq, etc.
    Binary instructions have args=[src, dst]. Unary have args=[dst]."""
    name: str
    args: list

    def __repr__(self):
        return f'{self.name} {", ".join(repr(a) for a in self.args)}'

@dataclass
class Callq:
    """Function call. Clobbers all caller-saved registers."""
    label: str
    num_args: int

    def __repr__(self):
        return f'callq {self.label}'

@dataclass
class Jump:
    """Unconditional jump to a labeled block."""
    label: str

    def __repr__(self):
        return f'jmp {self.label}'

@dataclass
class JumpIf:
    """Conditional jump. Condition codes: e, ne, l, le, g, ge."""
    cc: str
    label: str

    def __repr__(self):
        return f'j{self.cc} {self.label}'

Instruction = Union[Instr, Callq, Jump, JumpIf]

# === Program Structure ===

@dataclass
class X86Program:
    """An x86 program as a control-flow graph of basic blocks.

    blocks: dict mapping label -> list of instructions
    stack_space: bytes needed on stack for spilled variables (set by allocator)
    used_callee_saved: list of callee-saved register names used (set by allocator)
    """
    blocks: Dict[str, List[Instruction]]
    stack_space: int = 0
    used_callee_saved: List[str] = field(default_factory=list)

# === Register Conventions ===

CALLER_SAVED = frozenset({'rax', 'rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11'})
CALLEE_SAVED = frozenset({'rbx', 'r12', 'r13', 'r14'})

# Registers available for allocation, indexed by color number.
# rax is reserved (return value / temp). rbp, rsp, r15 are reserved.
ALLOCATABLE = ['rcx', 'rdx', 'rsi', 'rdi', 'r8', 'r9', 'r10', 'r11',
               'rbx', 'r12', 'r13', 'r14']

ARG_REGISTERS = ['rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9']

# === Read/Write Analysis ===

def _locations_in(operand: Operand) -> Set[Location]:
    """Extract the location(s) referenced by an operand."""
    if isinstance(operand, (Reg, Var)):
        return {operand}
    elif isinstance(operand, Deref):
        return {Reg(operand.reg)}
    return set()

def reads(instr: Instruction) -> Set[Location]:
    """Return the set of locations read by an instruction."""
    if isinstance(instr, Instr):
        name = instr.name
        if name in ('movq', 'movzbq'):
            return _locations_in(instr.args[0])
        elif name == 'negq':
            return _locations_in(instr.args[0])
        elif name in ('addq', 'subq', 'xorq', 'andq', 'cmpq'):
            return _locations_in(instr.args[0]) | _locations_in(instr.args[1])
        elif name in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
            return set()
        elif name == 'leaq':
            return set()
    elif isinstance(instr, Callq):
        return {Reg(r) for r in ARG_REGISTERS[:instr.num_args]}
    return set()

def writes(instr: Instruction) -> Set[Location]:
    """Return the set of locations written by an instruction."""
    if isinstance(instr, Instr):
        name = instr.name
        if name in ('movq', 'movzbq', 'leaq'):
            return _locations_in(instr.args[-1])
        elif name == 'negq':
            return _locations_in(instr.args[0])
        elif name in ('addq', 'subq', 'xorq', 'andq'):
            return _locations_in(instr.args[-1])
        elif name == 'cmpq':
            return set()
        elif name in ('sete', 'setne', 'setl', 'setle', 'setg', 'setge'):
            return _locations_in(instr.args[0])
    elif isinstance(instr, Callq):
        return {Reg(r) for r in CALLER_SAVED}
    return set()

def is_move(instr: Instruction) -> bool:
    """Check if instruction is a register-to-register or var-to-var move."""
    return (isinstance(instr, Instr)
            and instr.name == 'movq'
            and isinstance(instr.args[0], (Reg, Var))
            and isinstance(instr.args[1], (Reg, Var)))

def variables_in_program(program: X86Program) -> Set[Var]:
    """Collect all Var operands appearing anywhere in the program."""
    result = set()
    for label, instrs in program.blocks.items():
        for instr in instrs:
            if isinstance(instr, Instr):
                for arg in instr.args:
                    if isinstance(arg, Var):
                        result.add(arg)
    return result

def successors(instr: Instruction) -> List[str]:
    """Return successor block labels for a control-flow instruction."""
    if isinstance(instr, Jump):
        return [instr.label]
    elif isinstance(instr, JumpIf):
        return [instr.label]
    return []

def block_successors(block: List[Instruction]) -> List[str]:
    """Return all successor block labels reachable from a basic block."""
    result = []
    for instr in block:
        result.extend(successors(instr))
    return result
