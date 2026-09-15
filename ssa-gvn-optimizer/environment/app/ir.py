"""
ir.py - Toy SSA IR with control flow graph.


This module provides the IR data structures for a simple SSA-based
intermediate representation with basic blocks, phi nodes, and
control flow.

Value references are strings (e.g., "a0" for arguments, "v0" for
instruction results). Integer literals appear only as:
  - The value in 'const' instructions: v0 = const 42
  - The offset in 'load'/'store' instructions: v1 = load v0 8

Pure operations (safe to value-number):
  add, mul, sub, lshift, rshift, bitand, bitor, bitxor, eq, lt, gt

Commutative operations (operand order doesn't matter):
  add, mul, bitand, bitor, bitxor, eq

Memory operations:
  load obj offset       -- read from (obj, offset)
  store obj offset val  -- write val to (obj, offset)

Side-effect operations (conservatively clobber all memory state):
  call, print
"""

from typing import Dict, List, Optional, Set, Tuple


COMMUTATIVE_OPS = frozenset({"add", "mul", "bitand", "bitor", "bitxor", "eq"})

PURE_OPS = frozenset({
    "add", "mul", "sub", "lshift", "rshift",
    "bitand", "bitor", "bitxor", "eq", "lt", "gt",
})

SIDE_EFFECT_OPS = frozenset({"call", "print"})


class Instr:
    """An SSA instruction: dst = op arg1 arg2 ..."""
    __slots__ = ("dst", "op", "args")

    def __init__(self, dst: str, op: str, args: list):
        self.dst = dst
        self.op = op
        self.args = list(args)

    def __repr__(self):
        args_str = " ".join(str(a) for a in self.args)
        return f"{self.dst} = {self.op} {args_str}"

    def clone(self) -> "Instr":
        return Instr(self.dst, self.op, list(self.args))


class Phi:
    """A phi node: dst = phi pred1:val1 pred2:val2 ..."""
    __slots__ = ("dst", "incoming")

    def __init__(self, dst: str, incoming: Dict[str, str]):
        self.dst = dst
        self.incoming = dict(incoming)

    def __repr__(self):
        parts = " ".join(f"{k}:{v}" for k, v in sorted(self.incoming.items()))
        return f"{self.dst} = phi {parts}"

    def clone(self) -> "Phi":
        return Phi(self.dst, dict(self.incoming))


class Terminator:
    """Block terminator: jump target | branch cond t_bb f_bb | return val"""
    __slots__ = ("op", "args")

    def __init__(self, op: str, args: list):
        self.op = op
        self.args = list(args)

    def __repr__(self):
        args_str = " ".join(str(a) for a in self.args)
        return f"{self.op} {args_str}"

    def clone(self) -> "Terminator":
        return Terminator(self.op, list(self.args))


class Block:
    """A basic block in the CFG."""

    def __init__(self, name: str):
        self.name = name
        self.phis: List[Phi] = []
        self.instrs: List[Instr] = []
        self.term: Optional[Terminator] = None

    def successors(self) -> List[str]:
        if self.term is None:
            return []
        if self.term.op == "jump":
            return [self.term.args[0]]
        elif self.term.op == "branch":
            return [self.term.args[1], self.term.args[2]]
        return []

    def defined_values(self) -> List[str]:
        return [p.dst for p in self.phis] + [i.dst for i in self.instrs]

    def __repr__(self):
        lines = [f"{self.name}:"]
        for p in self.phis:
            lines.append(f"  {p}")
        for i in self.instrs:
            lines.append(f"  {i}")
        if self.term:
            lines.append(f"  {self.term}")
        return "\n".join(lines)


class Function:
    """An SSA function with a control-flow graph."""

    def __init__(self, name: str, n_args: int):
        self.name = name
        self.n_args = n_args
        self.blocks: Dict[str, Block] = {}
        self.block_order: List[str] = []
        self.entry: Optional[str] = None

    def add_block(self, name: str) -> Block:
        b = Block(name)
        self.blocks[name] = b
        self.block_order.append(name)
        if self.entry is None:
            self.entry = name
        return b

    def predecessors(self, block_name: str) -> List[str]:
        return [
            b.name
            for b in self.blocks.values()
            if block_name in b.successors()
        ]

    def __repr__(self):
        lines = [f"function {self.name}({self.n_args} args):"]
        for bname in self.block_order:
            lines.append(str(self.blocks[bname]))
        return "\n".join(lines)

    def deep_copy(self) -> "Function":
        f = Function(self.name, self.n_args)
        for bname in self.block_order:
            old_b = self.blocks[bname]
            new_b = f.add_block(bname)
            new_b.phis = [p.clone() for p in old_b.phis]
            new_b.instrs = [i.clone() for i in old_b.instrs]
            new_b.term = old_b.term.clone() if old_b.term else None
        return f


