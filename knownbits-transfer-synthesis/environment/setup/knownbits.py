"""
KnownBits Abstract Domain Framework

This module implements the KnownBits abstract domain used in compiler dataflow
analysis (as seen in LLVM's ValueTracking). Each abstract value tracks which
bits of an integer are known to be zero, known to be one, or unknown across
all possible runtime executions.

Representation:
  - zero_mask: bitmask where bit i is set if bit i is KNOWN to be 0
  - one_mask:  bitmask where bit i is set if bit i is KNOWN to be 1
  - Invariant: (zero_mask & one_mask) == 0  (a bit cannot be both)
  - Unknown bits have neither flag set

The agent must implement transfer functions in /app/transfers.py for the
following operations. Each transfer function takes KnownBits inputs and
returns a KnownBits result that must be:
  1. SOUND: the result must contain every concrete value that could arise
     from applying the operation to any concrete values consistent with the
     inputs.
  2. PRECISE: the result should contain as few extra values as possible.
"""

import itertools


class KnownBits:
    """Represents known-bits information for an N-bit integer."""

    def __init__(self, width, zero_mask, one_mask):
        self.width = width
        full = (1 << width) - 1
        self.zero_mask = zero_mask & full
        self.one_mask = one_mask & full
        if self.zero_mask & self.one_mask:
            raise ValueError("Conflict: a bit cannot be both known-zero and known-one")

    @property
    def unknown_mask(self):
        """Bits that are neither known-zero nor known-one."""
        full = (1 << self.width) - 1
        return full & ~(self.zero_mask | self.one_mask)

    @property
    def num_unknown(self):
        return bin(self.unknown_mask).count('1')

    def contains(self, concrete_val):
        """Check if a concrete value is consistent with this abstract value."""
        full = (1 << self.width) - 1
        v = concrete_val & full
        # All known-zero bits must be 0 in concrete value
        if v & self.zero_mask:
            return False
        # All known-one bits must be 1 in concrete value
        if (~v & full) & self.one_mask:
            return False
        return True

    def concrete_set(self):
        """Enumerate all concrete values consistent with this KnownBits."""
        unknown_positions = []
        for i in range(self.width):
            if (self.unknown_mask >> i) & 1:
                unknown_positions.append(i)
        base = self.one_mask
        result = set()
        for bits in itertools.product([0, 1], repeat=len(unknown_positions)):
            val = base
            for pos, b in zip(unknown_positions, bits):
                if b:
                    val |= (1 << pos)
            result.add(val)
        return result

    def __repr__(self):
        bits = []
        for i in range(self.width - 1, -1, -1):
            if (self.one_mask >> i) & 1:
                bits.append('1')
            elif (self.zero_mask >> i) & 1:
                bits.append('0')
            else:
                bits.append('?')
        return f"KB({''.join(bits)})"

    def __eq__(self, other):
        return (self.width == other.width and
                self.zero_mask == other.zero_mask and
                self.one_mask == other.one_mask)

    def __hash__(self):
        return hash((self.width, self.zero_mask, self.one_mask))


def top(width):
    """Return the top element: all bits unknown."""
    return KnownBits(width, 0, 0)


def bottom(width):
    """Return bottom (conflict — should not arise in sound analysis)."""
    full = (1 << width) - 1
    return KnownBits(width, full, 0)


def constant(width, value):
    """Return a KnownBits representing an exact constant."""
    full = (1 << width) - 1
    v = value & full
    return KnownBits(width, (~v) & full, v)


def meet(a, b):
    """Meet (intersection): combine information from two KnownBits.
    Result is more precise. Conflict if incompatible."""
    assert a.width == b.width
    new_zero = a.zero_mask | b.zero_mask
    new_one = a.one_mask | b.one_mask
    if new_zero & new_one:
        # Conflict — return bottom-like (known all zero, which is wrong
        # but signals unsatisfiability)
        return KnownBits(a.width, new_zero, new_one & ~new_zero)
    return KnownBits(a.width, new_zero, new_one)


def get_min_unsigned(kb):
    """Minimum possible unsigned value."""
    return kb.one_mask


def get_max_unsigned(kb):
    """Maximum possible unsigned value."""
    return kb.one_mask | kb.unknown_mask


