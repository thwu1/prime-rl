#!/usr/bin/env python3
"""Quantum circuit optimizer for OpenQASM 2.0.

Reads an OpenQASM 2.0 file, applies gate-cancellation optimizations
(adjacent-inverse removal and commutation-aware CX cancellation),
and writes the optimized circuit to stdout.

No external quantum libraries are used.
"""
import sys
import re


# ---------------------------------------------------------------------------
# QASM Parser
# ---------------------------------------------------------------------------

def parse_qasm(filename):
    """Parse a QASM file into header lines, qubit count, register name, and
    a list of gate dicts."""
    with open(filename) as f:
        text = f.read()

    header_lines = []
    n_qubits = None
    reg_name = "q"
    gates = []

    for line in text.strip().split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            header_lines.append(line)
            continue
        if stripped.startswith("OPENQASM"):
            header_lines.append(line)
            continue
        if stripped.startswith("include"):
            header_lines.append(line)
            continue

        m = re.match(r"qreg\s+(\w+)\[(\d+)\]\s*;", stripped)
        if m:
            reg_name = m.group(1)
            n_qubits = int(m.group(2))
            header_lines.append(line)
            continue

        if stripped.startswith("creg") or stripped.startswith("barrier"):
            header_lines.append(line)
            continue

        # Gate line: name[(params)] qubit_list;
        m = re.match(r"(\w+)\s*(?:\(([^)]*)\))?\s+(.+);", stripped)
        if m:
            name = m.group(1)
            params_str = m.group(2)
            qubits_str = m.group(3)
            qubits = [
                int(qm.group(1))
                for qm in re.finditer(r"\w+\[(\d+)\]", qubits_str)
            ]
            gates.append(
                {"name": name, "qubits": qubits, "params_str": params_str}
            )

    return header_lines, n_qubits, reg_name, gates


# ---------------------------------------------------------------------------
# Optimization helpers
# ---------------------------------------------------------------------------

_SELF_INVERSE = frozenset({"cx", "h", "x", "y", "z"})
_INVERSE_PAIRS = frozenset(
    {("s", "sdg"), ("sdg", "s"), ("t", "tdg"), ("tdg", "t")}
)
_DIAGONAL_GATES = frozenset({"z", "s", "sdg", "t", "tdg", "id", "rz", "u1"})
_X_TYPE_GATES = frozenset({"x", "id"})


def are_inverse_pair(g1, g2):
    """Return True if g1 and g2 cancel each other (inverse pair)."""
    if g1["qubits"] != g2["qubits"]:
        return False
    if g1["name"] == g2["name"] and g1["name"] in _SELF_INVERSE:
        return True
    return (g1["name"], g2["name"]) in _INVERSE_PAIRS


def can_commute_past_cx(gate, cx_control, cx_target):
    """Return True if *gate* commutes with CX(cx_control, cx_target)."""
    if gate["name"] == "cx":
        return False
    if len(gate["qubits"]) != 1:
        return False
    qubit = gate["qubits"][0]
    # Disjoint qubits always commute
    if qubit != cx_control and qubit != cx_target:
        return True
    # Diagonal gate on control commutes
    if qubit == cx_control and gate["name"] in _DIAGONAL_GATES:
        return True
    # X-type gate on target commutes
    if qubit == cx_target and gate["name"] in _X_TYPE_GATES:
        return True
    return False


# ---------------------------------------------------------------------------
# Optimization passes
# ---------------------------------------------------------------------------

def cancel_adjacent_inverses(gates):
    """Remove adjacent pairs of inverse gates.  Repeats until stable."""
    changed = True
    while changed:
        changed = False
        new_gates = []
        i = 0
        while i < len(gates):
            if (
                i + 1 < len(gates)
                and are_inverse_pair(gates[i], gates[i + 1])
            ):
                i += 2
                changed = True
            else:
                new_gates.append(gates[i])
                i += 1
        gates = new_gates
    return gates


def commute_and_cancel_cx(gates):
    """Cancel CX pairs separated only by commuting gates."""
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(gates):
            if gates[i]["name"] != "cx":
                i += 1
                continue
            cx_ctrl = gates[i]["qubits"][0]
            cx_targ = gates[i]["qubits"][1]

            found = False
            all_commute = True
            for j in range(i + 1, len(gates)):
                g = gates[j]
                if (
                    g["name"] == "cx"
                    and g["qubits"] == [cx_ctrl, cx_targ]
                ):
                    if all_commute:
                        # Remove both CX gates, keep intermediates in place
                        gates = gates[:i] + gates[i + 1 : j] + gates[j + 1 :]
                        changed = True
                        found = True
                    break
                if not can_commute_past_cx(g, cx_ctrl, cx_targ):
                    all_commute = False
                    break

            if not found:
                i += 1
    return gates


def optimize(gates):
    """Run all optimization passes until convergence."""
    prev_len = -1
    while len(gates) != prev_len:
        prev_len = len(gates)
        gates = cancel_adjacent_inverses(gates)
        gates = commute_and_cancel_cx(gates)
    return gates


# ---------------------------------------------------------------------------
# QASM output
# ---------------------------------------------------------------------------

def gates_to_qasm(header_lines, reg_name, gates):
    """Reconstruct a valid QASM string from header and gate list."""
    lines = list(header_lines)
    for gate in gates:
        qubits = ", ".join(f"{reg_name}[{q}]" for q in gate["qubits"])
        if gate.get("params_str"):
            lines.append(f"{gate['name']}({gate['params_str']}) {qubits};")
        else:
            lines.append(f"{gate['name']} {qubits};")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print("Usage: optimize.py <input.qasm>", file=sys.stderr)
        sys.exit(1)

    header_lines, n_qubits, reg_name, gates = parse_qasm(sys.argv[1])
    gates = optimize(gates)
    print(gates_to_qasm(header_lines, reg_name, gates), end="")


if __name__ == "__main__":
    main()
