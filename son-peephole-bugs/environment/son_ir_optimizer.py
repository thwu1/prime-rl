"""
Sea of Nodes IR Peephole Optimizer

Implements three categories of rewrites inspired by the Tilde Backend (TB):
  * value_of  (constant folding): compute the constant result of a node
  * idealize  (algebraic simplification): replace with a simpler form
  * identity  (input substitution): replace a node with one of its inputs

Plus GVN (Global Value Numbering) for common subexpression elimination.

The optimizer processes a DAG in topological order, applying all rewrite
categories to each node until no more changes occur (local fixpoint).
"""

from .nodes import Node, NodeType, DataType, I1, I8, I16, I32, I64


# ================================================================
# Helper functions
# ================================================================

def _is_const(node, value=None):
    """Check if a node is a constant, optionally with a specific value."""
    if node.type != NodeType.ICONST:
        return False
    if value is not None:
        return node.value == (value & node.dt.mask())
    return True


def _const_val(node):
    """Get the integer value of an ICONST node."""
    assert node.type == NodeType.ICONST
    return node.value


def _make_const(value, dt):
    """Create a new ICONST node."""
    return Node(NodeType.ICONST, dt, [], value=value & dt.mask())


def _sign_extend(value, bits):
    """Sign-extend a value from the given bit width."""
    mask = (1 << bits) - 1
    value = value & mask
    if value & (1 << (bits - 1)):
        return value - (1 << bits)
    return value


def _is_power_of_2(n):
    """Check if n is a power of 2."""
    return n & (n - 1) == 0


def _log2(n):
    """Compute log2 of a power-of-2 number."""
    r = 0
    while n > 1:
        n >>= 1
        r += 1
    return r


# ================================================================
# value_of: Constant Folding
# ================================================================