def get_min_signed(kb):
    """Minimum possible signed value (two's complement)."""
    sign_bit = 1 << (kb.width - 1)
    if (kb.one_mask & sign_bit):
        # Sign bit is known-one: negative, minimize magnitude means all unknown low bits = 0
        return _to_signed(kb.one_mask, kb.width)
    elif (kb.zero_mask & sign_bit):
        # Sign bit is known-zero: non-negative, min is just the known ones
        return _to_signed(kb.one_mask, kb.width)
    else:
        # Sign bit unknown: worst case is negative with all unknown low bits = 0
        return _to_signed(kb.one_mask | sign_bit, kb.width)


def get_max_signed(kb):
    """Maximum possible signed value (two's complement)."""
    sign_bit = 1 << (kb.width - 1)
    if (kb.one_mask & sign_bit):
        # Sign bit known-one: negative, max is ones + all unknown = 1
        return _to_signed(kb.one_mask | kb.unknown_mask, kb.width)
    elif (kb.zero_mask & sign_bit):
        # Sign bit known-zero: non-negative, max is ones + unknowns = 1
        return _to_signed(kb.one_mask | kb.unknown_mask, kb.width)
    else:
        # Sign bit unknown: best case positive, all unknown low bits = 1, sign = 0
        return _to_signed((kb.one_mask | kb.unknown_mask) & ~sign_bit, kb.width)


def _to_signed(val, width):
    full = (1 << width) - 1
    val = val & full
    sign_bit = 1 << (width - 1)
    if val & sign_bit:
        return val - (1 << width)
    return val


def _to_unsigned(val, width):
    return val & ((1 << width) - 1)


# ============================================================
# Concrete operation semantics (ground truth)
# ============================================================

def concrete_add(a, b, width):
    return (a + b) & ((1 << width) - 1)

def concrete_sub(a, b, width):
    return (a - b) & ((1 << width) - 1)

def concrete_mul(a, b, width):
    return (a * b) & ((1 << width) - 1)

