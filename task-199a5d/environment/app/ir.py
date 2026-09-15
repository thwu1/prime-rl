"""
Three-address code IR for the register allocator task.

Programs consist of basic blocks connected by branches and jumps.
Each instruction operates on named operands:
  - Virtual registers: v0, v1, v2, ...
  - Physical registers: r0, r1, ..., r5
  - Stack slots (spills): s0, s1, s2, ...
"""


from dataclasses import dataclass
from copy import deepcopy

NUM_PHYS_REGS = 6  # r0 through r5


def is_vreg(op) -> bool:
    return isinstance(op, str) and len(op) >= 2 and op[0] == 'v' and op[1:].isdigit()

def is_preg(op) -> bool:
    return isinstance(op, str) and len(op) >= 2 and op[0] == 'r' and op[1:].isdigit()

def is_stack(op) -> bool:
    return isinstance(op, str) and len(op) >= 2 and op[0] == 's' and op[1:].isdigit()

def is_reg(op) -> bool:
    return is_vreg(op) or is_preg(op) or is_stack(op)


@dataclass
class Instr:
    """A single instruction in the IR."""
    op: str
    dst: str = None
    src1: str = None
    src2: str = None
    label1: str = None
    label2: str = None

    def defs(self):
        """Set of registers written by this instruction."""
        if self.op in ('CONST', 'ADD', 'SUB', 'MUL', 'MOD', 'MOV',
                        'CMP_LT', 'CMP_EQ'):
            return {self.dst} if is_reg(self.dst) else set()
        return set()

    def uses(self):
        """Set of registers read by this instruction."""
        result = set()
        if self.op == 'CONST':
            pass
        elif self.op == 'MOV':
            if is_reg(self.src1):
                result.add(self.src1)
        elif self.op == 'PRINT':
            if is_reg(self.src1):
                result.add(self.src1)
        elif self.op in ('ADD', 'SUB', 'MUL', 'MOD', 'CMP_LT', 'CMP_EQ'):
            if is_reg(self.src1):
                result.add(self.src1)
            if is_reg(self.src2):
                result.add(self.src2)
        elif self.op == 'BR':
            if is_reg(self.src1):
                result.add(self.src1)
        return result

    def is_move(self):
        return self.op == 'MOV'

    def successors(self):
        """Return branch/jump target labels."""
        if self.op == 'BR':
            return [self.label1, self.label2]
        elif self.op == 'JMP':
            return [self.label1]
        return []

    def is_terminator(self):
        return self.op in ('BR', 'JMP', 'RET')

    def __repr__(self):
        if self.op == 'CONST':
            return f'{self.dst} = #{self.src1}'
        elif self.op in ('ADD', 'SUB', 'MUL', 'MOD', 'CMP_LT', 'CMP_EQ'):
            return f'{self.dst} = {self.op} {self.src1} {self.src2}'
        elif self.op == 'MOV':
            return f'{self.dst} = {self.src1}'
        elif self.op == 'PRINT':
            return f'PRINT {self.src1}'
        elif self.op == 'BR':
            return f'BR {self.src1} -> {self.label1} / {self.label2}'
        elif self.op == 'JMP':
            return f'JMP {self.label1}'
        elif self.op == 'RET':
            return 'RET'
        return f'{self.op}(?)'


# Convenience constructors
def CONST(dst, val):
    return Instr('CONST', dst=dst, src1=str(val))

def ADD(dst, a, b):
    return Instr('ADD', dst=dst, src1=a, src2=b)

def SUB(dst, a, b):
    return Instr('SUB', dst=dst, src1=a, src2=b)

def MUL(dst, a, b):
    return Instr('MUL', dst=dst, src1=a, src2=b)

def MOD(dst, a, b):
    return Instr('MOD', dst=dst, src1=a, src2=b)

def MOV(dst, src):
    return Instr('MOV', dst=dst, src1=src)

def PRINT(src):
    return Instr('PRINT', src1=src)

def CMP_LT(dst, a, b):
    return Instr('CMP_LT', dst=dst, src1=a, src2=b)

def CMP_EQ(dst, a, b):
    return Instr('CMP_EQ', dst=dst, src1=a, src2=b)

def BR(cond, true_label, false_label):
    return Instr('BR', src1=cond, label1=true_label, label2=false_label)

def JMP(label):
    return Instr('JMP', label1=label)

def RET():
    return Instr('RET')


class Program:
    """A program is a mapping from block labels to instruction lists."""

    def __init__(self, blocks: dict, entry='entry'):
        self.blocks = blocks
        self.entry = entry

    def all_vregs(self):
        vregs = set()
        for instrs in self.blocks.values():
            for instr in instrs:
                for reg in instr.defs() | instr.uses():
                    if is_vreg(reg):
                        vregs.add(reg)
        return vregs

    def validate(self):
        for label, instrs in self.blocks.items():
            if not instrs or not instrs[-1].is_terminator():
                raise ValueError(f"Block '{label}' missing terminator")
            for i, instr in enumerate(instrs[:-1]):
                if instr.is_terminator():
                    raise ValueError(
                        f"Block '{label}' has terminator at position {i}")

    def copy(self):
        return deepcopy(self)

    def __repr__(self):
        lines = []
        for label in self.blocks:
            lines.append(f'{label}:')
            for instr in self.blocks[label]:
                lines.append(f'  {instr}')
        return '\n'.join(lines)
