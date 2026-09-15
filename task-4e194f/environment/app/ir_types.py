
from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class Instruction:
    """A single IR instruction."""
    op: str
    dest: Optional[str] = None
    args: List[Union[str, int]] = field(default_factory=list)

    def __repr__(self):
        if self.dest:
            return f"{self.dest} = {self.op} {' '.join(str(a) for a in self.args)}"
        return f"{self.op} {' '.join(str(a) for a in self.args)}"


@dataclass
class BasicBlock:
    """A basic block with a label and a list of instructions."""
    label: str
    instructions: List[Instruction] = field(default_factory=list)


@dataclass
class Function:
    """A function definition."""
    name: str
    params: List[str] = field(default_factory=list)
    blocks: List[BasicBlock] = field(default_factory=list)


@dataclass
class Program:
    """A complete IR program (one or more functions)."""
    functions: List[Function] = field(default_factory=list)
