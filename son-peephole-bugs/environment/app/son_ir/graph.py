"""
Sea of Nodes IR - Graph builder.

Provides a fluent API for constructing IR expression DAGs.
"""

from .nodes import Node, NodeType, DataType, I1, I8, I16, I32, I64


class Graph:
    """Builder for constructing Sea of Nodes IR expression DAGs."""

    def __init__(self):
        self.nodes = []

    def _add(self, node):
        self.nodes.append(node)
        return node

    # --- Leaf nodes ---

    def iconst(self, value, dt=I32):
        """Create an integer constant node."""
        return self._add(Node(NodeType.ICONST, dt, [], value=value & dt.mask()))

    def param(self, idx, dt=I32):
        """Create a function parameter node."""
        return self._add(Node(NodeType.PARAM, dt, [], param_idx=idx))

    # --- Arithmetic ---

    def add(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.ADD, a.dt, [a, b]))

    def sub(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.SUB, a.dt, [a, b]))

    def mul(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.MUL, a.dt, [a, b]))

    def udiv(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.UDIV, a.dt, [a, b]))

    def sdiv(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.SDIV, a.dt, [a, b]))

    def neg(self, a):
        return self._add(Node(NodeType.NEG, a.dt, [a]))

    # --- Bitwise ---

    def and_(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.AND, a.dt, [a, b]))

    def or_(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.OR, a.dt, [a, b]))

    def xor(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.XOR, a.dt, [a, b]))

    def not_(self, a):
        return self._add(Node(NodeType.NOT, a.dt, [a]))

    # --- Shifts ---

    def shl(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.SHL, a.dt, [a, b]))

    def shr(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.SHR, a.dt, [a, b]))

    def sar(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.SAR, a.dt, [a, b]))

    # --- Comparisons (result is always I1) ---

    def cmp_eq(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.CMP_EQ, I1, [a, b]))

    def cmp_ne(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.CMP_NE, I1, [a, b]))

    def cmp_slt(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.CMP_SLT, I1, [a, b]))

    def cmp_sle(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.CMP_SLE, I1, [a, b]))

    def cmp_ult(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.CMP_ULT, I1, [a, b]))

    def cmp_ule(self, a, b):
        assert a.dt == b.dt, f"type mismatch: {a.dt} vs {b.dt}"
        return self._add(Node(NodeType.CMP_ULE, I1, [a, b]))

    # --- Select ---

    def select(self, cond, true_val, false_val):
        assert cond.dt == I1, f"select condition must be i1, got {cond.dt}"
        assert true_val.dt == false_val.dt, \
            f"select branch types must match: {true_val.dt} vs {false_val.dt}"
        return self._add(Node(NodeType.SELECT, true_val.dt, [cond, true_val, false_val]))

    # --- Width conversions ---

    def zext(self, val, target_dt):
        assert target_dt.bits > val.dt.bits, \
            f"zext target must be wider: {val.dt} -> {target_dt}"
        return self._add(Node(NodeType.ZEXT, target_dt, [val]))

    def sext(self, val, target_dt):
        assert target_dt.bits > val.dt.bits, \
            f"sext target must be wider: {val.dt} -> {target_dt}"
        return self._add(Node(NodeType.SEXT, target_dt, [val]))

    def trunc(self, val, target_dt):
        assert target_dt.bits < val.dt.bits, \
            f"trunc target must be narrower: {val.dt} -> {target_dt}"
        return self._add(Node(NodeType.TRUNC, target_dt, [val]))

    # --- Utilities ---

    def count_nodes(self, root):
        """Count the number of unique reachable nodes from root."""
        visited = set()
        stack = [root]
        while stack:
            n = stack.pop()
            if n.id in visited:
                continue
            visited.add(n.id)
            for inp in n.inputs:
                stack.append(inp)
        return len(visited)
