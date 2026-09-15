"""IR data structures for pseudo-x86-64 assembly.

"""
from dataclasses import dataclass, field
from typing import Union
import copy


@dataclass(frozen=True)
class VReg:
    """Virtual register (to be allocated by the register allocator)."""
    name: str
    def __repr__(self): return f"VReg('{self.name}')"
    def __str__(self): return f"v:{self.name}"


@dataclass(frozen=True)
class PReg:
    """Physical x86-64 register."""
    name: str
    def __repr__(self): return f"PReg('{self.name}')"
    def __str__(self): return f"%{self.name}"


@dataclass(frozen=True)
class Imm:
    """Immediate integer value."""
    value: int
    def __repr__(self): return f"Imm({self.value})"
    def __str__(self): return f"${self.value}"


@dataclass(frozen=True)
class Deref:
    """Memory reference: offset(%reg). Used for stack spill slots."""
    reg: str
    offset: int
    def __repr__(self): return f"Deref('{self.reg}', {self.offset})"
    def __str__(self): return f"{self.offset}(%{self.reg})"


Operand = Union[VReg, PReg, Imm, Deref]
Location = Union[VReg, PReg, Deref]


@dataclass
class Instr:
    """A pseudo-x86-64 instruction."""
    op: str
    args: list

    def __repr__(self):
        return f"Instr('{self.op}', {self.args})"

    def __str__(self):
        if self.args:
            return f"  {self.op} {', '.join(str(a) for a in self.args)}"
        return f"  {self.op}"


@dataclass
class Block:
    """A basic block in the control flow graph."""
    label: str
    instrs: list = field(default_factory=list)


@dataclass
class CFG:
    """Control flow graph: a collection of labeled basic blocks."""
    blocks: dict = field(default_factory=dict)   # label -> Block
    entry: str = "start"

    def __str__(self):
        lines = []
        for label in self.blocks:
            lines.append(f"{label}:")
            for instr in self.blocks[label].instrs:
                lines.append(str(instr))
        return '\n'.join(lines)

    def deep_copy(self):
        return copy.deepcopy(self)
