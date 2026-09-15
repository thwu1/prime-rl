#!/usr/bin/env python3

"""
Stabilizer code auditor and circuit synthesizer.

Validates each entry in /app/codes_db.json, diagnoses invalid entries,
and synthesizes optimized state-preparation circuits for valid codes.
"""

import json
import os
import sys

sys.path.insert(0, "/app/tools")

import stim
from check_stabilizers import check_stabilizers
from circuit_metric import compute_metrics

VALID_PAULIS = set("IXYZ")


def pauli_to_xz(ch):
    """Map a Pauli character to its (x, z) binary representation."""
    return {"I": (0, 0), "X": (1, 0), "Y": (1, 1), "Z": (0, 1)}[ch]


def symplectic_commutes(s1, s2):
    """Check if two Pauli strings commute via the symplectic inner product."""
    total = 0
    for c1, c2 in zip(s1, s2):
        x1, z1 = pauli_to_xz(c1)
        x2, z2 = pauli_to_xz(c2)
        total += x1 * z2 + x2 * z1
    return total % 2 == 0


def validate_code(entry):
    """Validate a stabilizer code entry. Returns (is_valid, diagnosis)."""
    n_qubits = entry["n_qubits"]
    stabilizers = entry["stabilizers"]

    # Check for invalid Pauli characters
    for s in stabilizers:
        for ch in s:
            if ch not in VALID_PAULIS:
                return False, (
                    f"Stabilizer '{s}' contains invalid character '{ch}'; "
                    f"only I, X, Y, Z are valid Pauli operators"
                )

    # Check that stabilizer lengths match declared qubit count
    for s in stabilizers:
        if len(s) != n_qubits:
            return False, (
                f"Stabilizer '{s}' has length {len(s)} but code declares "
                f"{n_qubits} qubits — length mismatch"
            )

    # Check mutual commutativity of all generator pairs
    for i in range(len(stabilizers)):
        for j in range(i + 1, len(stabilizers)):
            if not symplectic_commutes(stabilizers[i], stabilizers[j]):
                return False, (
                    f"Stabilizers '{stabilizers[i]}' and '{stabilizers[j]}' "
                    f"do not commute (anti-commuting pair detected via "
                    f"symplectic inner product)"
                )

    return True, ""


def synthesize_circuit(stabilizer_strs):
    """Build a Stim circuit from stabilizer generators via tableau decomposition."""
    pauli_stabs = [stim.PauliString("+" + s) for s in stabilizer_strs]
    tableau = stim.Tableau.from_stabilizers(
        pauli_stabs, allow_underconstrained=True
    )
    circuit = tableau.to_circuit("elimination")
    return str(circuit)


def _parse_instructions(circuit_str):
    circuit = stim.Circuit(circuit_str)
    instructions = []
    for inst in circuit:
        name = inst.name
        targets = [t.value for t in inst.targets_copy() if t.is_qubit_target]
        if targets:
            instructions.append((name, targets))
    return instructions


def _instructions_to_str(instructions):
    lines = []
    for name, targets in instructions:
        lines.append(f"{name} {' '.join(str(t) for t in targets)}")
    return "\n".join(lines)


