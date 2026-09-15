#!/usr/bin/env python3

"""
Fault propagation analyzer for quantum stabilizer circuits.

Implements Heisenberg-picture Pauli tracking through Clifford gates
using the XZ symplectic representation. Each single-qubit Pauli is
encoded as a pair of bits (x, z):
    I = (0, 0), X = (1, 0), Y = (1, 1), Z = (0, 1)

Clifford gate conjugation rules (global phase ignored):
    H:    swap x <-> z
    S:    z ^= x  (i.e., X->Y, Y->X, Z->Z)
    CX(c,t):  target_x ^= control_x;  control_z ^= target_z
"""

import stim


def _pauli_to_xz(p):
    """Map Pauli label to (x_bit, z_bit)."""
    return {"I": (0, 0), "X": (1, 0), "Y": (1, 1), "Z": (0, 1)}[p]


def _xz_to_pauli(x, z):
    """Map (x_bit, z_bit) to Pauli label."""
    return {(0, 0): "I", (1, 0): "X", (1, 1): "Y", (0, 1): "Z"}[(x, z)]


def _decompose_gates(circuit_str):
    """
    Parse a Stim circuit string into a flat list of individual gate operations.
    Packed instructions (e.g. 'CX 0 1 2 3') are split into separate pairs.

    Returns:
        List of (gate_name, [qubit_indices]) tuples.
    """
    if not circuit_str or not circuit_str.strip():
        return []

    circuit = stim.Circuit(circuit_str)
    ops = []
    for item in circuit:
        if isinstance(item, stim.CircuitRepeatBlock):
            body_str = str(item.body_copy())
            for _ in range(item.repeat_count):
                ops.extend(_decompose_gates(body_str))
            continue

        name = item.name
        # Skip non-gate instructions
        if name in (
            "TICK", "DETECTOR", "OBSERVABLE_INCLUDE", "QUBIT_COORDS",
            "SHIFT_COORDS", "M", "MR", "MX", "MY", "MZ", "R", "RX", "RY", "RZ",
        ):
            continue

        targets = [t.value for t in item.targets_copy() if t.is_qubit_target]
        if not targets:
            continue

        # Two-qubit gates: decompose into pairs
        if name in ("CX", "CZ", "SWAP", "XCZ", "XCY", "YCZ",
                     "ISWAP", "ISWAP_DAG", "SQRT_XX", "SQRT_ZZ", "SQRT_YY"):
            for i in range(0, len(targets), 2):
                ops.append((name, [targets[i], targets[i + 1]]))
        else:
            # Single-qubit gates: one per target
            for t in targets:
                ops.append((name, [t]))

    return ops


def _conjugate_pauli(pauli_xz, gate_name, gate_qubits):
    """
    Conjugate a multi-qubit Pauli through a single Clifford gate
    in the Heisenberg picture (U P U†).

    Args:
        pauli_xz: dict mapping qubit_index -> (x_bit, z_bit)
        gate_name: Stim gate name (H, S, S_DAG, CX, CZ, etc.)
        gate_qubits: list of qubit indices involved

    Modifies pauli_xz in place.
    """
    if gate_name == "H":
        q = gate_qubits[0]
        x, z = pauli_xz.get(q, (0, 0))
        pauli_xz[q] = (z, x)  # swap x <-> z

    elif gate_name in ("S", "S_DAG"):
        q = gate_qubits[0]
        x, z = pauli_xz.get(q, (0, 0))
        # S: X(1,0)->Y(1,1), Y(1,1)->X(1,0), Z->Z, I->I
        # Equivalently: z ^= x
        pauli_xz[q] = (x, z ^ x)

    elif gate_name == "X":
        # X gate conjugation: X->X, Z->-Z (weight unchanged), Y->-Y
        pass  # Weight-preserving, no change needed

    elif gate_name == "Z":
        # Z gate conjugation: X->-X, Z->Z, Y->-Y
        pass  # Weight-preserving, no change needed

    elif gate_name == "CX":
        c, t = gate_qubits
        cx, cz = pauli_xz.get(c, (0, 0))
        tx, tz = pauli_xz.get(t, (0, 0))
        # CX: control X spreads to target; target Z spreads to control
        new_tx = tx ^ cx
        new_cz = cz ^ tz
        pauli_xz[c] = (cx, new_cz)
        pauli_xz[t] = (new_tx, tz)

    elif gate_name == "CZ":
        c, t = gate_qubits
        cx, cz = pauli_xz.get(c, (0, 0))
        tx, tz = pauli_xz.get(t, (0, 0))
        # CZ: X on either qubit acquires Z on the other
        new_cz = cz ^ tx
        new_tz = tz ^ cx
        pauli_xz[c] = (cx, new_cz)
        pauli_xz[t] = (tx, new_tz)

    elif gate_name == "SWAP":
        a, b = gate_qubits
        pauli_xz[a], pauli_xz[b] = (
            pauli_xz.get(b, (0, 0)),
            pauli_xz.get(a, (0, 0)),
        )


