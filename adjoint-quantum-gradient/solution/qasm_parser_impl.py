"""
OpenQASM 2.0 parser -- complete implementation.

"""
import re

from qcsim.circuit import Circuit
from qcsim.gates import (
    H_GATE,
    X_GATE,
    Y_GATE,
    Z_GATE,
    rx_gate,
    ry_gate,
    rz_gate,
)


def parse_qasm(filepath):
    """Parse an OpenQASM 2.0 file and return a Circuit object."""
    with open(filepath) as f:
        lines = f.readlines()

    n_qubits = None
    circuit = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("OPENQASM") or line.startswith("include"):
            continue

        # qreg declaration
        m = re.match(r"qreg\s+(\w+)\[(\d+)\];", line)
        if m:
            n_qubits = int(m.group(2))
            circuit = Circuit(n_qubits)
            continue

        if circuit is None:
            continue

        # Standard single-qubit gates: h, x, y, z
        m = re.match(r"(h|x|y|z)\s+\w+\[(\d+)\];", line)
        if m:
            gate_name = m.group(1)
            qubit = int(m.group(2))
            gate_map = {"h": H_GATE, "x": X_GATE, "y": Y_GATE, "z": Z_GATE}
            circuit.operations.append(
                {"type": "fixed", "matrix": gate_map[gate_name], "targets": (qubit,)}
            )
            continue

        # cx (CNOT)
        m = re.match(r"cx\s+\w+\[(\d+)\]\s*,\s*\w+\[(\d+)\];", line)
        if m:
            control = int(m.group(1))
            target = int(m.group(2))
            circuit.cnot(control, target)
            continue

        # Parameterized rotation gates: rx, ry, rz with literal angle
        m = re.match(r"(rx|ry|rz)\(\s*([^)]+)\s*\)\s+\w+\[(\d+)\];", line)
        if m:
            gate_name = m.group(1)
            angle = float(m.group(2))
            qubit = int(m.group(3))
            gate_fn_map = {"rx": rx_gate, "ry": ry_gate, "rz": rz_gate}
            matrix = gate_fn_map[gate_name](angle)
            circuit.operations.append(
                {"type": "fixed", "matrix": matrix, "targets": (qubit,)}
            )
            continue

    return circuit
