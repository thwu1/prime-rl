"""Pre-defined quantum circuits for benchmarking."""

import numpy as np
from simulator import Gate, Circuit


def ghz_circuit(n_qubits: int) -> Circuit:
    """GHZ state preparation: H on q0, then CNOTs down the chain."""
    circuit = [Gate('H', (0,))]
    for i in range(n_qubits - 1):
        circuit.append(Gate('CNOT', (i, i + 1)))
    return circuit


def random_clifford_circuit(n_qubits: int, depth: int,
                            seed: int = 42) -> Circuit:
    """Random Clifford circuit with single-qubit gates and CNOTs."""
    rng = np.random.RandomState(seed)
    cliffords = ['H', 'S', 'X', 'Y', 'Z']
    circuit = []
    for _ in range(depth):
        for q in range(n_qubits):
            circuit.append(Gate(rng.choice(cliffords), (q,)))
        if n_qubits > 1:
            q = rng.randint(0, n_qubits - 1)
            circuit.append(Gate('CNOT', (q, q + 1)))
    return circuit


def mirror_circuit(base_circuit: Circuit) -> Circuit:
    """base + inverse(base) — implements identity in the noiseless case."""
    inverse = [g.dagger() for g in reversed(base_circuit)]
    return list(base_circuit) + inverse


def parametric_circuit(n_qubits: int, params: list) -> Circuit:
    """Parametric ansatz with RZ/RX rotations and CNOT entanglement."""
    circuit = []
    idx = 0
    for q in range(n_qubits):
        if idx < len(params):
            circuit.append(Gate('RZ', (q,), (params[idx],)))
            idx += 1
        if idx < len(params):
            circuit.append(Gate('RX', (q,), (params[idx],)))
            idx += 1
    for q in range(n_qubits - 1):
        circuit.append(Gate('CNOT', (q, q + 1)))
    for q in range(n_qubits):
        if idx < len(params):
            circuit.append(Gate('RY', (q,), (params[idx],)))
            idx += 1
    return circuit


def identity_circuit(n_qubits: int, depth: int) -> Circuit:
    """Circuit that implements identity via self-canceling X pairs."""
    circuit = []
    for _ in range(depth):
        for q in range(n_qubits):
            circuit.append(Gate('X', (q,)))
            circuit.append(Gate('X', (q,)))
    return circuit
