"""
Gradient computation for parameterized quantum circuits.

"""
import numpy as np


def expectation_value(state, obs_matrix, obs_qubits):
    """
    Compute <state|O|state> for observable O on given qubits.

    Args:
        state: complex128 array of shape (2**n,).
        obs_matrix: Hermitian matrix for the observable.
        obs_qubits: tuple of qubit indices the observable acts on.

    Returns:
        Real-valued expectation value.
    """
    raise NotImplementedError


def compute_gradient(circuit, params, obs_matrix, obs_qubits):
    """
    Compute exact gradient of E(theta) = <psi(theta)|O|psi(theta)>
    with respect to all circuit parameters theta.

    Args:
        circuit: Circuit object.
        params: float array of parameter values.
        obs_matrix: Hermitian observable matrix.
        obs_qubits: tuple of qubits the observable acts on.

    Returns:
        Real-valued gradient array of shape (n_params,).
    """
    raise NotImplementedError
