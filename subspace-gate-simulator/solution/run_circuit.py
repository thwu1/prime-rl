
"""
Run the quantum circuit defined in /app/circuit.json using the qsim module
and write the output state vector to /app/output.json.
"""

import sys
import json
import cmath
import numpy as np

sys.path.insert(0, '/app')
import qsim


def get_gate_matrix(gate_def):
    """Build the unitary matrix for a gate definition."""
    name = gate_def["gate"]
    params = gate_def.get("params")

    if name == "H":
        return np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    elif name == "X":
        return np.array([[0, 1], [1, 0]], dtype=complex)
    elif name == "Y":
        return np.array([[0, -1j], [1j, 0]], dtype=complex)
    elif name == "Z":
        return np.array([[1, 0], [0, -1]], dtype=complex)
    elif name == "S":
        return np.array([[1, 0], [0, 1j]], dtype=complex)
    elif name == "T":
        return np.array([[1, 0], [0, cmath.exp(1j * cmath.pi / 4)]],
                        dtype=complex)
    elif name == "RX":
        theta = params["theta"]
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)
    elif name == "RY":
        theta = params["theta"]
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array([[c, -s], [s, c]], dtype=complex)
    elif name == "RZ":
        theta = params["theta"]
        return np.array([[cmath.exp(-1j * theta / 2), 0],
                         [0, cmath.exp(1j * theta / 2)]], dtype=complex)
    elif name == "SWAP":
        return np.array([[1, 0, 0, 0], [0, 0, 1, 0],
                         [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex)
    elif name == "CUSTOM":
        mr = np.array(gate_def["matrix_real"], dtype=float)
        mi = np.array(gate_def["matrix_imag"], dtype=float)
        return mr + 1j * mi
    else:
        raise ValueError(f"Unknown gate: {name}")


def main():
    with open('/app/circuit.json') as f:
        circuit = json.load(f)

    n_qubits = circuit["n_qubits"]
    state = np.zeros(1 << n_qubits, dtype=complex)
    state[0] = 1.0  # |0...0⟩

    for gate_def in circuit["gates"]:
        matrix = get_gate_matrix(gate_def)
        targets = gate_def["targets"]

        if "controls" in gate_def and gate_def["controls"]:
            ctrl_qubits = [c["qubit"] for c in gate_def["controls"]]
            ctrl_values = [c["value"] for c in gate_def["controls"]]
            state = qsim.apply_controlled_gate(
                state, matrix, targets, ctrl_qubits, ctrl_values)
        else:
            state = qsim.apply_gate(state, matrix, targets)

    # Write output
    output = {
        "n_qubits": n_qubits,
        "state": [[float(x.real), float(x.imag)] for x in state]
    }
    with open('/app/output.json', 'w') as f:
        json.dump(output, f)

    # Verification
    norm_sq = np.sum(np.abs(state) ** 2)
    print(f"Circuit simulation complete: {n_qubits} qubits, "
          f"norm^2 = {norm_sq:.10f}")


if __name__ == "__main__":
    main()
