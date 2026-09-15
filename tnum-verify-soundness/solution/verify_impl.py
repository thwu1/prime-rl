"""
Formal verification of tnum operations using Z3 SMT solver.
Verifies soundness on 8-bit integers: for all valid abstract inputs and
all concrete values in their concretizations, the concrete result of the
operation is within the concretization of the abstract result.
"""

import json
import sys
from z3 import (
    BitVec, BitVecVal, Solver, And, Not, If, Extract, LShR, ULE,
    sat, unsat,
)

BITS = 8


def make_vars(prefix):
    """Create Z3 bitvector variables for a tnum (value, mask)."""
    return BitVec(f'{prefix}_v', BITS), BitVec(f'{prefix}_m', BITS)


def invariant(val, mask):
    return val & mask == BitVecVal(0, BITS)


def in_gamma(x, val, mask):
    return x & ~mask == val


# ---- Z3 encodings of each tnum operation ----

def z3_tnum_and(av, am, bv, bm):
    alpha = av | am
    beta = bv | bm
    v = av & bv
    return v, alpha & beta & ~v


def z3_tnum_or(av, am, bv, bm):
    v = av | bv
    return v, (am | bm) & ~v


def z3_tnum_xor(av, am, bv, bm):
    v = av ^ bv
    mu = am | bm
    return v & ~mu, mu


def z3_tnum_add(av, am, bv, bm):
    sm = am + bm
    sv = av + bv
    sigma = sm + sv
    chi = sigma ^ sv
    mu = chi | am | bm
    return sv & ~mu, mu


def z3_tnum_sub(av, am, bv, bm):
    dv = av - bv
    alpha = dv + am
    beta = dv - bm
    chi = alpha ^ beta
    mu = chi | am | bm
    return dv & ~mu, mu


def z3_tnum_lshift(av, am, shift):
    return av << shift, am << shift


def z3_tnum_rshift(av, am, shift):
    return LShR(av, shift), LShR(am, shift)


def z3_tnum_mul(av, am, bv, bm):
    """Unrolled schoolbook multiplication for BITS iterations."""
    acc_v = BitVecVal(0, BITS)
    acc_m = BitVecVal(0, BITS)
    ca_v, ca_m = av, am
    cb_v, cb_m = bv, bm

    for _ in range(BITS):
        lsb_v = Extract(0, 0, ca_v)
        lsb_m = Extract(0, 0, ca_m)

        is_one = And(lsb_v == BitVecVal(1, 1), lsb_m == BitVecVal(0, 1))
        is_unk = lsb_m == BitVecVal(1, 1)

        add_v = If(is_one, cb_v, BitVecVal(0, BITS))
        add_m = If(is_one, cb_m,
                   If(is_unk, cb_m | cb_v, BitVecVal(0, BITS)))

        # tnum_add into accumulator
        sm = acc_m + add_m
        sv = acc_v + add_v
        sigma = sm + sv
        chi = sigma ^ sv
        mu = chi | acc_m | add_m
        acc_v = sv & ~mu
        acc_m = mu

        ca_v = LShR(ca_v, 1)
        ca_m = LShR(ca_m, 1)
        cb_v = cb_v << 1
        cb_m = cb_m << 1

    return acc_v, acc_m


# ---- Verification harness ----

def verify_binary(name, z3_op, concrete_op):
    """Verify a binary tnum operation: for all valid (a,b) and concrete
    x in gamma(a), y in gamma(b), concrete_op(x,y) in gamma(result)."""
    s = Solver()
    av, am = make_vars('a')
    bv, bm = make_vars('b')
    x = BitVec('x', BITS)
    y = BitVec('y', BITS)

    s.add(invariant(av, am))
    s.add(invariant(bv, bm))
    s.add(in_gamma(x, av, am))
    s.add(in_gamma(y, bv, bm))

    rv, rm = z3_op(av, am, bv, bm)
    z = concrete_op(x, y)
    s.add(Not(in_gamma(z, rv, rm)))

    return {"verified": s.check() == unsat, "bit_width": BITS}


def verify_shift(name, z3_op, concrete_op):
    """Verify a shift operation for every valid shift amount."""
    for sh in range(BITS):
        s = Solver()
        av, am = make_vars('a')
        x = BitVec('x', BITS)

        s.add(invariant(av, am))
        s.add(in_gamma(x, av, am))

        rv, rm = z3_op(av, am, sh)
        z = concrete_op(x, sh)
        s.add(Not(in_gamma(z, rv, rm)))

        if s.check() != unsat:
            return {"verified": False, "bit_width": BITS, "failed_shift": sh}
    return {"verified": True, "bit_width": BITS}


def verify_intersect():
    """Verify intersect: for compatible tnums, gamma(a) & gamma(b) subset of gamma(result)."""
    s = Solver()
    av, am = make_vars('a')
    bv, bm = make_vars('b')
    x = BitVec('x', BITS)

    s.add(invariant(av, am))
    s.add(invariant(bv, bm))

    # Require no conflict
    conflict = (av ^ bv) & ~am & ~bm
    s.add(conflict == BitVecVal(0, BITS))

    s.add(in_gamma(x, av, am))
    s.add(in_gamma(x, bv, bm))

    # intersect result
    rv = (av | bv) & ~(am & bm)
    rm = am & bm
    s.add(Not(in_gamma(x, rv, rm)))

    return {"verified": s.check() == unsat, "bit_width": BITS}


def verify_range():
    """Verify tnum_range: for min <= x <= max, x in gamma(result)."""
    s = Solver()
    mn = BitVec('mn', BITS)
    mx = BitVec('mx', BITS)
    x = BitVec('x', BITS)

    s.add(ULE(mn, mx))
    s.add(ULE(mn, x))
    s.add(ULE(x, mx))

    chi = mn ^ mx
    mask = chi
    mask = mask | LShR(mask, 1)
    mask = mask | LShR(mask, 2)
    mask = mask | LShR(mask, 4)

    rv = mn & ~mask
    rm = mask
    s.add(Not(in_gamma(x, rv, rm)))

    return {"verified": s.check() == unsat, "bit_width": BITS}


def main():
    results = {}

    ops = [
        ("tnum_and",   lambda: verify_binary("and",   z3_tnum_and, lambda x, y: x & y)),
        ("tnum_or",    lambda: verify_binary("or",    z3_tnum_or,  lambda x, y: x | y)),
        ("tnum_xor",   lambda: verify_binary("xor",   z3_tnum_xor, lambda x, y: x ^ y)),
        ("tnum_add",   lambda: verify_binary("add",   z3_tnum_add, lambda x, y: x + y)),
        ("tnum_sub",   lambda: verify_binary("sub",   z3_tnum_sub, lambda x, y: x - y)),
        ("tnum_lshift", lambda: verify_shift("lsh",   z3_tnum_lshift, lambda x, s: x << s)),
        ("tnum_rshift", lambda: verify_shift("rsh",   z3_tnum_rshift, lambda x, s: LShR(x, s))),
        ("tnum_intersect", verify_intersect),
        ("tnum_mul",   lambda: verify_binary("mul",   z3_tnum_mul, lambda x, y: x * y)),
        ("tnum_range", verify_range),
    ]

    all_ok = True
    for name, fn in ops:
        print(f"Verifying {name}...", end=" ", flush=True)
        r = fn()
        results[name] = r
        status = "OK" if r["verified"] else "FAIL"
        print(status)
        if not r["verified"]:
            all_ok = False

    with open("/app/verification_report.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nAll verified: {all_ok}")
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
