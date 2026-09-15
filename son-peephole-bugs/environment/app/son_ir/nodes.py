"""
Sea of Nodes IR - Node definitions.

Inspired by the Tilde Backend (TB) compiler project by Yasser Arguelles.
The IR uses a Sea of Nodes representation where nodes represent operations
and edges represent data dependencies.
"""

from enum import IntEnum, auto


class DataType:
    """Represents the data type of a node's output value."""

    __slots__ = ['bits']

    def __init__(self, bits):
        self.bits = bits

    def mask(self):
        """Bitmask for this type's width."""
        return (1 << self.bits) - 1

    def __eq__(self, other):
        return isinstance(other, DataType) and self.bits == other.bits

    def __hash__(self):
        return hash(self.bits)

    def __repr__(self):
        return f"i{self.bits}"


# Common data types
I1 = DataType(1)
I8 = DataType(8)
I16 = DataType(16)
I32 = DataType(32)
I64 = DataType(64)


class NodeType(IntEnum):
    """Enumeration of all IR node types."""

    # Leaf nodes
    ICONST = 0
    PARAM = 1

    # Arithmetic binary ops
    ADD = 10
    SUB = 11
    MUL = 12
    UDIV = 13
    SDIV = 14

    # Arithmetic unary ops
    NEG = 17

    # Bitwise binary ops
    AND = 20
    OR = 21
    XOR = 22
    NOT = 23

    # Shift ops
    SHL = 30
    SHR = 31   # logical (unsigned) right shift
    SAR = 32   # arithmetic (signed) right shift

    # Comparison ops (result type is I1)
    CMP_EQ = 40
    CMP_NE = 41
    CMP_SLT = 42
    CMP_SLE = 43
    CMP_ULT = 44
    CMP_ULE = 45

    # Miscellaneous
    SELECT = 50   # select(cond, true_val, false_val)
    ZEXT = 51     # zero extend
    SEXT = 52     # sign extend
    TRUNC = 53    # truncate


_next_node_id = 0


def _alloc_id():
    global _next_node_id
    nid = _next_node_id
    _next_node_id += 1
    return nid


def reset_node_ids():
    """Reset the global node ID counter (useful for testing)."""
    global _next_node_id
    _next_node_id = 0


class Node:
    """
    A single node in the Sea of Nodes IR graph.

    Each node has a type (operation), a data type (bit width of the result),
    a list of input edges, and optionally extra data (value for constants,
    parameter index for params).
    """

    __slots__ = ['type', 'dt', 'inputs', 'value', 'param_idx', 'id']

    def __init__(self, node_type, dt, inputs, value=None, param_idx=None):
        self.type = node_type
        self.dt = dt
        self.inputs = list(inputs)
        self.value = value
        self.param_idx = param_idx
        self.id = _alloc_id()

    def __repr__(self):
        if self.type == NodeType.ICONST:
            return f"v{self.id}:iconst({self.value:#x}, {self.dt})"
        elif self.type == NodeType.PARAM:
            return f"v{self.id}:param({self.param_idx}, {self.dt})"
        else:
            ins = ", ".join(f"v{i.id}" for i in self.inputs)
            return f"v{self.id}:{self.type.name.lower()}({ins}, {self.dt})"
