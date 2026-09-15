"""Density matrix quantum circuit simulator with depolarizing noise."""

import numpy as np
from typing import List, Tuple, Optional

# Single-qubit gate matrices
GATES = {
    'I': np.eye(2, dtype=complex),
    'X': np.array([[0, 1], [1, 0]], dtype=complex),
    'Y': np.array([[0, -1j], [1j, 0]], dtype=complex),
    'Z': np.array([[1, 0], [0, -1]], dtype=complex),
    'H': np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    'S': np.array([[1, 0], [0, 1j]], dtype=complex),
    'T': np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    'CNOT': np.array([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
        [0, 0, 1, 0],
    ], dtype=complex),
}
GATES['S_DAG'] = np.conj(GATES['S'].T)
GATES['T_DAG'] = np.conj(GATES['T'].T)


def _rx(theta):
    return np.array([
        [np.cos(theta / 2), -1j * np.sin(theta / 2)],
        [-1j * np.sin(theta / 2), np.cos(theta / 2)],
    ], dtype=complex)


def _ry(theta):
    return np.array([
        [np.cos(theta / 2), -np.sin(theta / 2)],
        [np.sin(theta / 2), np.cos(theta / 2)],
    ], dtype=complex)


def _rz(theta):
    return np.array([
        [np.exp(-1j * theta / 2), 0],
        [0, np.exp(1j * theta / 2)],
    ], dtype=complex)


class Gate:
    """A quantum gate applied to specific qubits."""

    def __init__(self, name: str, qubits: Tuple[int, ...],
                 params: Tuple[float, ...] = ()):
        self.name = name
        self.qubits = qubits
        self.params = params

    def matrix(self) -> np.ndarray:
        if self.name in GATES:
            return GATES[self.name]
        elif self.name == 'RX':
            return _rx(self.params[0])
        elif self.name == 'RY':
            return _ry(self.params[0])
        elif self.name == 'RZ':
            return _rz(self.params[0])
        else:
            raise ValueError(f"Unknown gate: {self.name}")

    def dagger(self) -> 'Gate':
        """Return the adjoint (conjugate transpose) of this gate."""
        if self.name in ('RX', 'RY', 'RZ'):
            return Gate(self.name, self.qubits, (-self.params[0],))
        elif self.name in ('X', 'Y', 'Z', 'H', 'I', 'CNOT'):
            return Gate(self.name, self.qubits, self.params)
        elif self.name == 'S':
            return Gate('S_DAG', self.qubits, ())
        elif self.name == 'S_DAG':
            return Gate('S', self.qubits, ())
        elif self.name == 'T':
            return Gate('T_DAG', self.qubits, ())
        elif self.name == 'T_DAG':
            return Gate('T', self.qubits, ())
        else:
            raise ValueError(f"Cannot compute dagger for: {self.name}")

    def __repr__(self):
        if self.params:
            return f"Gate({self.name}, {self.qubits}, {self.params})"
        return f"Gate({self.name}, {self.qubits})"


Circuit = List[Gate]


def _apply_gate(rho: np.ndarray, gate: Gate, n_qubits: int) -> np.ndarray:
    """Apply a unitary gate to a density matrix: rho -> U rho U†."""
    d = 2 ** n_qubits
    U = gate.matrix()

    if len(gate.qubits) == 1:
        q = gate.qubits[0]
        full_U = np.eye(1, dtype=complex)
        for i in range(n_qubits):
            full_U = np.kron(full_U, U if i == q else np.eye(2, dtype=complex))
    elif len(gate.qubits) == 2:
        q0, q1 = gate.qubits
        full_U = np.zeros((d, d), dtype=complex)
        for i in range(d):
            bits_in = [(i >> (n_qubits - 1 - k)) & 1 for k in range(n_qubits)]
            for j in range(d):
                bits_out = [(j >> (n_qubits - 1 - k)) & 1
                            for k in range(n_qubits)]
                in_state = bits_in[q0] * 2 + bits_in[q1]
                out_state = bits_out[q0] * 2 + bits_out[q1]
                other_match = all(
                    bits_in[k] == bits_out[k]
                    for k in range(n_qubits) if k not in (q0, q1)
                )
                if other_match:
                    full_U[j, i] = U[out_state, in_state]
    else:
        raise ValueError("Only 1- and 2-qubit gates supported")

    return full_U @ rho @ full_U.conj().T


def _depolarize(rho: np.ndarray, gate: Gate, n_qubits: int,
                noise_level: float) -> np.ndarray:
    """Apply depolarizing noise channel after a gate."""
    d = 2 ** n_qubits
    p = noise_level * len(gate.qubits)
    p = min(p, 1.0)
    if p <= 0:
        return rho
    return (1 - p) * rho + p * np.eye(d, dtype=complex) / d


def simulate(circuit: Circuit, n_qubits: int, noise_level: float = 0.0,
             initial_state: Optional[np.ndarray] = None) -> np.ndarray:
    """Simulate a circuit and return the final density matrix.

    Args:
        circuit: List of Gate objects.
        n_qubits: Number of qubits.
        noise_level: Per-qubit depolarizing noise probability (0 = noiseless).
        initial_state: Optional initial density matrix (defaults to |0...0>).

    Returns:
        The final density matrix as a numpy array.
    """
    d = 2 ** n_qubits
    if initial_state is None:
        rho = np.zeros((d, d), dtype=complex)
        rho[0, 0] = 1.0
    else:
        rho = initial_state.copy()

    for gate in circuit:
        rho = _apply_gate(rho, gate, n_qubits)
        if noise_level > 0:
            rho = _depolarize(rho, gate, n_qubits, noise_level)

    return rho


def expectation_value(rho: np.ndarray, observable: np.ndarray) -> float:
    """Compute Tr(observable @ rho)."""
    return float(np.real(np.trace(observable @ rho)))


def noisy_expectation(circuit: Circuit, n_qubits: int,
                      observable: np.ndarray, noise_level: float) -> float:
    """Shorthand: simulate with noise and compute expectation."""
    rho = simulate(circuit, n_qubits, noise_level=noise_level)
    return expectation_value(rho, observable)


def ideal_expectation(circuit: Circuit, n_qubits: int,
                      observable: np.ndarray) -> float:
    """Shorthand: simulate without noise and compute expectation."""
    return noisy_expectation(circuit, n_qubits, observable, noise_level=0.0)
