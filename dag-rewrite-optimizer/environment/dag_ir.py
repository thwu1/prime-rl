"""
DAG-based Intermediate Representation for computation graphs.

Inspired by tinygrad's UOp system, this module provides a graph-based IR where
nodes represent operations on 32-bit unsigned integers. The DAG supports
evaluation (interpretation) and graph transformations via substitution.

All arithmetic is performed modulo 2^32 (unsigned 32-bit).

"""
from __future__ import annotations
import enum
from dataclasses import dataclass
from typing import Any

MASK32 = 0xFFFFFFFF


class Op(enum.Enum):
    CONST = "const"    # Constant value. arg = int value (masked to 32-bit)
    ARG = "arg"        # Function argument. arg = argument index (0-based)
    ADD = "add"        # a + b (mod 2^32)
    SUB = "sub"        # a - b (mod 2^32)
    MUL = "mul"        # a * b (mod 2^32)
    AND = "and"        # a & b
    OR = "or"          # a | b
    XOR = "xor"        # a ^ b
    SHL = "shl"        # a << (b & 31)  (logical left shift)
    SHR = "shr"        # a >> (b & 31)  (logical right shift)
    NEG = "neg"        # -a (two's complement negation, mod 2^32)
    NOT = "not"        # ~a (bitwise complement)
    CMPLT = "cmplt"    # 1 if a < b (unsigned), else 0
    CMPEQ = "cmpeq"    # 1 if a == b, else 0
    WHERE = "where"    # cond ? true_val : false_val  (cond != 0 means true)


LEAF_OPS = frozenset({Op.CONST, Op.ARG})
UNARY_OPS = frozenset({Op.NEG, Op.NOT})
BINARY_OPS = frozenset({
    Op.ADD, Op.SUB, Op.MUL, Op.AND, Op.OR, Op.XOR,
    Op.SHL, Op.SHR, Op.CMPLT, Op.CMPEQ,
})
COMMUTATIVE_OPS = frozenset({Op.ADD, Op.MUL, Op.AND, Op.OR, Op.XOR, Op.CMPEQ})


@dataclass(frozen=True)
class Node:
    """An immutable node in the computation DAG."""
    id: int
    op: Op
    srcs: tuple       # Tuple of source node IDs (ints)
    arg: Any = None   # For CONST: int value.  For ARG: argument index.


