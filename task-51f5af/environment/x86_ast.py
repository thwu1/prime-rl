"""x86 Assembly AST definitions for register allocation.


Provides dataclass-based representations of x86-64 instructions
and operands, used by the register allocator and emulator.
"""

from dataclasses import dataclass
from typing import Dict, List


class instr:
    """Base class for x86 instructions."""
    ...

class arg:
    """Base class for instruction arguments/operands."""
    ...

class location(arg):
    """An arg that is also a storage location (register or variable)."""
    ...


@dataclass(frozen=True)
class Variable(location):
    """A virtual (pseudo) register to be allocated by the register allocator."""
    id: str

    def __str__(self):
        return self.id

    def __repr__(self):
        return f"Variable('{self.id}')"


@dataclass(frozen=True)
class Immediate(arg):
    """An integer constant operand."""
    value: int

    def __str__(self):
        return f'${self.value}'


@dataclass(frozen=True)
class Reg(location):
    """A physical x86-64 register."""
    id: str

    def __str__(self):
        return f'%{self.id}'


@dataclass(frozen=True)
class ByteReg(Reg):
    """An 8-bit sub-register (e.g., al, cl)."""
    pass


@dataclass(frozen=True)
class Deref(arg):
    """A memory reference: offset(%reg)."""
    reg: str
    offset: int

    def __str__(self):
        return f'{self.offset}(%{self.reg})'


@dataclass(frozen=True, eq=False)
class Instr(instr):
    """A generic x86 instruction (movq, addq, subq, etc.)."""
    instr: str
    args: tuple

    def __init__(self, name: str, args):
        object.__setattr__(self, 'instr', name)
        object.__setattr__(self, 'args', tuple(args))

    def __str__(self):
        return '  ' + self.instr + ' ' + ', '.join(str(a) for a in self.args)


@dataclass(frozen=True, eq=False)
class Callq(instr):
    """A direct function call instruction."""
    func: str
    num_args: int

    def __str__(self):
        return f'  callq {self.func}'


@dataclass(frozen=True, eq=False)
class Jump(instr):
    """An unconditional jump."""
    label: str

    def __str__(self):
        return f'  jmp {self.label}'


@dataclass(frozen=True, eq=False)
class JumpIf(instr):
    """A conditional jump based on EFLAGS condition code."""
    cc: str
    label: str

    def __str__(self):
        return f'  j{self.cc} {self.label}'


@dataclass
class X86Program:
    """An x86 program represented as a dict of labeled basic blocks.

    body: maps block labels (str) to lists of instructions.
    Before register allocation, instructions may contain Variable nodes.
    After allocation, only Reg and Deref operands remain.
    """
    body: Dict[str, List[instr]]

    def __str__(self):
        result = ''
        for label, instrs in self.body.items():
            result += f'{label}:\n'
            for i in instrs:
                result += f'{i}\n'
        return result
