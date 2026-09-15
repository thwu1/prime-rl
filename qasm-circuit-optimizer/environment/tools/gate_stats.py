#!/usr/bin/env python3
"""Print gate statistics for an OpenQASM 2.0 circuit."""
import sys
import re
from collections import Counter


def main():
    if len(sys.argv) != 2:
        print("Usage: gate_stats.py <file.qasm>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        text = f.read()

    n_qubits = None
    gates = Counter()
    gate_qubits = {}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if line.startswith("OPENQASM") or line.startswith("include"):
            continue
        m = re.match(r"qreg\s+\w+\[(\d+)\]\s*;", line)
        if m:
            n_qubits = int(m.group(1))
            continue
        if line.startswith("creg") or line.startswith("barrier"):
            continue
        m = re.match(r"(\w+)\s*(?:\([^)]*\))?\s+(.+);", line)
        if m:
            name = m.group(1)
            qubits = [int(qm.group(1)) for qm in re.finditer(r"\w+\[(\d+)\]", m.group(2))]
            gates[name] += 1
            if name not in gate_qubits:
                gate_qubits[name] = len(qubits)

    multi_q_types = {g for g, nq in gate_qubits.items() if nq >= 2}
    mq_count = sum(c for g, c in gates.items() if g in multi_q_types)

    print(f"Qubits: {n_qubits}")
    print(f"Total gates: {sum(gates.values())}")
    print("Gate breakdown:")
    for g, c in sorted(gates.items()):
        tag = " [multi-qubit]" if g in multi_q_types else ""
        print(f"  {g}: {c}{tag}")
    print(f"Multi-qubit gates: {mq_count}")


if __name__ == "__main__":
    main()