def concrete_udiv(a, b, width):
    if b == 0:
        return None  # undefined
    return (a // b) & ((1 << width) - 1)

def concrete_urem(a, b, width):
    if b == 0:
        return None
    return (a % b) & ((1 << width) - 1)

def concrete_shl(a, b, width):
    full = (1 << width) - 1
    if b >= width:
        return 0
    return (a << b) & full

def concrete_lshr(a, b, width):
    if b >= width:
        return 0
    return a >> b

def concrete_ashr(a, b, width):
    if b >= width:
        sign = (a >> (width - 1)) & 1
        return ((1 << width) - 1) if sign else 0
    sa = _to_signed(a, width)
    result = sa >> b
    return _to_unsigned(result, width)

def concrete_and(a, b, width):
    return a & b

def concrete_or(a, b, width):
    return a | b

def concrete_xor(a, b, width):
    return a ^ b

def concrete_neg(a, width):
    return (-a) & ((1 << width) - 1)

def concrete_not(a, width):
    return (~a) & ((1 << width) - 1)


# Mapping from operation names to concrete semantics
BINARY_OPS = {
    'add': concrete_add,
    'sub': concrete_sub,
    'mul': concrete_mul,
    'udiv': concrete_udiv,
    'urem': concrete_urem,
    'shl': concrete_shl,
    'lshr': concrete_lshr,
    'ashr': concrete_ashr,
    'and': concrete_and,
    'or': concrete_or,
    'xor': concrete_xor,
}

UNARY_OPS = {
    'neg': concrete_neg,
    'not': concrete_not,
}


# ============================================================
# Verification infrastructure
# ============================================================

def verify_transfer_soundness(op_name, transfer_fn, width, is_unary=False):
    """Exhaustively verify that a transfer function is sound at a given bit width.

    For every possible pair of KnownBits inputs, checks that every concrete
    result of the operation on concrete values consistent with the inputs
    is contained in the KnownBits returned by the transfer function.

    Returns (is_sound, counterexample_or_None)
    """
    full = (1 << width) - 1

    if is_unary:
        concrete_fn = UNARY_OPS[op_name]
        for z1 in range(full + 1):
            for o1 in range(full + 1):
                if z1 & o1:
                    continue
                kb1 = KnownBits(width, z1, o1)
                result_kb = transfer_fn(kb1)
                for v1 in kb1.concrete_set():
                    cv = concrete_fn(v1, width)
                    if cv is not None and not result_kb.contains(cv):
                        return False, {
                            'input': kb1,
                            'concrete_input': v1,
                            'concrete_result': cv,
                            'abstract_result': result_kb,
                        }
        return True, None

    concrete_fn = BINARY_OPS[op_name]
    for z1 in range(full + 1):
        for o1 in range(full + 1):
            if z1 & o1:
                continue
            kb1 = KnownBits(width, z1, o1)
            for z2 in range(full + 1):
                for o2 in range(full + 1):
                    if z2 & o2:
                        continue
                    kb2 = KnownBits(width, z2, o2)
                    result_kb = transfer_fn(kb1, kb2)
                    for v1 in kb1.concrete_set():
                        for v2 in kb2.concrete_set():
                            cv = concrete_fn(v1, v2, width)
                            if cv is not None and not result_kb.contains(cv):
                                return False, {
                                    'lhs': kb1,
                                    'rhs': kb2,
                                    'concrete_lhs': v1,
                                    'concrete_rhs': v2,
                                    'concrete_result': cv,
                                    'abstract_result': result_kb,
                                }
    return True, None


def measure_precision(op_name, transfer_fn, width, is_unary=False, sample_limit=None):
    """Measure precision of a transfer function vs the optimal (most precise) result.

    Returns a precision score between 0 and 1, where 1.0 means the transfer
    function always returns the tightest possible KnownBits.

    Precision is measured as: (bits_known_by_transfer / bits_known_by_optimal)
    averaged over all valid input KnownBits combinations.
    """
    full = (1 << width) - 1
    total_optimal_known = 0
    total_transfer_known = 0
    count = 0

    if is_unary:
        concrete_fn = UNARY_OPS[op_name]
        for z1 in range(full + 1):
            for o1 in range(full + 1):
                if z1 & o1:
                    continue
                kb1 = KnownBits(width, z1, o1)
                # Compute optimal result
                result_values = set()
                for v1 in kb1.concrete_set():
                    cv = concrete_fn(v1, width)
                    if cv is not None:
                        result_values.add(cv)
                if not result_values:
                    continue
                optimal = _optimal_knownbits(width, result_values)
                transfer_result = transfer_fn(kb1)

                opt_known = bin(optimal.zero_mask | optimal.one_mask).count('1')
                tf_known = bin(transfer_result.zero_mask | transfer_result.one_mask).count('1')
                total_optimal_known += opt_known
                total_transfer_known += tf_known
                count += 1
        if total_optimal_known == 0:
            return 1.0
        return total_transfer_known / total_optimal_known

    concrete_fn = BINARY_OPS[op_name]
    inputs = []
    for z1 in range(full + 1):
        for o1 in range(full + 1):
            if z1 & o1:
                continue
            inputs.append((z1, o1))

    checked = 0
    for z1, o1 in inputs:
        kb1 = KnownBits(width, z1, o1)
        for z2, o2 in inputs:
            kb2 = KnownBits(width, z2, o2)
            if sample_limit and checked >= sample_limit:
                break
            # Compute optimal result
            result_values = set()
            for v1 in kb1.concrete_set():
                for v2 in kb2.concrete_set():
                    cv = concrete_fn(v1, v2, width)
                    if cv is not None:
                        result_values.add(cv)
            if not result_values:
                checked += 1
                continue
            optimal = _optimal_knownbits(width, result_values)
            transfer_result = transfer_fn(kb1, kb2)

            opt_known = bin(optimal.zero_mask | optimal.one_mask).count('1')
            tf_known = bin(transfer_result.zero_mask | transfer_result.one_mask).count('1')
            total_optimal_known += opt_known
            total_transfer_known += tf_known
            count += 1
            checked += 1
        if sample_limit and checked >= sample_limit:
            break

    if total_optimal_known == 0:
        return 1.0
    return total_transfer_known / total_optimal_known


def _optimal_knownbits(width, concrete_values):
    """Compute the most precise KnownBits that contains all given concrete values."""
    full = (1 << width) - 1
    if not concrete_values:
        return top(width)
    # known-one: bits that are 1 in ALL values
    all_one = full
    # known-zero: bits that are 0 in ALL values
    all_zero = full
    for v in concrete_values:
        all_one &= v
        all_zero &= (~v) & full
    return KnownBits(width, all_zero, all_one)
