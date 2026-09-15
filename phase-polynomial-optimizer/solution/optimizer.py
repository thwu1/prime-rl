#!/usr/bin/env python3

"""Quantum circuit T-count optimizer.

Reads OpenQASM 2.0 benchmarks, reduces non-Clifford gate count via
phase polynomial optimization, writes optimized QASM to /app/results/.
"""

import json
import math
import os
import re
import sys

sys.path.insert(0, "/app")
from circuit import Circuit, Gate


# ============================================================
# QASM parsing and writing
# ============================================================

def parse_qasm(text):
    """Parse OpenQASM 2.0 into internal Circuit representation."""
    n_qubits = None
    circ = None

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("OPENQASM") or line.startswith("include"):
            continue

        m = re.match(r"qreg\s+\w+\[(\d+)\]", line)
        if m:
            n_qubits = int(m.group(1))
            circ = Circuit(n_qubits)
            continue

        if circ is None:
            continue

        line = line.rstrip(";").strip()

        if re.match(r"^tdg\s", line):
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.tdg(q)
        elif re.match(r"^t\s", line):
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.t(q)
        elif re.match(r"^sdg\s", line):
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.sdg(q)
        elif re.match(r"^s\s", line):
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.s(q)
        elif re.match(r"^z\s", line):
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.z(q)
        elif re.match(r"^h\s", line):
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.h(q)
        elif re.match(r"^cx\s", line):
            qubits = re.findall(r"\[(\d+)\]", line)
            circ.cnot(int(qubits[0]), int(qubits[1]))
        elif re.match(r"^rz\(", line):
            angle_str = re.search(r"rz\(([^)]+)\)", line).group(1)
            angle_rad = float(
                eval(angle_str, {"pi": math.pi, "PI": math.pi, "__builtins__": {}})
            )
            q = int(re.search(r"\[(\d+)\]", line).group(1))
            circ.rz(q, angle_rad / math.pi)

    return circ


def to_qasm(circ):
    """Convert internal Circuit to OpenQASM 2.0 string."""
    lines = [
        "OPENQASM 2.0;",
        'include "qelib1.inc";',
        f"qreg q[{circ.n_qubits}];",
    ]

    for gate in circ.gates:
        if gate.name == "H":
            lines.append(f"h q[{gate.qubits[0]}];")
        elif gate.name == "CNOT":
            lines.append(f"cx q[{gate.qubits[0]}],q[{gate.qubits[1]}];")
        elif gate.name == "Rz":
            a = gate.angle
            q = gate.qubits[0]
            emitted = False
            for ref, gname in [
                (0.25, "t"),
                (-0.25, "tdg"),
                (0.5, "s"),
                (-0.5, "sdg"),
            ]:
                if abs(a - ref) < 1e-10:
                    lines.append(f"{gname} q[{q}];")
                    emitted = True
                    break
            if not emitted:
                if abs(abs(a) - 1.0) < 1e-10:
                    lines.append(f"z q[{q}];")
                elif abs(a) < 1e-10:
                    pass  # identity rotation, skip
                elif abs(a - 0.75) < 1e-10:
                    lines.append(f"s q[{q}];")
                    lines.append(f"t q[{q}];")
                elif abs(a + 0.75) < 1e-10:
                    lines.append(f"sdg q[{q}];")
                    lines.append(f"tdg q[{q}];")
                else:
                    lines.append(f"rz({a * math.pi}) q[{q}];")

    return "\n".join(lines) + "\n"


# ============================================================
# Phase polynomial data structure
# ============================================================

class PhasePolynomial:
    """Phase polynomial: set of (parity_vector, angle) terms + output parity matrix."""

    def __init__(self, n):
        self.n_qubits = n
        self.terms = {}
        self.parity_matrix = [
            [1 if i == j else 0 for j in range(n)] for i in range(n)
        ]

    def add_term(self, parity, angle):
        if parity in self.terms:
            self.terms[parity] += angle
        else:
            self.terms[parity] = angle


# ============================================================
# Phase polynomial extraction
# ============================================================

def extract(circuit):
    """Extract phase polynomial from a {CNOT, Rz}-only circuit."""
    n = circuit.n_qubits
    pp = PhasePolynomial(n)
    labels = [[1 if i == j else 0 for j in range(n)] for i in range(n)]

    for gate in circuit.gates:
        if gate.name == "CNOT":
            c, t = gate.qubits
            for j in range(n):
                labels[t][j] ^= labels[c][j]
        elif gate.name == "Rz":
            q = gate.qubits[0]
            parity = tuple(labels[q])
            pp.add_term(parity, gate.angle)
        else:
            raise ValueError(f"Unexpected gate in CNOT+Rz block: {gate.name}")

    pp.parity_matrix = [list(row) for row in labels]
    return pp