def optimize_circuit(circuit_str, stabilizer_strs, max_rounds=20):
    """Peephole optimization: cancel self-inverse gates, S/S_DAG pairs, S^4."""
    instructions = _parse_instructions(circuit_str)
    self_inverse = {"CX", "CZ", "SWAP", "H", "X", "Z", "Y"}

    for _ in range(max_rounds):
        changed = False

        # Pass 1: adjacent identical self-inverse cancellation
        new_insts = []
        i = 0
        while i < len(instructions):
            if i + 1 < len(instructions):
                n1, t1 = instructions[i]
                n2, t2 = instructions[i + 1]
                if n1 == n2 and t1 == t2 and n1 in self_inverse:
                    i += 2
                    changed = True
                    continue
            new_insts.append(instructions[i])
            i += 1
        instructions = new_insts

        # Pass 2: S/S_DAG cancellation and S^4 = I
        new_insts = []
        i = 0
        while i < len(instructions):
            if i + 1 < len(instructions):
                n1, t1 = instructions[i]
                n2, t2 = instructions[i + 1]
                if t1 == t2:
                    if (n1 == "S" and n2 == "S_DAG") or (
                        n1 == "S_DAG" and n2 == "S"
                    ):
                        i += 2
                        changed = True
                        continue
            if i + 3 < len(instructions):
                n1, t1 = instructions[i]
                n2, t2 = instructions[i + 1]
                n3, t3 = instructions[i + 2]
                n4, t4 = instructions[i + 3]
                if n1 == n2 == n3 == n4 == "S" and t1 == t2 == t3 == t4:
                    i += 4
                    changed = True
                    continue
            new_insts.append(instructions[i])
            i += 1
        instructions = new_insts

        # Pass 3: commute disjoint gates to expose cancellable pairs
        swapped = True
        while swapped:
            swapped = False
            for j in range(len(instructions) - 1):
                n1, t1 = instructions[j]
                n2, t2 = instructions[j + 1]
                q1 = set(t1)
                q2 = set(t2)
                if not q1.isdisjoint(q2):
                    continue
                can_cancel = False
                if j + 2 < len(instructions):
                    n3, t3 = instructions[j + 2]
                    if n1 == n3 and t1 == t3 and n1 in self_inverse:
                        can_cancel = True
                if j >= 1:
                    n0, t0 = instructions[j - 1]
                    if n2 == n0 and t2 == t0 and n2 in self_inverse:
                        can_cancel = True
                if can_cancel:
                    instructions[j], instructions[j + 1] = (
                        instructions[j + 1],
                        instructions[j],
                    )
                    swapped = True
                    changed = True
                    break

        if not changed:
            break

    result = _instructions_to_str(instructions)
    verdicts = check_stabilizers(result, stabilizer_strs)
    if all(verdicts.values()):
        return result
    return circuit_str


def main():
    with open("/app/codes_db.json") as f:
        codes = json.load(f)

    results = []

    for code in codes:
        name = code["name"]
        stabilizers = code["stabilizers"]
        budget = code["two_qubit_gate_budget"]

        is_valid, diagnosis = validate_code(code)

        if not is_valid:
            print(f"[{name}] INVALID: {diagnosis}")
            results.append({
                "name": name,
                "status": "invalid",
                "diagnosis": diagnosis,
                "circuit": "",
            })
            continue

        print(f"[{name}] Valid — synthesizing circuit...")

        circuit_str = synthesize_circuit(stabilizers)
        metrics_raw = compute_metrics(circuit_str)
        print(f"  Raw: {metrics_raw.two_qubit_gates} two-qubit gates")

        optimized = optimize_circuit(circuit_str, stabilizers)
        metrics_opt = compute_metrics(optimized)
        print(f"  Optimized: {metrics_opt.two_qubit_gates} two-qubit gates")

        if metrics_opt.two_qubit_gates > budget:
            print(f"  Budget {budget}: EXCEEDED — trying alternative decomposition")
            try:
                pauli_stabs = [stim.PauliString("+" + s) for s in stabilizers]
                tableau = stim.Tableau.from_stabilizers(
                    pauli_stabs, allow_underconstrained=True
                )
                alt_circuit = str(tableau.to_circuit("graph_state"))
                alt_opt = optimize_circuit(alt_circuit, stabilizers)
                alt_metrics = compute_metrics(alt_opt)
                if alt_metrics.two_qubit_gates < metrics_opt.two_qubit_gates:
                    optimized = alt_opt
                    metrics_opt = alt_metrics
                    print(f"  Alt: {metrics_opt.two_qubit_gates} two-qubit gates")
            except Exception as e:
                print(f"  Alt decomposition failed: {e}")

        verdicts = check_stabilizers(optimized, stabilizers)
        assert all(verdicts.values()), (
            f"Code {name}: optimized circuit fails stabilizer check!"
        )

        results.append({
            "name": name,
            "status": "valid",
            "diagnosis": "",
            "circuit": optimized,
        })
        print(f"  Budget {budget}: {'OK' if metrics_opt.two_qubit_gates <= budget else 'EXCEEDED'}")

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDone. {len(results)} entries written to /app/output/results.json")


if __name__ == "__main__":
    main()
