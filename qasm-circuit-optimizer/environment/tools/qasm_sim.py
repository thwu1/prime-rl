#!/usr/bin/env python3
"""Compute and display the unitary matrix of an OpenQASM 2.0 circuit."""
import sys
import numpy as np
from qasm_utils import parse_qasm, circuit_unitary, count_cx


def main():
    if len(sys.argv) != 2:
        print("Usage: qasm_sim.py <file.qasm>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    n, gates = parse_qasm(text)

    if n > 6:
        print(
            f"Circuit has {n} qubits ({2**n}x{2**n} matrix) -- too large to display.",
            file=sys.stderr,
        )
        sys.exit(1)

    U = circuit_unitary(n, gates)

    print(f"Circuit: {sys.argv[1]}")
    print(f"Qubits: {n}")
    print(f"Gates: {len(gates)}  (CX: {count_cx(gates)})")
    print(f"Unitary ({2**n}x{2**n}):")
    np.set_printoptions(precision=4, linewidth=200, suppress=True)
    print(U)


if __name__ == "__main__":
    main()
