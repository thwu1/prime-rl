"""
Exhaustive verification and precision measurement for KnownBits
transfer functions.

Designed for small bit widths (4-bit) where enumeration is feasible.
"""

from knownbits import KnownBits


def all_knownbits(width):
    """Yield every valid (non-conflicting) KnownBits for *width* bits.

    Each bit position can be known-0, known-1, or unknown, giving 3^width
    elements (81 for width=4).
    """
    upper = 1 << width
    for zero in range(upper):
        for one in range(upper):
            if zero & one == 0:
                yield KnownBits(width, zero, one)


def compute_optimal_binary(concrete_op, width, a, b):
    """Most-precise sound result by exhaustive evaluation."""
    mask = (1 << width) - 1
    result = None
    for x in a.iterate_concrete_values():
        for y in b.iterate_concrete_values():
            val = concrete_op(x, y) & mask
            kb = KnownBits.from_constant(width, val)
            result = kb if result is None else result.join(kb)
    return result if result is not None else KnownBits.bottom(width)


def verify_soundness_binary(transfer_fn, concrete_op, width):
    """Check that *transfer_fn* is sound for every abstract input pair.

    Returns ``(True, None)`` on success.
    Returns ``(False, (a, b, x, y, concrete, abstract))`` on failure.
    """
    mask = (1 << width) - 1
    for a in all_knownbits(width):
        for b in all_knownbits(width):
            abstract = transfer_fn(a, b)
            for x in a.iterate_concrete_values():
                for y in b.iterate_concrete_values():
                    concrete = concrete_op(x, y) & mask
                    if not abstract.contains(concrete):
                        return False, (a, b, x, y, concrete, abstract)
    return True, None


def measure_precision_binary(transfer_fn, concrete_op, width):
    """Precision = (total known bits from impl) / (total from optimal).

    Pairs where the optimal has zero known bits are excluded.
    Returns a float in [0, 1].
    """
    impl_total = 0
    opt_total = 0
    for a in all_knownbits(width):
        for b in all_knownbits(width):
            optimal = compute_optimal_binary(concrete_op, width, a, b)
            if optimal.is_conflict():
                continue
            ok = optimal.num_known_bits()
            if ok == 0:
                continue
            result = transfer_fn(a, b)
            impl_total += result.num_known_bits()
            opt_total += ok
    if opt_total == 0:
        return 1.0
    return impl_total / opt_total
