"""
Quantum circuit simulation engine.

"""
import numpy as np


def apply_gate(state, matrix, targets):
    """
    Apply a k-qubit gate matrix to the specified target qubits.
    Must not construct the full 2^n x 2^n unitary.

    Args:
        state: complex128 array of shape (2**n,), modified in-place.
        matrix: complex128 array of shape (2**k, 2**k).
        targets: tuple of k target qubit indices (0-based).

    Returns:
        The modified state array.
    """
    raise NotImplementedError


def apply_controlled_gate(state, matrix, controls, targets):
    """
    Apply a gate only when every control qubit is |1>.

    Args:
        state: complex128 array of shape (2**n,), modified in-place.
        matrix: complex128 array of shape (2**k, 2**k).
        controls: tuple of control qubit indices.
        targets: tuple of target qubit indices.

    Returns:
        The modified state array.
    """
    raise NotImplementedError


def simulate(circuit, params=None):
    """
    Simulate a circuit starting from |0...0>.

    Args:
        circuit: Circuit object with .n_qubits and .operations.
        params: optional float array of parameter values.

    Returns:
        Final state vector as complex128 array of shape (2**n,).
    """
    raise NotImplementedError
