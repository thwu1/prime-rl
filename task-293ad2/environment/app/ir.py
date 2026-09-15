"""
Sea-of-Nodes IR Framework for Integer Computations.

Provides a graph-based intermediate representation for integer arithmetic
programs, inspired by the Sea of Nodes architecture used in compiler
backends such as the Tilde Backend (TB) and HotSpot's C2.

Nodes are connected by def-use edges. Each node has:
  - An operation type (Op)
  - A data type (DataType) describing the result
  - A list of input nodes
  - A list of users (nodes that use this node as input)
  - An optional extra field (constant value, parameter index, etc.)

The Graph class manages nodes, provides builder methods, evaluation
(interpretation), and utilities for node replacement and dead code removal.
"""


from enum import IntEnum
from typing import List, Optional, Dict, Tuple, Any


class DataType(IntEnum):
    """Integer data types identified by their bit width."""
    I1  = 1
    I8  = 8
    I16 = 16
    I32 = 32
    I64 = 64

    @property
    def mask(self) -> int:
        return (1 << self.value) - 1

    def truncate(self, val: int) -> int:
        """Truncate an arbitrary integer to this type's unsigned range."""
        return val & self.mask

    def sign_extend(self, val: int) -> int:
        """Interpret an unsigned value as signed in this type's range."""
        val = val & self.mask
        sign_bit = 1 << (self.value - 1)
        if val & sign_bit:
            return val - (1 << self.value)
        return val


class Op(IntEnum):
    """Node operation types."""
    # Leaf nodes
    ICONST = 0      # integer constant; extra = unsigned value
    PARAM  = 1      # function parameter; extra = parameter index

    # Arithmetic (binary, integer)
    ADD  = 10
    SUB  = 11
    MUL  = 12
    UDIV = 13       # unsigned division
    SDIV = 14       # signed (truncating) division
    UMOD = 15       # unsigned modulo
    SMOD = 16       # signed modulo (C semantics: a - (a/b)*b)

    # Bitwise (binary, integer)
    AND  = 20
    OR   = 21
    XOR  = 22
    SHL  = 23       # shift left
    LSHR = 24       # logical shift right (zero-fill)
    ASHR = 25       # arithmetic shift right (sign-fill)

    # Comparisons (binary, result is I1)
    CMP_EQ  = 30
    CMP_NE  = 31
    CMP_SLT = 32    # signed less-than
    CMP_SLE = 33    # signed less-or-equal
    CMP_ULT = 34    # unsigned less-than
    CMP_ULE = 35    # unsigned less-or-equal

    # Casts (unary)
    TRUNC = 40      # truncate to narrower type
    ZEXT  = 41      # zero-extend to wider type
    SEXT  = 42      # sign-extend to wider type

    # Misc
    SELECT = 50     # select(cond:I1, true_val, false_val)
    NEG    = 51     # arithmetic negation: 0 - x
    NOT    = 52     # bitwise complement: x ^ all_ones

    @property
    def is_binary(self) -> bool:
        return 10 <= self.value <= 35

    @property
    def is_commutative(self) -> bool:
        return self in (Op.ADD, Op.MUL, Op.AND, Op.OR, Op.XOR,
                        Op.CMP_EQ, Op.CMP_NE)

    @property
    def is_comparison(self) -> bool:
        return 30 <= self.value <= 35

    @property
    def is_unary(self) -> bool:
        return self in (Op.NEG, Op.NOT)


class Node:
    """A node in the Sea-of-Nodes IR graph."""
    __slots__ = ['id', 'op', 'dt', 'inputs', 'users', 'extra']

    def __init__(self, nid: int, op: Op, dt: DataType,
                 inputs: List['Node'], extra: Any = None):
        self.id = nid
        self.op = op
        self.dt = dt
        self.inputs = inputs
        self.users: List[Tuple['Node', int]] = []
        self.extra = extra

    def __repr__(self):
        name = self.op.name.lower()
        dt_name = self.dt.name.lower()
        if self.op == Op.ICONST:
            return f"v{self.id} = iconst.{dt_name} {self.extra}"
        if self.op == Op.PARAM:
            return f"v{self.id} = param.{dt_name} p{self.extra}"
        if self.op == Op.SELECT:
            i = self.inputs
            return (f"v{self.id} = select.{dt_name} "
                    f"v{i[0].id}, v{i[1].id}, v{i[2].id}")
        if self.op.is_unary or self.op in (Op.TRUNC, Op.ZEXT, Op.SEXT):
            return f"v{self.id} = {name}.{dt_name} v{self.inputs[0].id}"
        if self.op.is_binary:
            return (f"v{self.id} = {name}.{dt_name} "
                    f"v{self.inputs[0].id}, v{self.inputs[1].id}")
        return f"v{self.id} = {name}"

    @property
    def is_const(self) -> bool:
        return self.op == Op.ICONST

    @property
    def const_val(self) -> Optional[int]:
        """Return the constant value if ICONST, else None."""
        return self.extra if self.op == Op.ICONST else None