# ============================================================
# Phase polynomial optimization
# ============================================================

def optimize_pp(pp):
    """Normalize angles to (-1, 1] and remove zero terms."""
    result = PhasePolynomial(pp.n_qubits)
    result.parity_matrix = [list(row) for row in pp.parity_matrix]

    for parity, angle in pp.terms.items():
        a = angle % 2.0
        if a > 1.0:
            a -= 2.0
        if abs(a) > 1e-10:
            result.terms[parity] = a

    return result


# ============================================================
# Circuit synthesis from phase polynomial
# ============================================================

def synthesize(pp):
    """Build a {CNOT, Rz} circuit that realises the phase polynomial."""
    n = pp.n_qubits
    circ = Circuit(n)

    for parity, angle in pp.terms.items():
        f = list(parity)
        if 1 not in f:
            continue  # all-zero parity = global phase

        target = f.index(1)
        cnots = []

        for q in range(n):
            if q != target and f[q]:
                circ.cnot(q, target)
                cnots.append(q)

        circ.rz(target, angle)

        for q in reversed(cnots):
            circ.cnot(q, target)

    _decompose_parity(circ, pp.parity_matrix, n)
    return circ


def _decompose_parity(circ, target, n):
    """Decompose invertible binary matrix into CNOT gates via GF(2) elimination."""
    if all(
        target[i][j] == (1 if i == j else 0)
        for i in range(n)
        for j in range(n)
    ):
        return

    M = [list(row) for row in target]
    ops = []

    # Forward elimination
    for col in range(n):
        pivot = None
        for row in range(col, n):
            if M[row][col]:
                pivot = row
                break
        if pivot is None:
            raise ValueError("Parity matrix is singular")

        if pivot != col:
            # Row swap via three XOR operations
            ops.append((pivot, col))
            for j in range(n):
                M[col][j] ^= M[pivot][j]
            ops.append((col, pivot))
            for j in range(n):
                M[pivot][j] ^= M[col][j]
            ops.append((pivot, col))
            for j in range(n):
                M[col][j] ^= M[pivot][j]

        for row in range(col + 1, n):
            if M[row][col]:
                ops.append((col, row))
                for j in range(n):
                    M[row][j] ^= M[col][j]

    # Back substitution
    for col in range(n - 1, -1, -1):
        for row in range(col):
            if M[row][col]:
                ops.append((col, row))
                for j in range(n):
                    M[row][j] ^= M[col][j]

    # Apply in reverse order as CNOT gates
    for c, t in reversed(ops):
        circ.cnot(c, t)


# ============================================================
# Full optimization pipeline (handles H gates)
# ============================================================

def optimize_circuit(circuit):
    """Optimize an {H, CNOT, Rz} circuit by partitioning at Hadamard boundaries."""
    n = circuit.n_qubits
    blocks = []
    current = Circuit(n)

    for gate in circuit.gates:
        if gate.name == "H":
            blocks.append(("block", current))
            blocks.append(("h", gate.qubits[0]))
            current = Circuit(n)
        else:
            current.gates.append(Gate(gate.name, list(gate.qubits), gate.angle))
    blocks.append(("block", current))

    result = Circuit(n)
    for kind, data in blocks:
        if kind == "h":
            result.h(data)
        else:
            if not data.gates:
                continue
            pp = extract(data)
            pp_opt = optimize_pp(pp)
            opt_blk = synthesize(pp_opt)
            result.gates.extend(opt_blk.gates)

    return result


# ============================================================
# Main entry point
# ============================================================

def main():
    benchmarks_dir = "/app/benchmarks"
    results_dir = "/app/results"
    targets_path = "/app/targets.json"

    os.makedirs(results_dir, exist_ok=True)

    with open(targets_path) as f:
        targets = json.load(f)

    for name in sorted(targets.keys()):
        in_path = os.path.join(benchmarks_dir, name)
        out_path = os.path.join(results_dir, name)

        with open(in_path) as f:
            qasm_text = f.read()

        circ = parse_qasm(qasm_text)
        original_t = circ.t_count()

        opt = optimize_circuit(circ)
        optimized_t = opt.t_count()

        with open(out_path, "w") as f:
            f.write(to_qasm(opt))

        print(f"{name}: T-count {original_t} -> {optimized_t}")


if __name__ == "__main__":
    main()