# --------------- Utility helpers ---------------

def count_ops(func: Function, opcode: str) -> int:
    """Count instructions with the given opcode across all blocks."""
    return sum(
        1 for b in func.blocks.values() for i in b.instrs if i.op == opcode
    )


def find_instrs(func: Function, opcode: str) -> List[Instr]:
    """Find all instructions with a given opcode, in block order."""
    return [
        i
        for bname in func.block_order
        for i in func.blocks[bname].instrs
        if i.op == opcode
    ]


def find_phis(func: Function) -> List[Phi]:
    """Find all phi nodes in the function, in block order."""
    return [
        p
        for bname in func.block_order
        for p in func.blocks[bname].phis
    ]


# --------------- Simple interpreter ---------------

def interpret(
    func: Function,
    args: List[int],
    initial_heap: Optional[Dict[Tuple[int, int], int]] = None,
) -> int:
    """Interpret the function with given arguments.

    Objects are represented by integer IDs.  The heap maps
    (object_id, offset) -> stored value (default 0 for uninitialized).

    Returns the value passed to the ``return`` terminator.
    """
    if len(args) != func.n_args:
        raise ValueError(f"Expected {func.n_args} args, got {len(args)}")

    env: Dict[str, int] = {f"a{i}": a for i, a in enumerate(args)}
    heap: Dict[Tuple[int, int], int] = dict(initial_heap or {})

    def val(x):
        if isinstance(x, int):
            return x
        return env[x]

    current = func.entry
    prev = None

    for _ in range(100_000):
        block = func.blocks[current]

        # Phis execute "simultaneously"
        phi_vals = {}
        for phi in block.phis:
            if prev is not None and prev in phi.incoming:
                phi_vals[phi.dst] = val(phi.incoming[prev])
            elif len(phi.incoming) == 1:
                phi_vals[phi.dst] = val(next(iter(phi.incoming.values())))
        env.update(phi_vals)

        # Instructions
        for instr in block.instrs:
            op, a = instr.op, instr.args
            if op == "const":
                env[instr.dst] = a[0]
            elif op == "add":
                env[instr.dst] = val(a[0]) + val(a[1])
            elif op == "sub":
                env[instr.dst] = val(a[0]) - val(a[1])
            elif op == "mul":
                env[instr.dst] = val(a[0]) * val(a[1])
            elif op == "lshift":
                env[instr.dst] = val(a[0]) << val(a[1])
            elif op == "rshift":
                env[instr.dst] = val(a[0]) >> val(a[1])
            elif op == "bitand":
                env[instr.dst] = val(a[0]) & val(a[1])
            elif op == "bitor":
                env[instr.dst] = val(a[0]) | val(a[1])
            elif op == "bitxor":
                env[instr.dst] = val(a[0]) ^ val(a[1])
            elif op == "eq":
                env[instr.dst] = 1 if val(a[0]) == val(a[1]) else 0
            elif op == "lt":
                env[instr.dst] = 1 if val(a[0]) < val(a[1]) else 0
            elif op == "gt":
                env[instr.dst] = 1 if val(a[0]) > val(a[1]) else 0
            elif op == "load":
                env[instr.dst] = heap.get((val(a[0]), val(a[1])), 0)
            elif op == "store":
                heap[(val(a[0]), val(a[1]))] = val(a[2])
                env[instr.dst] = 0
            elif op == "call":
                # Simplified: return first value-arg (a[1]) or 0
                env[instr.dst] = val(a[1]) if len(a) > 1 else 0
            elif op == "print":
                env[instr.dst] = val(a[0])
            else:
                raise ValueError(f"Unknown opcode: {op}")

        # Terminator
        prev = current
        if block.term.op == "return":
            return val(block.term.args[0])
        elif block.term.op == "jump":
            current = block.term.args[0]
        elif block.term.op == "branch":
            cond = val(block.term.args[0])
            current = block.term.args[1] if cond else block.term.args[2]

    raise RuntimeError("Exceeded max steps")
