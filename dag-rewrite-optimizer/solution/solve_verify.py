#!/usr/bin/env python3
"""
Verify candidate rewrite rules using the Z3 SMT solver.
Produces /app/verification_report.json with sound/unsound verdicts
and counterexamples for unsound rules.

"""
import json
from z3 import BitVec, BitVecVal, ULT, Solver, sat, LShR, Not


BV = 32


def verify_c1():
    """C1: OR(AND(x, c), AND(x, ~c)) == x for all x, c."""
    s = Solver()
    x = BitVec('x', BV)
    c = BitVec('c', BV)
    lhs = (x & c) | (x & ~c)
    s.add(lhs != x)
    if s.check() == sat:
        m = s.model()
        return {"verdict": "unsound",
                "counterexample": {"x": m[x].as_long(), "c": m[c].as_long()}}
    return {"verdict": "sound"}


def verify_c2():
    """C2: LShR(x << c, c) == x for c in [1, 31]."""
    s = Solver()
    x = BitVec('x', BV)
    c = BitVec('c', BV)
    s.add(c >= 1, c <= 31)
    lhs = LShR(x << c, c)
    s.add(lhs != x)
    if s.check() == sat:
        m = s.model()
        return {"verdict": "unsound",
                "counterexample": {"x": m[x].as_long(), "c": m[c].as_long()}}
    return {"verdict": "sound"}


def verify_c3():
    """C3: ULT(x, x + 1) is always true."""
    s = Solver()
    x = BitVec('x', BV)
    s.add(Not(ULT(x, x + BitVecVal(1, BV))))
    if s.check() == sat:
        m = s.model()
        return {"verdict": "unsound",
                "counterexample": {"x": m[x].as_long()}}
    return {"verdict": "sound"}


def verify_c4():
    """C4: x - (x - y) == y for all x, y."""
    s = Solver()
    x = BitVec('x', BV)
    y = BitVec('y', BV)
    lhs = x - (x - y)
    s.add(lhs != y)
    if s.check() == sat:
        m = s.model()
        return {"verdict": "unsound",
                "counterexample": {"x": m[x].as_long(), "y": m[y].as_long()}}
    return {"verdict": "sound"}


def verify_c5():
    """C5: x + (-x) == 0 for all x."""
    s = Solver()
    x = BitVec('x', BV)
    lhs = x + (-x)
    s.add(lhs != BitVecVal(0, BV))
    if s.check() == sat:
        m = s.model()
        return {"verdict": "unsound",
                "counterexample": {"x": m[x].as_long()}}
    return {"verdict": "sound"}


def verify_c6():
    """C6: ULT(x - y, x) is always true."""
    s = Solver()
    x = BitVec('x', BV)
    y = BitVec('y', BV)
    s.add(Not(ULT(x - y, x)))
    if s.check() == sat:
        m = s.model()
        return {"verdict": "unsound",
                "counterexample": {"x": m[x].as_long(), "y": m[y].as_long()}}
    return {"verdict": "sound"}


def main():
    report = {
        "C1": verify_c1(),
        "C2": verify_c2(),
        "C3": verify_c3(),
        "C4": verify_c4(),
        "C5": verify_c5(),
        "C6": verify_c6(),
    }

    with open("/app/verification_report.json", "w") as f:
        json.dump(report, f, indent=2)

    for rid, result in sorted(report.items()):
        print(f"  {rid}: {result['verdict']}")


if __name__ == "__main__":
    main()
