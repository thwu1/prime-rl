"""Quantum gate definitions for the circuit optimizer framework.

Provides matrix representations for standard quantum gates and helper
functions for gate classification.
"""

import numpy as np
from typing import List

SINGLE_QUBIT_GATES = frozenset({
    'I', 'H', 'X', 'Y', 'Z', 'S', 'Sdg', 'T', 'Tdg', 'Rx', 'Ry', 'Rz',
})
TWO_QUBIT_GATES = frozenset({'CNOT', 'CZ', 'SWAP'})


def gate_matrix(name: str, params: List[float] = None) -> np.ndarray:
    """Return the unitary matrix for a named gate.

    Parameters
    ----------
    name : str
        Gate name (e.g. 'H', 'CNOT', 'Rz').
    params : list of float, optional
        Gate parameters (rotation angles, etc.).

    Returns
    -------
    np.ndarray
        The unitary matrix.
    """
    if params is None:
        params = []

    if name == 'I':
        return np.eye(2, dtype=complex)
    elif name == 'H':
        return np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    elif name == 'X':
        return np.array([[0, 1], [1, 0]], dtype=complex)
    elif name == 'Y':
        return np.array([[0, -1j], [1j, 0]], dtype=complex)
    elif name == 'Z':
        return np.array([[1, 0], [0, -1]], dtype=complex)
    elif name == 'S':
        return np.array([[1, 0], [0, 1j]], dtype=complex)
    elif name == 'Sdg':
        return np.array([[1, 0], [0, -1j]], dtype=complex)
    elif name == 'T':
        return np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex)
    elif name == 'Tdg':
        return np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=complex)
    elif name == 'Rx':
        theta = params[0]
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)
    elif name == 'Ry':
        theta = params[0]
        c, s = np.cos(theta / 2), np.sin(theta / 2)
        return np.array([[c, -s], [s, c]], dtype=complex)
    elif name == 'Rz':
        theta = params[0]
        return np.array([
            [np.exp(-1j * theta / 2), 0],
            [0, np.exp(1j * theta / 2)]
        ], dtype=complex)
    elif name == 'CNOT':
        return np.array([
            [1, 0, 0, 0], [0, 1, 0, 0],
            [0, 0, 0, 1], [0, 0, 1, 0]
        ], dtype=complex)
    elif name == 'CZ':
        return np.array([
            [1, 0, 0, 0], [0, 1, 0, 0],
            [0, 0, 1, 0], [0, 0, 0, -1]
        ], dtype=complex)
    elif name == 'SWAP':
        return np.array([
            [1, 0, 0, 0], [0, 0, 1, 0],
            [0, 1, 0, 0], [0, 0, 0, 1]
        ], dtype=complex)
    else:
        raise ValueError(f"Unknown gate: {name}")


def gate_num_qubits(name: str) -> int:
    """Return the number of qubits a named gate acts on."""
    if name in TWO_QUBIT_GATES:
        return 2
    return 1


def is_single_qubit(name: str) -> bool:
    """Return True if the gate is a single-qubit gate."""
    return name in SINGLE_QUBIT_GATES