class DAG:
    """A directed acyclic graph representing a computation on uint32 values."""

    def __init__(self):
        self.nodes: dict[int, Node] = {}
        self.outputs: list[int] = []
        self._next_id: int = 0

    # ---- node creation ----

    def _add(self, op: Op, srcs: tuple = (), arg: Any = None) -> int:
        nid = self._next_id
        self._next_id += 1
        self.nodes[nid] = Node(nid, op, srcs, arg)
        return nid

    def const(self, value: int) -> int:
        return self._add(Op.CONST, arg=value & MASK32)

    def arg(self, index: int) -> int:
        return self._add(Op.ARG, arg=index)

    def add(self, a: int, b: int) -> int:
        return self._add(Op.ADD, (a, b))

    def sub(self, a: int, b: int) -> int:
        return self._add(Op.SUB, (a, b))

    def mul(self, a: int, b: int) -> int:
        return self._add(Op.MUL, (a, b))

    def and_(self, a: int, b: int) -> int:
        return self._add(Op.AND, (a, b))

    def or_(self, a: int, b: int) -> int:
        return self._add(Op.OR, (a, b))

    def xor(self, a: int, b: int) -> int:
        return self._add(Op.XOR, (a, b))

    def shl(self, a: int, b: int) -> int:
        return self._add(Op.SHL, (a, b))

    def shr(self, a: int, b: int) -> int:
        return self._add(Op.SHR, (a, b))

    def neg(self, a: int) -> int:
        return self._add(Op.NEG, (a,))

    def not_(self, a: int) -> int:
        return self._add(Op.NOT, (a,))

    def cmplt(self, a: int, b: int) -> int:
        return self._add(Op.CMPLT, (a, b))

    def cmpeq(self, a: int, b: int) -> int:
        return self._add(Op.CMPEQ, (a, b))

    def where(self, cond: int, true_val: int, false_val: int) -> int:
        return self._add(Op.WHERE, (cond, true_val, false_val))

    def set_outputs(self, outputs: list[int]):
        self.outputs = list(outputs)

    # ---- graph analysis ----

    def toposort(self) -> list[int]:
        """Return node IDs in topological order (dependencies first)."""
        visited: set[int] = set()
        order: list[int] = []

        def visit(nid: int):
            if nid in visited:
                return
            visited.add(nid)
            node = self.nodes[nid]
            for src in node.srcs:
                visit(src)
            order.append(nid)

        for oid in self.outputs:
            visit(oid)
        return order

    def reachable(self) -> set[int]:
        """Return the set of node IDs reachable from outputs."""
        return set(self.toposort())

    def computational_node_count(self) -> int:
        """Count non-CONST, non-ARG nodes reachable from outputs."""
        return sum(1 for nid in self.reachable()
                   if self.nodes[nid].op not in LEAF_OPS)

    def total_node_count(self) -> int:
        """Count all nodes reachable from outputs."""
        return len(self.reachable())

    # ---- evaluation ----

    def evaluate(self, args: list[int]) -> list[int]:
        """Evaluate the DAG with the given arguments (32-bit unsigned)."""
        values: dict[int, int] = {}
        for nid in self.toposort():
            node = self.nodes[nid]
            s = [values[sid] for sid in node.srcs]
            if node.op == Op.CONST:
                values[nid] = node.arg & MASK32
            elif node.op == Op.ARG:
                values[nid] = args[node.arg] & MASK32
            elif node.op == Op.ADD:
                values[nid] = (s[0] + s[1]) & MASK32
            elif node.op == Op.SUB:
                values[nid] = (s[0] - s[1]) & MASK32
            elif node.op == Op.MUL:
                values[nid] = (s[0] * s[1]) & MASK32
            elif node.op == Op.AND:
                values[nid] = s[0] & s[1]
            elif node.op == Op.OR:
                values[nid] = s[0] | s[1]
            elif node.op == Op.XOR:
                values[nid] = s[0] ^ s[1]
            elif node.op == Op.SHL:
                values[nid] = (s[0] << (s[1] & 0x1F)) & MASK32
            elif node.op == Op.SHR:
                values[nid] = (s[0] >> (s[1] & 0x1F)) & MASK32
            elif node.op == Op.NEG:
                values[nid] = (-s[0]) & MASK32
            elif node.op == Op.NOT:
                values[nid] = (~s[0]) & MASK32
            elif node.op == Op.CMPLT:
                values[nid] = 1 if (s[0] & MASK32) < (s[1] & MASK32) else 0
            elif node.op == Op.CMPEQ:
                values[nid] = 1 if (s[0] & MASK32) == (s[1] & MASK32) else 0
            elif node.op == Op.WHERE:
                values[nid] = s[1] if s[0] != 0 else s[2]
            else:
                raise ValueError(f"Unknown op: {node.op}")
        return [values[oid] & MASK32 for oid in self.outputs]

    # ---- transformations ----

    def substitute(self, old_id: int, new_id: int) -> DAG:
        """Return a new DAG with all references to old_id replaced by new_id."""
        new_dag = DAG()
        new_dag._next_id = self._next_id
        for nid, node in self.nodes.items():
            new_srcs = tuple(new_id if s == old_id else s for s in node.srcs)
            new_dag.nodes[nid] = Node(nid, node.op, new_srcs, node.arg)
        new_dag.outputs = [new_id if oid == old_id else oid for oid in self.outputs]
        return new_dag

    def compact(self) -> DAG:
        """Remove unreachable nodes and re-index from 0."""
        reachable_ids = self.reachable()
        old_to_new: dict[int, int] = {}
        new_dag = DAG()
        for nid in self.toposort():
            if nid not in reachable_ids:
                continue
            node = self.nodes[nid]
            new_srcs = tuple(old_to_new[s] for s in node.srcs)
            new_id = new_dag._add(node.op, new_srcs, node.arg)
            old_to_new[nid] = new_id
        new_dag.outputs = [old_to_new[oid] for oid in self.outputs]
        return new_dag

    def copy(self) -> DAG:
        """Return a deep copy of this DAG."""
        new_dag = DAG()
        new_dag._next_id = self._next_id
        for nid, node in self.nodes.items():
            new_dag.nodes[nid] = node
        new_dag.outputs = list(self.outputs)
        return new_dag

    def dump(self) -> str:
        """Return a human-readable string representation."""
        lines = []
        for nid in self.toposort():
            node = self.nodes[nid]
            if node.op == Op.CONST:
                lines.append(f"  n{nid} = CONST({node.arg:#x})")
            elif node.op == Op.ARG:
                lines.append(f"  n{nid} = ARG({node.arg})")
            elif node.op in UNARY_OPS:
                lines.append(f"  n{nid} = {node.op.name}(n{node.srcs[0]})")
            elif node.op in BINARY_OPS:
                lines.append(f"  n{nid} = {node.op.name}(n{node.srcs[0]}, n{node.srcs[1]})")
            elif node.op == Op.WHERE:
                lines.append(f"  n{nid} = WHERE(n{node.srcs[0]}, n{node.srcs[1]}, n{node.srcs[2]})")
        out_str = ", ".join(f"n{oid}" for oid in self.outputs)
        lines.append(f"  outputs: [{out_str}]")
        return "DAG {\n" + "\n".join(lines) + "\n}"