# ---------------------------------------------------------------------------
# Helpers for C-style signed integer arithmetic
# ---------------------------------------------------------------------------

def _c_sdiv(a: int, b: int) -> int:
    """C-style truncating signed division (toward zero)."""
    if b == 0:
        return 0
    q = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        q = -q
    return q


def _c_smod(a: int, b: int) -> int:
    """C-style signed modulo: a - (a/b)*b."""
    if b == 0:
        return 0
    return a - _c_sdiv(a, b) * b


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class Graph:
    """
    An expression DAG using Sea-of-Nodes style representation.

    Build expressions with the builder methods (add, sub, mul, ...), set a
    result node with set_result(), then evaluate with evaluate() or optimize
    by calling an external optimizer that operates on the graph in-place.
    """

    def __init__(self, param_types: List[DataType]):
        self._next_id: int = 0
        self.nodes: List[Node] = []
        self.param_types = param_types
        self.params: List[Node] = []
        self.result: Optional[Node] = None

        for i, dt in enumerate(param_types):
            self.params.append(self._make(Op.PARAM, dt, [], extra=i))

    # -- internal node creation ---------------------------------------------

    def _make(self, op: Op, dt: DataType, inputs: List[Node],
              extra: Any = None) -> Node:
        n = Node(self._next_id, op, dt, inputs, extra)
        self._next_id += 1
        for i, inp in enumerate(inputs):
            inp.users.append((n, i))
        self.nodes.append(n)
        return n

    # -- builder methods ----------------------------------------------------

    def iconst(self, dt: DataType, value: int) -> Node:
        return self._make(Op.ICONST, dt, [], extra=dt.truncate(value))

    def add(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.ADD, a.dt, [a, b])

    def sub(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.SUB, a.dt, [a, b])

    def mul(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.MUL, a.dt, [a, b])

    def udiv(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.UDIV, a.dt, [a, b])

    def sdiv(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.SDIV, a.dt, [a, b])

    def umod(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.UMOD, a.dt, [a, b])

    def smod(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.SMOD, a.dt, [a, b])

    def and_(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.AND, a.dt, [a, b])

    def or_(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.OR, a.dt, [a, b])

    def xor(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.XOR, a.dt, [a, b])

    def shl(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.SHL, a.dt, [a, b])

    def lshr(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.LSHR, a.dt, [a, b])

    def ashr(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.ASHR, a.dt, [a, b])

    def cmp_eq(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.CMP_EQ, DataType.I1, [a, b])

    def cmp_ne(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.CMP_NE, DataType.I1, [a, b])

    def cmp_slt(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.CMP_SLT, DataType.I1, [a,b])

    def cmp_sle(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.CMP_SLE, DataType.I1, [a,b])

    def cmp_ult(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.CMP_ULT, DataType.I1, [a,b])

    def cmp_ule(self, a: Node, b: Node) -> Node:
        assert a.dt == b.dt; return self._make(Op.CMP_ULE, DataType.I1, [a,b])

    def trunc(self, a: Node, target_dt: DataType) -> Node:
        assert target_dt.value < a.dt.value
        return self._make(Op.TRUNC, target_dt, [a])

    def zext(self, a: Node, target_dt: DataType) -> Node:
        assert target_dt.value > a.dt.value
        return self._make(Op.ZEXT, target_dt, [a])

    def sext(self, a: Node, target_dt: DataType) -> Node:
        assert target_dt.value > a.dt.value
        return self._make(Op.SEXT, target_dt, [a])

    def select(self, cond: Node, true_val: Node, false_val: Node) -> Node:
        assert cond.dt == DataType.I1
        assert true_val.dt == false_val.dt
        return self._make(Op.SELECT, true_val.dt, [cond, true_val, false_val])

    def neg(self, a: Node) -> Node:
        return self._make(Op.NEG, a.dt, [a])

    def not_(self, a: Node) -> Node:
        return self._make(Op.NOT, a.dt, [a])

    # -- result -------------------------------------------------------------

    def set_result(self, n: Node):
        self.result = n

    # -- graph mutation -----------------------------------------------------

    def replace_node(self, old: Node, new: Node):
        """Replace all uses of *old* with *new*.

        Updates user lists, input references, and self.result if needed.
        After this call *old* is disconnected from the graph.
        """
        if old is new:
            return
        # Redirect every user of old → new
        for user, slot in list(old.users):
            user.inputs[slot] = new
            new.users.append((user, slot))
        old.users.clear()
        # Remove old from its inputs' user lists
        for i, inp in enumerate(old.inputs):
            inp.users = [(u, s) for u, s in inp.users
                         if not (u is old and s == i)]
        old.inputs = []
        # Update result pointer
        if self.result is old:
            self.result = new

    def remove_dead(self):
        """Remove nodes unreachable from self.result and self.params."""
        alive: set = set()
        wl = list(self.params)
        if self.result is not None:
            wl.append(self.result)
        while wl:
            n = wl.pop()
            if n in alive:
                continue
            alive.add(n)
            wl.extend(n.inputs)
        self.nodes = [n for n in self.nodes if n in alive]
        for n in self.nodes:
            n.users = [(u, s) for u, s in n.users if u in alive]

    def rebuild_users(self):
        """Rebuild all user lists from scratch (safety net for debugging)."""
        for n in self.nodes:
            n.users = []
        for n in self.nodes:
            for i, inp in enumerate(n.inputs):
                inp.users.append((n, i))

    # -- queries ------------------------------------------------------------

    def op_count(self) -> int:
        """Count non-leaf (non-PARAM, non-ICONST) nodes."""
        return sum(1 for n in self.nodes
                   if n.op not in (Op.PARAM, Op.ICONST))

    def dump(self) -> str:
        lines = []
        for n in self.nodes:
            prefix = "=> " if n is self.result else "   "
            lines.append(f"{prefix}{n}")
        return "\n".join(lines)

    # -- evaluation (interpreter) -------------------------------------------

    def evaluate(self, param_values: List[int]) -> int:
        """Evaluate the graph with given parameter values.

        Parameters are supplied as a list in the same order as param_types.
        Returns the unsigned result of self.result.
        """
        assert len(param_values) == len(self.param_types)
        cache: Dict[int, int] = {}

        for i, p in enumerate(self.params):
            cache[p.id] = p.dt.truncate(param_values[i])

        def ev(n: Node) -> int:
            if n.id in cache:
                return cache[n.id]
            if n.op == Op.ICONST:
                cache[n.id] = n.extra
                return n.extra

            args = [ev(inp) for inp in n.inputs]
            r = _eval_op(n, args)
            cache[n.id] = r
            return r

        return ev(self.result)


