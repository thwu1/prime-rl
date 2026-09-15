
"""
Intermediate Representation (IR) data structures for a simple compiler.

The IR is a linear sequence of instructions that operate on named variables (IRVar).
It supports integer and boolean constants, variable copies, function/operator calls,
unconditional jumps, conditional jumps, and labels.

All instructions are immutable (frozen dataclasses).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IRVar:
    """Represents a named storage location or built-in reference."""
    name: str

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"IRVar('{self.name}')"

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, IRVar) and self.name == other.name


@dataclass(frozen=True)
class Instruction:
    """Base class for all IR instructions."""
    pass


@dataclass(frozen=True)
class LoadIntConst(Instruction):
    """Load an integer constant into dest."""
    value: int
    dest: IRVar


@dataclass(frozen=True)
class LoadBoolConst(Instruction):
    """Load a boolean constant into dest."""
    value: bool
    dest: IRVar


@dataclass(frozen=True)
class Copy(Instruction):
    """Copy the value of source into dest."""
    source: IRVar
    dest: IRVar


@dataclass(frozen=True)
class Call(Instruction):
    """
    Call a function or built-in operator.
    fun: the IRVar naming the function/operator (e.g., IRVar('+'), IRVar('print_int'))
    args: tuple of IRVar arguments
    dest: IRVar to store the return value
    """
    fun: IRVar
    args: tuple  # tuple of IRVar
    dest: IRVar


@dataclass(frozen=True)
class Jump(Instruction):
    """Unconditional jump to the named label."""
    label: str


@dataclass(frozen=True)
class CondJump(Instruction):
    """
    Conditional jump: if cond is truthy, jump to then_label; otherwise jump to else_label.
    """
    cond: IRVar
    then_label: str
    else_label: str


@dataclass(frozen=True)
class Label(Instruction):
    """A label that serves as a jump target."""
    name: str
