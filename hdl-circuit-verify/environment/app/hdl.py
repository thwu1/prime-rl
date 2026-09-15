"""
miniHDL - A minimal Hardware Description Language DSL in Python.

Provides primitives for describing and simulating combinational
digital logic circuits using Python operator overloading.

Bit ordering convention: LSB first (index 0 = least significant bit).
"""



class Wire:
    """A single signal wire in a digital circuit."""
    _all = []

    def __init__(self, name=None):
        self.id = len(Wire._all)
        Wire._all.append(self)
        self.name = name or f"w{self.id}"
        self.driver = None
        self._const_val = None

    @staticmethod
    def reset():
        """Clear all wire state for a fresh circuit build."""
        Wire._all = []

    def __and__(self, other):
        w = Wire()
        w.driver = ('AND', [self, other])
        return w

    def __or__(self, other):
        w = Wire()
        w.driver = ('OR', [self, other])
        return w

    def __xor__(self, other):
        w = Wire()
        w.driver = ('XOR', [self, other])
        return w

    def __invert__(self):
        w = Wire()
        w.driver = ('NOT', [self])
        return w

    def __repr__(self):
        return f"Wire({self.name}, id={self.id})"


class Bus:
    """An ordered collection of Wire objects representing a multi-bit signal (LSB first)."""

    def __init__(self, wires):
        self.wires = list(wires) if not isinstance(wires, list) else wires

    @staticmethod
    def input(width, prefix="x"):
        """Create a bus of primary input wires."""
        return Bus([Wire(name=f"{prefix}[{i}]") for i in range(width)])

    def __len__(self):
        return len(self.wires)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            return Bus(self.wires[idx])
        return self.wires[idx]

    def __and__(self, other):
        if isinstance(other, Wire):
            return Bus([w & other for w in self.wires])
        return Bus([a & b for a, b in zip(self.wires, other.wires)])

    def __or__(self, other):
        if isinstance(other, Wire):
            return Bus([w | other for w in self.wires])
        return Bus([a | b for a, b in zip(self.wires, other.wires)])

    def __xor__(self, other):
        if isinstance(other, Wire):
            return Bus([w ^ other for w in self.wires])
        return Bus([a ^ b for a, b in zip(self.wires, other.wires)])

    def __invert__(self):
        return Bus([~w for w in self.wires])

    def __repr__(self):
        return f"Bus([{', '.join(w.name for w in self.wires)}])"


def mux(sel, if_one, if_zero):
    """
    2-to-1 multiplexor.
    Returns if_one when sel=1, if_zero when sel=0.
    Works on both Wire and Bus operands.
    """
    if isinstance(if_one, Bus):
        return Bus([mux(sel, a, b)
                     for a, b in zip(if_one.wires, if_zero.wires)])
    return (if_one & sel) | (if_zero & ~sel)


def const(val):
    """Create a wire with a fixed constant value (0 or 1)."""
    w = Wire(name=f"const_{val}")
    w._const_val = val
    w.driver = ('CONST', [])
    return w


def simulate(outputs, input_map):
    """
    Evaluate a combinational circuit by tracing from outputs back to inputs.

    Args:
        outputs: Bus or list of Wire objects to evaluate.
        input_map: dict mapping Wire objects to integer values (0 or 1).

    Returns:
        List of output values (0 or 1), one per output wire.
    """
    memo = {}

    def _eval(w):
        if w.id in memo:
            return memo[w.id]
        if w in input_map:
            memo[w.id] = input_map[w]
            return input_map[w]
        if w._const_val is not None:
            memo[w.id] = w._const_val
            return w._const_val
        if w.driver is None:
            raise RuntimeError(
                f"Wire '{w.name}' (id={w.id}) is floating: "
                "no driver, no input binding, and not a constant"
            )
        op, args = w.driver
        if op == 'CONST':
            v = w._const_val if w._const_val is not None else 0
        elif op == 'NOT':
            v = 1 - _eval(args[0])
        elif op == 'AND':
            v = _eval(args[0]) & _eval(args[1])
        elif op == 'OR':
            v = _eval(args[0]) | _eval(args[1])
        elif op == 'XOR':
            v = _eval(args[0]) ^ _eval(args[1])
        else:
            raise RuntimeError(f"Unknown gate type: {op}")
        memo[w.id] = v
        return v

    wires = outputs.wires if isinstance(outputs, Bus) else outputs
    return [_eval(w) for w in wires]


def bus_to_int(bit_values):
    """Convert LSB-first bit list to integer."""
    return sum(v << i for i, v in enumerate(bit_values))


def int_to_input_map(bus, value):
    """Create input_map entries for a bus from an integer value (LSB first)."""
    return {bus[i]: (value >> i) & 1 for i in range(len(bus))}
