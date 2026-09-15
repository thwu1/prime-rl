"""
Pseudo-x86 intermediate representation for the register allocator task.
"""
from dataclasses import dataclass
from typing import Union


# ── Operands ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Immediate:
    value: int
    def __repr__(self): return f"${self.value}"

@dataclass(frozen=True)
class Register:
    name: str
    def __repr__(self): return f"%{self.name}"

@dataclass(frozen=True)
class Variable:
    name: str
    def __repr__(self): return self.name

@dataclass(frozen=True)
class Deref:
    reg: str
    offset: int
    def __repr__(self): return f"{self.offset}(%{self.reg})"

Arg = Union[Immediate, Register, Variable, Deref]
Location = Union[Register, Variable]


# ── Instructions ──────────────────────────────────────────────────────────────

@dataclass
class Instr:
    name: str
    args: list
    def __repr__(self):
        return f"{self.name} {', '.join(str(a) for a in self.args)}"

@dataclass
class Callq:
    func: str
    num_args: int
    def __repr__(self): return f"callq {self.func}"

@dataclass
class Jump:
    label: str
    def __repr__(self): return f"jmp {self.label}"

@dataclass
class JumpIf:
    cc: str
    label: str
    def __repr__(self): return f"j{self.cc} {self.label}"

Instruction = Union[Instr, Callq, Jump, JumpIf]


# ── Program ───────────────────────────────────────────────────────────────────

@dataclass
class X86Program:
    blocks: dict  # str -> list[Instruction]


# ── Register classification ──────────────────────────────────────────────────

CALLER_SAVED = ["rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11"]
CALLEE_SAVED = ["rbx", "r12", "r13", "r14"]  # r15 reserved for root stack
ALLOCATABLE = [
    "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10",  # caller-saved (colors 0-6)
    "rbx", "r12", "r13", "r14",                       # callee-saved (colors 7-10)
]
ARG_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
NUM_REGS = len(ALLOCATABLE)  # 11

# Map from Register -> pre-assigned color
REG_COLOR = {}
for _i, _r in enumerate(ALLOCATABLE):
    REG_COLOR[Register(_r)] = _i
# Non-allocatable registers get unique negative colors
for _r, _c in {"rax": -1, "r11": -2, "r15": -3, "rsp": -4, "rbp": -5}.items():
    REG_COLOR[Register(_r)] = _c


def color_to_location(color):
    """Map a graph-coloring color to a Register or Deref (stack slot)."""
    if color < NUM_REGS:
        return Register(ALLOCATABLE[color])
    else:
        offset = -8 * (color - NUM_REGS + 1)
        return Deref("rbp", offset)


# ── Read / write sets for liveness analysis ───────────────────────────────────

def _arg_locs(op):
    """Extract the set of Variable / Register locations referenced by *op*."""
    if isinstance(op, (Variable, Register)):
        return {op}
    if isinstance(op, Deref):
        return {Register(op.reg)}
    return set()


def instr_reads(instr):
    """Locations read by *instr*."""
    if isinstance(instr, Instr):
        n = instr.name
        if n in ("movq", "movzbq"):
            return _arg_locs(instr.args[0])
        if n in ("addq", "subq", "xorq", "cmpq"):
            return _arg_locs(instr.args[0]) | _arg_locs(instr.args[1])
        if n == "negq":
            return _arg_locs(instr.args[0])
        if n == "pushq":
            return _arg_locs(instr.args[0])
        if n == "popq":
            return set()
    if isinstance(instr, Callq):
        return {Register(r) for r in ARG_REGISTERS[:instr.num_args]}
    return set()


def instr_writes(instr):
    """Locations written by *instr*."""
    if isinstance(instr, Instr):
        n = instr.name
        if n in ("movq", "addq", "subq", "negq", "xorq", "movzbq"):
            return _arg_locs(instr.args[-1])
        if n == "cmpq":
            return set()
        if n == "popq":
            return _arg_locs(instr.args[0])
    if isinstance(instr, Callq):
        return {Register(r) for r in CALLER_SAVED}
    return set()
