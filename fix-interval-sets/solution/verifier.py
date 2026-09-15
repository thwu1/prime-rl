"""Z3-based bounded model checker for interval set operations.

Encodes interval set semantics using Z3 bitvector formulas and provides
functions to verify algebraic laws and check operation implementations.

Bitvector encoding:
    union(A, B)           = A | B   (bitwise OR)
    intersection(A, B)    = A & B   (bitwise AND)
    difference(A, B)      = A & ~B  (bitwise AND-NOT)
    complement(A)         = ~A      (bitwise NOT)
    symmetric_difference  = A ^ B   (bitwise XOR)
"""


import z3
import json
import sys

sys.path.insert(0, '/app')
import intervals as iv


def iset_from_bitmask(mask, bound):
    """Convert an integer bitmask to an interval set within [0, bound).

    Bit i of mask is set iff integer i is in the set.
    """
    points = [i for i in range(bound) if mask & (1 << i)]
    return iv.from_points(points)


def bitmask_from_iset(iset, bound):
    """Convert an interval set to an integer bitmask for [0, bound).

    Returns an integer whose bit i is set iff i is in the interval set.
    """
    mask = 0
    for lo, hi in iset:
        for i in range(max(0, lo), min(bound, hi)):
            mask |= (1 << i)
    return mask


def check_law(law_name, bound=8):
    """Verify an algebraic law using Z3 bitvector reasoning.

    Encodes interval set operations as bitvector operations and checks
    whether the negation of the law is satisfiable. If UNSAT, the law
    holds for all sets of integers in [0, bound).

    Args:
        law_name: Name from laws.json
        bound: Bitvector width (universe is [0, bound))

    Returns:
        {"verified": bool, "bound": int}
    """
    A = z3.BitVec('A', bound)
    B = z3.BitVec('B', bound)
    C = z3.BitVec('C', bound)
    zero = z3.BitVecVal(0, bound)

    # Each formula is the NEGATION of the law.
    # If Z3 returns UNSAT, no counterexample exists and the law holds.
    negated_laws = {
        "union_commutative":
            (A | B) != (B | A),
        "intersection_commutative":
            (A & B) != (B & A),
        "union_associative":
            ((A | B) | C) != (A | (B | C)),
        "intersection_associative":
            ((A & B) & C) != (A & (B & C)),
        "distributivity":
            (A | (B & C)) != ((A | B) & (A | C)),
        "absorption_union":
            (A | (A & B)) != A,
        "absorption_intersection":
            (A & (A | B)) != A,
        "difference_decomposition":
            ((A & ~B) | (B & ~A)) != (A ^ B),
        "demorgan_union":
            ~(A | B) != (~A & ~B),
        "demorgan_intersection":
            ~(A & B) != (~A | ~B),
        "complement_involution":
            ~(~A) != A,
        "intersection_complement_empty":
            (A & ~A) != zero,
    }

    if law_name not in negated_laws:
        return {"verified": False, "bound": bound,
                "error": f"Unknown law: {law_name}"}

    solver = z3.Solver()
    solver.add(negated_laws[law_name])
    result = solver.check()

    if result == z3.unsat:
        return {"verified": True, "bound": bound}
    else:
        model = solver.model()
        cx = {}
        for d in model.decls():
            cx[d.name()] = model[d].as_long()
        return {"verified": False, "bound": bound, "counterexample": cx}


def check_operation(op_func, ref_func, num_sets, bound):
    """Check a Python interval operation against a reference implementation.

    Exhaustively tests all possible interval sets within [0, bound) by
    iterating over all 2^bound bitmask representations.

    Args:
        op_func: The operation to test
        ref_func: The reference implementation (assumed correct)
        num_sets: Number of input interval sets (1 or 2)
        bound: Universe size [0, bound)

    Returns:
        (is_correct: bool, counterexample_or_none: dict|None)
    """
    total = 1 << bound

    if num_sets == 1:
        for mask_a in range(total):
            a = iset_from_bitmask(mask_a, bound)
            try:
                result = op_func(a)
                expected = ref_func(a)
            except Exception as e:
                return (False, {"inputs": [a], "error": str(e)})
            if result != expected:
                return (False, {
                    "inputs": [a],
                    "got": result,
                    "expected": expected
                })
    elif num_sets == 2:
        for mask_a in range(total):
            a = iset_from_bitmask(mask_a, bound)
            for mask_b in range(total):
                b = iset_from_bitmask(mask_b, bound)
                try:
                    result = op_func(a, b)
                    expected = ref_func(a, b)
                except Exception as e:
                    return (False, {"inputs": [a, b], "error": str(e)})
                if result != expected:
                    return (False, {
                        "inputs": [a, b],
                        "got": result,
                        "expected": expected
                    })

    return (True, None)