def _eval_op(n: Node, args: List[int]) -> int:
    """Compute the result of a single node given evaluated input values."""
    op = n.op
    dt = n.dt
    mask = dt.mask

    if op == Op.ADD:
        return (args[0] + args[1]) & mask
    if op == Op.SUB:
        return (args[0] - args[1]) & mask
    if op == Op.MUL:
        return (args[0] * args[1]) & mask
    if op == Op.UDIV:
        return 0 if args[1] == 0 else args[0] // args[1]
    if op == Op.SDIV:
        if args[1] == 0:
            return 0
        src = n.inputs[0].dt
        return dt.truncate(_c_sdiv(src.sign_extend(args[0]),
                                   src.sign_extend(args[1])))
    if op == Op.UMOD:
        return 0 if args[1] == 0 else args[0] % args[1]
    if op == Op.SMOD:
        if args[1] == 0:
            return 0
        src = n.inputs[0].dt
        return dt.truncate(_c_smod(src.sign_extend(args[0]),
                                   src.sign_extend(args[1])))
    if op == Op.AND:
        return args[0] & args[1]
    if op == Op.OR:
        return args[0] | args[1]
    if op == Op.XOR:
        return args[0] ^ args[1]
    if op == Op.SHL:
        shift = args[1] & (n.inputs[0].dt.value - 1)
        return (args[0] << shift) & mask
    if op == Op.LSHR:
        shift = args[1] & (n.inputs[0].dt.value - 1)
        return args[0] >> shift
    if op == Op.ASHR:
        shift = args[1] & (n.inputs[0].dt.value - 1)
        src = n.inputs[0].dt
        return dt.truncate(src.sign_extend(args[0]) >> shift)

    # Comparisons
    if op == Op.CMP_EQ:
        return 1 if args[0] == args[1] else 0
    if op == Op.CMP_NE:
        return 1 if args[0] != args[1] else 0
    if op == Op.CMP_SLT:
        src = n.inputs[0].dt
        return 1 if src.sign_extend(args[0]) < src.sign_extend(args[1]) else 0
    if op == Op.CMP_SLE:
        src = n.inputs[0].dt
        return 1 if src.sign_extend(args[0]) <= src.sign_extend(args[1]) else 0
    if op == Op.CMP_ULT:
        return 1 if args[0] < args[1] else 0
    if op == Op.CMP_ULE:
        return 1 if args[0] <= args[1] else 0

    # Casts
    if op == Op.TRUNC:
        return dt.truncate(args[0])
    if op == Op.ZEXT:
        return args[0]  # already fits in wider type
    if op == Op.SEXT:
        src = n.inputs[0].dt
        return dt.truncate(src.sign_extend(args[0]))

    # Misc
    if op == Op.SELECT:
        return args[1] if args[0] else args[2]
    if op == Op.NEG:
        return dt.truncate(-args[0])
    if op == Op.NOT:
        return args[0] ^ mask

    raise ValueError(f"Unknown op: {op}")