def propagate_fault(circuit_str, fault_qubit, fault_layer, fault_pauli, n_qubits):
    """
    Propagate a single-point Pauli fault through the suffix of a circuit.

    The circuit is decomposed into m individual gate operations. A fault at
    layer j means the Pauli error F_{i,P} is inserted after the j-th operation.
    The resulting error E = C_suf(j) · F · C_suf(j)† is computed by tracking
    the Pauli through the suffix gates in the Heisenberg picture.

    Args:
        circuit_str: Circuit in Stim format.
        fault_qubit: Index of the qubit where the fault occurs.
        fault_layer: Boundary index (0 = before first gate, m = after last).
        fault_pauli: One of 'X', 'Y', 'Z'.
        n_qubits: Total number of qubits in the circuit.

    Returns:
        String of length n_qubits with per-qubit Pauli labels (e.g. 'XZI').
        Global phase is ignored.
    """
    ops = _decompose_gates(circuit_str)
    suffix_ops = ops[fault_layer:]

    # Initialize: fault Pauli on the specified qubit
    pauli_xz = {}
    pauli_xz[fault_qubit] = _pauli_to_xz(fault_pauli)

    # Propagate through each suffix gate
    for gate_name, gate_qubits in suffix_ops:
        _conjugate_pauli(pauli_xz, gate_name, gate_qubits)

    # Build result string
    result = []
    for q in range(n_qubits):
        x, z = pauli_xz.get(q, (0, 0))
        result.append(_xz_to_pauli(x, z))
    return "".join(result)


def compute_ft_score(circuit_str, data_qubits, flag_qubits, distance):
    """
    Compute the fault-tolerance score of a stabilizer circuit.

    Enumerates all n × (m+1) × 3 single-fault locations and counts the
    fraction where either:
      - the error weight on data qubits ≤ t = floor((d-1)/2), OR
      - at least one flag qubit has an X or Y error component.

    Args:
        circuit_str: Circuit in Stim format.
        data_qubits: List of data qubit indices.
        flag_qubits: List of flag (ancilla) qubit indices.
        distance: Code distance d.

    Returns:
        FT score as a float in [0, 1].
    """
    t = (distance - 1) // 2

    if not circuit_str or not circuit_str.strip():
        # Empty circuit: infer n_qubits from data + flag qubits
        all_qubits = set(data_qubits) | set(flag_qubits)
        n_qubits = max(all_qubits) + 1 if all_qubits else 0
    else:
        circuit = stim.Circuit(circuit_str)
        n_qubits = circuit.num_qubits

    if n_qubits == 0:
        return 1.0

    ops = _decompose_gates(circuit_str)
    m = len(ops)

    total_faults = 0
    safe_faults = 0

    for fault_layer in range(m + 1):
        for fault_qubit in range(n_qubits):
            for fault_pauli in ("X", "Y", "Z"):
                total_faults += 1
                error_str = propagate_fault(
                    circuit_str, fault_qubit, fault_layer, fault_pauli, n_qubits
                )

                # Weight on data qubits only
                weight = sum(1 for q in data_qubits if error_str[q] != "I")

                # Flag detection: X or Y on any flag qubit
                flagged = any(
                    error_str[q] in ("X", "Y") for q in flag_qubits
                )

                if weight <= t or flagged:
                    safe_faults += 1

    return safe_faults / total_faults if total_faults > 0 else 1.0


if __name__ == "__main__":
    import json

    with open("/app/problem.json") as f:
        problem = json.load(f)

    for circ_data in problem["circuits"]:
        cid = circ_data["id"]
        score = compute_ft_score(
            circ_data["circuit"],
            circ_data["data_qubits"],
            circ_data["flag_qubits"],
            circ_data["distance"],
        )
        print(f"{cid}: FT score = {score:.6f}")
