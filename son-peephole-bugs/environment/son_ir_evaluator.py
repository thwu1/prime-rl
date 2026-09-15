"""
Sea of Nodes IR - Expression evaluator.

Provides a reference interpreter for IR expression DAGs.  Given concrete
values for parameter nodes, evaluates the expression tree and returns
the result as an unsigned integer masked to the output data type's width.
"""

from .nodes import NodeType


def _sign_extend(value, bits):
    """Sign-extend a value from 'bits' width to Python int."""
    mask = (1 << bits) - 1
    value = value & mask
    if value & (1 << (bits - 1)):
        return value - (1 << bits)
    return value


def evaluate(node, params):
    """
    Evaluate an IR expression DAG with concrete parameter values.

    Args:
        node: The root node of the expression to evaluate.
        params: dict mapping param_idx -> integer value.

    Returns:
        The result as an unsigned integer masked to the node's bit width.
    """
    cache = {}

    def ev(n):
        if n.id in cache:
            return cache[n.id]
        result = _eval_impl(n)
        cache[n.id] = result
        return result

    def _eval_impl(n):
        mask = n.dt.mask()
        bits = n.dt.bits

        if n.type == NodeType.ICONST:
            return n.value & mask

        elif n.type == NodeType.PARAM:
            return params[n.param_idx] & mask

        # Arithmetic
        elif n.type == NodeType.ADD:
            return (ev(n.inputs[0]) + ev(n.inputs[1])) & mask

        elif n.type == NodeType.SUB:
            return (ev(n.inputs[0]) - ev(n.inputs[1])) & mask

        elif n.type == NodeType.MUL:
            return (ev(n.inputs[0]) * ev(n.inputs[1])) & mask

        elif n.type == NodeType.UDIV:
            b = ev(n.inputs[1])
            if b == 0:
                return 0
            return ev(n.inputs[0]) // b

        elif n.type == NodeType.SDIV:
            a = _sign_extend(ev(n.inputs[0]), bits)
            b = _sign_extend(ev(n.inputs[1]), bits)
            if b == 0:
                return 0
            result = int(a / b)  # truncate toward zero
            return result & mask

        elif n.type == NodeType.NEG:
            return (-ev(n.inputs[0])) & mask

        # Bitwise
        elif n.type == NodeType.AND:
            return ev(n.inputs[0]) & ev(n.inputs[1])

        elif n.type == NodeType.OR:
            return ev(n.inputs[0]) | ev(n.inputs[1])

        elif n.type == NodeType.XOR:
            return ev(n.inputs[0]) ^ ev(n.inputs[1])

        elif n.type == NodeType.NOT:
            return ev(n.inputs[0]) ^ mask

        # Shifts
        elif n.type == NodeType.SHL:
            a = ev(n.inputs[0])
            b = ev(n.inputs[1])
            if b >= bits:
                return 0
            return (a << b) & mask

        elif n.type == NodeType.SHR:
            a = ev(n.inputs[0])
            b = ev(n.inputs[1])
            if b >= bits:
                return 0
            return a >> b

        elif n.type == NodeType.SAR:
            a = _sign_extend(ev(n.inputs[0]), bits)
            b = ev(n.inputs[1])
            if b >= bits:
                return mask if a < 0 else 0
            return (a >> b) & mask

        # Comparisons
        elif n.type == NodeType.CMP_EQ:
            return 1 if ev(n.inputs[0]) == ev(n.inputs[1]) else 0

        elif n.type == NodeType.CMP_NE:
            return 1 if ev(n.inputs[0]) != ev(n.inputs[1]) else 0

        elif n.type == NodeType.CMP_SLT:
            cmp_bits = n.inputs[0].dt.bits
            a = _sign_extend(ev(n.inputs[0]), cmp_bits)
            b = _sign_extend(ev(n.inputs[1]), cmp_bits)
            return 1 if a < b else 0

        elif n.type == NodeType.CMP_SLE:
            cmp_bits = n.inputs[0].dt.bits
            a = _sign_extend(ev(n.inputs[0]), cmp_bits)
            b = _sign_extend(ev(n.inputs[1]), cmp_bits)
            return 1 if a <= b else 0

        elif n.type == NodeType.CMP_ULT:
            return 1 if ev(n.inputs[0]) < ev(n.inputs[1]) else 0

        elif n.type == NodeType.CMP_ULE:
            return 1 if ev(n.inputs[0]) <= ev(n.inputs[1]) else 0

        # Select
        elif n.type == NodeType.SELECT:
            cond = ev(n.inputs[0])
            return ev(n.inputs[1]) if cond else ev(n.inputs[2])

        # Width conversions
        elif n.type == NodeType.ZEXT:
            return ev(n.inputs[0])  # already unsigned, just wider mask

        elif n.type == NodeType.SEXT:
            src_bits = n.inputs[0].dt.bits
            val = _sign_extend(ev(n.inputs[0]), src_bits)
            return val & mask

        elif n.type == NodeType.TRUNC:
            return ev(n.inputs[0]) & mask

        else:
            raise ValueError(f"Unknown node type: {n.type}")

    return ev(node)
