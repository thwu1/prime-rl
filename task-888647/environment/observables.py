"""Quantum observables for expectation value computation."""

import numpy as np

I = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.array([[1, 0], [0, -1]], dtype=complex)


def ground_state_projector(n_qubits: int) -> np.ndarray:
    """Projector onto |0...0>."""
    d = 2 ** n_qubits
    proj = np.zeros((d, d), dtype=complex)
    proj[0, 0] = 1.0
    return proj


def z_observable(qubit: int, n_qubits: int) -> np.ndarray:
    """Z on the specified qubit, I on all others."""
    obs = np.eye(1, dtype=complex)
    for i in range(n_qubits):
        obs = np.kron(obs, Z if i == qubit else I)
    return obs


def zz_correlator(q1: int, q2: int, n_qubits: int) -> np.ndarray:
    """Z tensor Z correlator between two qubits."""
    obs = np.eye(1, dtype=complex)
    for i in range(n_qubits):
        obs = np.kron(obs, Z if i in (q1, q2) else I)
    return obs


def total_magnetization(n_qubits: int) -> np.ndarray:
    """Average Z magnetization: (1/n) * sum_i Z_i."""
    d = 2 ** n_qubits
    obs = np.zeros((d, d), dtype=complex)
    for i in range(n_qubits):
        obs += z_observable(i, n_qubits)
    return obs / n_qubits
