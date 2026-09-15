"""Gradient computation for parameterized quantum circuits.

Computes gradients of expectation values <psi|O|psi> with respect to
circuit parameters using a single forward and backward pass through
the circuit.
"""
import numpy as np
from .engine import apply_gate, apply_controlled_gate


def compute_gradients(circuit, observable, params):
    """Compute gradients of <psi|O|psi> w.r.t. params.

    Parameters
    ----------
    circuit : ParameterizedCircuit
    observable : ndarray, shape (2^n, 2^n), Hermitian
    params : array-like of float

    Returns
    -------
    grads : ndarray of shape (n_params,)
    """
    n = circuit.n_qubits
    dim = 1 << n
    params = np.asarray(params, dtype=float)
    ops = circuit.operations
    num_ops = len(ops)

    # --- Forward pass: save every intermediate state ---
    state = np.zeros(dim, dtype=complex)
    state[0] = 1.0
    states = [state.copy()]

    for op in ops:
        state = state.copy()
        if op['type'] == 'fixed':
            matrix = op['gate_matrix']
        else:
            matrix = op['gate_func'](params[op['param_index']])

        if op['controls'] is not None:
            apply_controlled_gate(state, matrix, op['controls'], op['targets'], n)
        else:
            apply_gate(state, matrix, op['targets'], n)
        states.append(state.copy())

    # --- Initialise adjoint state ---
    chi = observable @ states[num_ops]

    # --- Backward pass ---
    grads = np.zeros(circuit.n_params)
    all_idx = np.arange(dim)

    for l in range(num_ops - 1, -1, -1):
        op = ops[l]

        # Gradient contribution from parameterized gates
        if op['type'] == 'parameterized':
            deriv_matrix = op['gate_deriv'](params[op['param_index']])
            temp = states[l].copy()

            if op['controls'] is not None:
                control_mask = sum(1 << c for c in op['controls'])
                temp[(all_idx & control_mask) != control_mask] = 0.0
                apply_gate(temp, deriv_matrix, op['targets'], n)
            else:
                apply_gate(temp, deriv_matrix, op['targets'], n)

            grads[op['param_index']] += 2.0 * np.real(np.vdot(chi, temp))

        # Propagate adjoint state: chi <- U_l^dagger chi
        if op['type'] == 'fixed':
            matrix = op['gate_matrix']
        else:
            matrix = op['gate_func'](params[op['param_index']])

        adj_matrix = matrix.conj().T
        if op['controls'] is not None:
            apply_controlled_gate(chi, adj_matrix, op['controls'], op['targets'], n)
        else:
            apply_gate(chi, adj_matrix, op['targets'], n)

    return grads
