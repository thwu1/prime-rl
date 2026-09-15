"""Density matrix quantum circuit simulator with depolarizing noise.

Supported gates: I, X, Y, Z, H, S, Sdg, T, Tdg (single-qubit), CNOT (two-qubit).

Circuit format (JSON):
{
    "id": str,
    "n_qubits": int,
    "gates": [{"name": str, "targets": [int, ...]}],
    "observable": 2d nested list representing a Hermitian matrix
}

Usage:
    from simulator import simulate, load_circuit, GATE_ADJOINTS
    circuit = load_circuit("circuits/example.json")
    ideal = simulate(circuit, noise_level=0.0)
    noisy = simulate(circuit, noise_level=0.01)
"""
import json
import numpy as np


GATES_1Q = {
    "I": np.eye(2, dtype=complex),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "H": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "Sdg": np.array([[1, 0], [0, -1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    "Tdg": np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=complex),
}

GATE_ADJOINTS = {
    "I": "I", "X": "X", "Y": "Y", "Z": "Z", "H": "H",
    "S": "Sdg", "Sdg": "S", "T": "Tdg", "Tdg": "T", "CNOT": "CNOT",
}


def _full_operator_1q(gate_matrix, target, n_qubits):
    """Build full Hilbert space operator for a single-qubit gate."""
    op = np.array([[1.0]], dtype=complex)
    for q in range(n_qubits):
        op = np.kron(op, gate_matrix if q == target else np.eye(2, dtype=complex))
    return op


def _full_cnot(control, target, n_qubits):
    """Build full Hilbert space CNOT operator."""
    dim = 2 ** n_qubits
    op = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        bits = [(i >> (n_qubits - 1 - q)) & 1 for q in range(n_qubits)]
        new_bits = list(bits)
        if bits[control] == 1:
            new_bits[target] = 1 - bits[target]
        j = sum(b << (n_qubits - 1 - q) for q, b in enumerate(new_bits))
        op[j, i] = 1.0
    return op


def _depolarize(rho, qubit, n_qubits, p):
    """Apply single-qubit depolarizing channel with error probability p.

    Channel: rho -> (1-p)*rho + (p/3)*(X*rho*X + Y*rho*Y + Z*rho*Z)
    """
    if p <= 0:
        return rho
    paulis_1q = [
        np.array([[0, 1], [1, 0]], dtype=complex),
        np.array([[0, -1j], [1j, 0]], dtype=complex),
        np.array([[1, 0], [0, -1]], dtype=complex),
    ]
    result = (1 - p) * rho
    for pauli in paulis_1q:
        op = _full_operator_1q(pauli, qubit, n_qubits)
        result = result + (p / 3.0) * (op @ rho @ op.conj().T)
    return result


def simulate(circuit, noise_level=0.0):
    """Simulate circuit and return Tr[observable * final_state].

    Args:
        circuit: dict with n_qubits, gates, observable.
        noise_level: depolarizing error probability per gate per target qubit.

    Returns:
        float: expectation value of the observable.
    """
    n = circuit["n_qubits"]
    dim = 2 ** n
    rho = np.zeros((dim, dim), dtype=complex)
    rho[0, 0] = 1.0

    for gate in circuit["gates"]:
        name = gate["name"]
        targets = gate["targets"]

        if name == "CNOT":
            op = _full_cnot(targets[0], targets[1], n)
        else:
            op = _full_operator_1q(GATES_1Q[name], targets[0], n)

        rho = op @ rho @ op.conj().T

        if noise_level > 0:
            for q in targets:
                rho = _depolarize(rho, q, n, noise_level)

    obs = np.array(circuit["observable"], dtype=complex)
    return float(np.real(np.trace(rho @ obs)))


def load_circuit(path):
    """Load a circuit definition from a JSON file."""
    with open(path) as f:
        return json.load(f)