def value_of(node):
    """
    Try to compute a constant value for a node whose inputs are all constants.
    Returns a new ICONST node if successful, None otherwise.
    """
    nt = node.type

    # --- Arithmetic ---
    if nt == NodeType.ADD:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(a + b, node.dt)

    elif nt == NodeType.SUB:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(a - b, node.dt)

    elif nt == NodeType.MUL:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(a * b, node.dt)

    elif nt == NodeType.UDIV:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            if b == 0:
                return None
            return _make_const(a // b, node.dt)

    elif nt == NodeType.SDIV:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _sign_extend(_const_val(node.inputs[0]), node.dt.bits)
            b = _sign_extend(_const_val(node.inputs[1]), node.dt.bits)
            if b == 0:
                return None
            result = int(a / b)
            return _make_const(result, node.dt)

    # --- Bitwise ---
    elif nt == NodeType.AND:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a_val = _const_val(node.inputs[0])
            b_val = _const_val(node.inputs[1])
            return _make_const(a_val | b_val, node.dt)

    elif nt == NodeType.OR:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(a | b, node.dt)

    elif nt == NodeType.XOR:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(a ^ b, node.dt)

    # --- Shifts ---
    elif nt == NodeType.SHL:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            if b >= node.dt.bits:
                return _make_const(0, node.dt)
            return _make_const(a << b, node.dt)

    elif nt == NodeType.SHR:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            if b >= node.dt.bits:
                return _make_const(0, node.dt)
            return _make_const(a >> b, node.dt)

    elif nt == NodeType.SAR:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _sign_extend(_const_val(node.inputs[0]), node.dt.bits)
            b = _const_val(node.inputs[1])
            if b >= node.dt.bits:
                return _make_const(node.dt.mask() if a < 0 else 0, node.dt)
            return _make_const(a >> b, node.dt)

    # --- Unary ---
    elif nt == NodeType.NEG:
        if _is_const(node.inputs[0]):
            return _make_const(-_const_val(node.inputs[0]), node.dt)

    elif nt == NodeType.NOT:
        if _is_const(node.inputs[0]):
            return _make_const(_const_val(node.inputs[0]) ^ node.dt.mask(), node.dt)

    # --- Comparisons ---
    elif nt == NodeType.CMP_EQ:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(1 if a == b else 0, I1)

    elif nt == NodeType.CMP_NE:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(1 if a != b else 0, I1)

    elif nt == NodeType.CMP_SLT:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(1 if a < b else 0, I1)

    elif nt == NodeType.CMP_SLE:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            bits = node.inputs[0].dt.bits
            a = _sign_extend(_const_val(node.inputs[0]), bits)
            b = _sign_extend(_const_val(node.inputs[1]), bits)
            return _make_const(1 if a <= b else 0, I1)

    elif nt == NodeType.CMP_ULT:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(1 if a < b else 0, I1)

    elif nt == NodeType.CMP_ULE:
        if _is_const(node.inputs[0]) and _is_const(node.inputs[1]):
            a = _const_val(node.inputs[0])
            b = _const_val(node.inputs[1])
            return _make_const(1 if a <= b else 0, I1)

    # --- Extensions and truncations ---
    elif nt == NodeType.ZEXT:
        if _is_const(node.inputs[0]):
            return _make_const(_const_val(node.inputs[0]), node.dt)

    elif nt == NodeType.SEXT:
        if _is_const(node.inputs[0]):
            val = _sign_extend(_const_val(node.inputs[0]), node.inputs[0].dt.bits)
            return _make_const(val, node.dt)

    elif nt == NodeType.TRUNC:
        if _is_const(node.inputs[0]):
            return _make_const(_const_val(node.inputs[0]), node.dt)

    return None


# ================================================================
# idealize: Algebraic Simplifications
# ================================================================

def idealize(node):
    """
    Try to algebraically simplify a node.
    Returns a replacement node or None.
    """
    nt = node.type

    if nt == NodeType.ADD:
        return _idealize_add(node)
    elif nt == NodeType.SUB:
        return _idealize_sub(node)
    elif nt == NodeType.MUL:
        return _idealize_mul(node)
    elif nt in (NodeType.AND, NodeType.OR, NodeType.XOR):
        return _idealize_bits(node)
    elif nt in (NodeType.SHL, NodeType.SHR, NodeType.SAR):
        return _idealize_shift(node)
    elif nt == NodeType.SELECT:
        return _idealize_select(node)
    elif nt in (NodeType.ZEXT, NodeType.SEXT):
        return _idealize_ext(node)

    return None


def _idealize_add(node):
    lhs, rhs = node.inputs

    # x + 0 => x
    if _is_const(rhs, 0):
        return lhs
    if _is_const(lhs, 0):
        return rhs

    # (a - b) + b => a
    if lhs.type == NodeType.SUB and lhs.inputs[0] is rhs:
        return lhs.inputs[0]

    # b + (a - b) => a
    if rhs.type == NodeType.SUB and rhs.inputs[1] is lhs:
        return rhs.inputs[0]

    # Reassociate: (x + c1) + c2 => x + (c1 + c2)
    if _is_const(rhs) and lhs.type == NodeType.ADD and _is_const(lhs.inputs[1]):
        new_c = _make_const(_const_val(lhs.inputs[1]) + _const_val(rhs), node.dt)
        return Node(NodeType.ADD, node.dt, [lhs.inputs[0], new_c])

    return None


def _idealize_sub(node):
    lhs, rhs = node.inputs

    # x - 0 => x
    if _is_const(rhs, 0):
        return lhs

    # x - x => 0
    if lhs is rhs:
        return _make_const(0, node.dt)

    # (a + b) - b => a
    if lhs.type == NodeType.ADD and lhs.inputs[1] is rhs:
        return lhs.inputs[0]

    # (a + b) - a => b
    if lhs.type == NodeType.ADD and lhs.inputs[0] is rhs:
        return lhs.inputs[1]

    return None


def _idealize_mul(node):
    lhs, rhs = node.inputs

    # x * 1 => x
    if _is_const(rhs, 1):
        return lhs
    if _is_const(lhs, 1):
        return rhs

    # Strength reduction: x * 2^n => x << n
    if _is_const(rhs) and _is_power_of_2(_const_val(rhs)):
        shift = _log2(_const_val(rhs))
        return Node(NodeType.SHL, node.dt, [lhs, _make_const(shift, node.dt)])
    if _is_const(lhs) and _is_power_of_2(_const_val(lhs)):
        shift = _log2(_const_val(lhs))
        return Node(NodeType.SHL, node.dt, [rhs, _make_const(shift, node.dt)])

    # x * 0 => 0
    if _is_const(rhs, 0):
        return rhs
    if _is_const(lhs, 0):
        return lhs

    return None


def _idealize_bits(node):
    lhs, rhs = node.inputs
    nt = node.type

    if nt == NodeType.AND:
        if _is_const(rhs, 0):
            return rhs
        if _is_const(rhs) and _const_val(rhs) == node.dt.mask():
            return lhs
        if lhs is rhs:
            return lhs

    elif nt == NodeType.OR:
        if _is_const(rhs, 0):
            return lhs
        if _is_const(rhs) and _const_val(rhs) == node.dt.mask():
            return rhs
        if lhs is rhs:
            return lhs

    elif nt == NodeType.XOR:
        if _is_const(rhs, 0):
            return lhs
        if lhs is rhs:
            return _make_const(0, node.dt)
        if lhs.type == NodeType.XOR and lhs.inputs[1] is rhs:
            return lhs.inputs[0]

    return None


def _idealize_shift(node):
    lhs, rhs = node.inputs
    nt = node.type

    # x << 0 => x
    if _is_const(rhs, 0):
        return lhs

    # Shift by >= bit width => 0 (for logical shifts)
    if _is_const(rhs) and _const_val(rhs) >= node.dt.bits:
        if nt in (NodeType.SHL, NodeType.SHR):
            return _make_const(0, node.dt)

    # Fold double left shift: (x << c1) << c2 => x << (c1 + c2) or 0
    if nt == NodeType.SHL and lhs.type == NodeType.SHL:
        if _is_const(rhs) and _is_const(lhs.inputs[1]):
            c1 = _const_val(lhs.inputs[1])
            c2 = _const_val(rhs)
            total = c1 + c2
            if total >= node.dt.bits:
                return _make_const(0, node.dt)
            return Node(NodeType.SHL, node.dt,
                        [lhs.inputs[0], _make_const(total, node.dt)])

    # Fold double logical right shift
    if nt == NodeType.SHR and lhs.type == NodeType.SHR:
        if _is_const(rhs) and _is_const(lhs.inputs[1]):
            c1 = _const_val(lhs.inputs[1])
            c2 = _const_val(rhs)
            total = c1 + c2
            if total >= node.dt.bits:
                return _make_const(0, node.dt)
            return Node(NodeType.SHR, node.dt,
                        [lhs.inputs[0], _make_const(total, node.dt)])

    return None


def _idealize_select(node):
    cond, true_val, false_val = node.inputs

    if _is_const(cond, 1):
        return true_val
    if _is_const(cond, 0):
        return false_val

    return None


def _idealize_ext(node):
    src = node.inputs[0]
    nt = node.type

    # zext(zext(x)) => zext(x)
    if nt == NodeType.ZEXT and src.type == NodeType.ZEXT:
        return Node(NodeType.ZEXT, node.dt, [src.inputs[0]])

    # sext(sext(x)) => sext(x)
    if nt == NodeType.SEXT and src.type == NodeType.SEXT:
        return Node(NodeType.SEXT, node.dt, [src.inputs[0]])

    return None


# ================================================================
# identity: Replace node with one of its inputs
# ================================================================

def identity(node):
    """
    Try to replace a node with one of its direct inputs.
    Returns an input node or None.
    """
    nt = node.type

    if nt == NodeType.SELECT:
        # select(cond, a, a) => a  (both branches are the same node)
        if node.inputs[0] is node.inputs[1]:
            return node.inputs[1]

    elif nt == NodeType.TRUNC:
        src = node.inputs[0]
        # trunc(zext(x)) => x  when result width matches original
        if src.type == NodeType.ZEXT and node.dt == src.inputs[0].dt:
            return src.inputs[0]
        # trunc(sext(x)) => x  when result width matches original
        if src.type == NodeType.SEXT and node.dt == src.inputs[0].dt:
            return src.inputs[0]

    return None


# ================================================================
# GVN: Global Value Numbering
# ================================================================

def gvn_hash(node):
    """Compute a hash for GVN deduplication."""
    h = hash(node.type)
    for inp in node.inputs:
        h = h * 31 + id(inp)
    if node.type == NodeType.ICONST:
        h = h * 31 + node.value
    if node.type == NodeType.PARAM:
        h = h * 31 + node.param_idx
    return h


def gvn_equal(a, b):
    """Check if two nodes are structurally identical for GVN purposes."""
    if a.type != b.type:
        return False
    if len(a.inputs) != len(b.inputs):
        return False
    for ai, bi in zip(a.inputs, b.inputs):
        if ai is not bi:
            return False
    if a.type == NodeType.ICONST:
        return a.value == b.value
    if a.type == NodeType.PARAM:
        return a.param_idx == b.param_idx
    return True


# ================================================================
# Optimizer: Main optimization engine
# ================================================================

class Optimizer:
    """
    Peephole optimizer for Sea of Nodes IR.

    Walks the DAG in topological order and applies value_of, idealize,
    and identity rewrites to each node until local fixpoint, then
    applies GVN for common subexpression elimination.
    """

    def __init__(self):
        self.gvn_table = {}

    def _gvn_lookup(self, node):
        """Find an existing structurally identical node."""
        if node.type == NodeType.PARAM:
            return None
        h = gvn_hash(node)
        for existing in self.gvn_table.get(h, []):
            if gvn_equal(node, existing):
                return existing
        return None

    def _gvn_insert(self, node):
        """Insert a node into the GVN table."""
        if node.type == NodeType.PARAM:
            return
        h = gvn_hash(node)
        if h not in self.gvn_table:
            self.gvn_table[h] = []
        for existing in self.gvn_table[h]:
            if gvn_equal(node, existing):
                return
        self.gvn_table[h].append(node)

    def _optimize_node(self, node):
        """Apply all peephole rules to a single node until fixpoint."""
        iterations = 0
        max_iter = 20

        while iterations < max_iter:
            iterations += 1
            changed = False

            # 1. Constant folding
            result = value_of(node)
            if result is not None:
                node = result
                changed = True
                if node.type == NodeType.ICONST:
                    break
                continue

            # 2. Algebraic simplification
            result = idealize(node)
            if result is not None:
                node = result
                changed = True
                continue

            # 3. Identity (replace with input)
            result = identity(node)
            if result is not None:
                node = result
                changed = True
                continue

            if not changed:
                break

        # 4. GVN deduplication
        existing = self._gvn_lookup(node)
        if existing is not None:
            return existing
        self._gvn_insert(node)
        return node

    def optimize(self, root):
        """
        Optimize a DAG rooted at the given node.
        Returns the new (optimized) root node.
        """
        visited = {}

        def process(node):
            if node.id in visited:
                return visited[node.id]

            # Process inputs first (ensures topological ordering)
            new_inputs = [process(inp) for inp in node.inputs]

            # Reconstruct with optimized inputs
            if node.type == NodeType.ICONST:
                new_node = Node(NodeType.ICONST, node.dt, [],
                                value=node.value)
            elif node.type == NodeType.PARAM:
                new_node = Node(NodeType.PARAM, node.dt, [],
                                param_idx=node.param_idx)
            else:
                new_node = Node(node.type, node.dt, new_inputs)

            result = self._optimize_node(new_node)
            visited[node.id] = result
            return result

        return process(root)
