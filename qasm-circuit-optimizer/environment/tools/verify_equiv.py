#!/usr/bin/env python3
"""Check if two OpenQASM 2.0 circuits implement the same unitary (up to global phase)."""
import sys
from qasm_utils import parse_qasm, circuit_unitary, unitaries_equivalent, count_cx


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: verify_equiv.py <circuit1.qasm> <circuit2.qasm>",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text1 = f.read()
    with open(sys.argv[2]) as f:
        text2 = f.read()

    n1, g1 = parse_qasm(text1)
    n2, g2 = parse_qasm(text2)

    if n1 != n2:
        print(f"FAIL: qubit count mismatch ({n1} vs {n2})")
        sys.exit(1)

    U1 = circuit_unitary(n1, g1)
    U2 = circuit_unitary(n2, g2)

    cx1 = count_cx(g1)
    cx2 = count_cx(g2)

    if unitaries_equivalent(U1, U2):
        print("PASS: circuits are unitarily equivalent (up to global phase)")
        print(f"  Circuit 1: {len(g1)} gates ({cx1} CX)")
        print(f"  Circuit 2: {len(g2)} gates ({cx2} CX)")
        if cx2 < cx1:
            print(f"  CX reduction: {cx1} -> {cx2} ({cx1 - cx2} removed)")
    else:
        print("FAIL: circuits are NOT unitarily equivalent")
        sys.exit(1)


if __name__ == "__main__":
    main()
