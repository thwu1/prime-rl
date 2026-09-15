"""
Gradient computation -- complete implementation.

"""
import numpy as np

from qcsim.engine import apply_gate, apply_controlled_gate


def expectation_value(state, obs_matrix, obs_qubits):
    """Compute <state|O|state> for observable O on given qubits."""
    temp = state.copy()
    apply_gate(temp, obs_matrix, obs_qubits)
    return float(np.real(np.vdot(state, temp)))


def compute_gradient(circuit, params, obs_matrix, obs_qubits):
    """Gradient of the expectation value via reverse-mode accumulation."""
    n = circuit.n_qubits
    n_params = circuit.n_params
    grad = np.zeros(n_params)
    ops = circuit.operations

    # forward pass: cache every intermediate state
    state = np.zeros(1 << n, dtype=complex)
    state[0] = 1.0
    states = [state.copy()]

    for op in ops:
        op_type = op["type"]
        if op_type == "fixed":
            apply_gate(state, op["matrix"], op["targets"])
        elif op_type == "parameterized":
            mat = op["gate_fn"](params[op["param_idx"]])
            apply_gate(state, mat, op["targets"])
        elif op_type == "controlled":
            apply_controlled_gate(state, op["matrix"], op["controls"], op["targets"])
        states.append(state.copy())

    # initialise bra: lambda = O |psi>
    lam = states[-1].copy()
    apply_gate(lam, obs_matrix, obs_qubits)

    # backward pass
    for k in range(len(ops) - 1, -1, -1):
        op = ops[k]
        op_type = op["type"]

        if op_type == "parameterized":
            pidx = op["param_idx"]
            dmat = op["deriv_fn"](params[pidx])
            phi = states[k].copy()
            apply_gate(phi, dmat, op["targets"])
            grad[pidx] += 2.0 * np.real(np.vdot(lam, phi))

        if op_type == "fixed":
            apply_gate(lam, op["matrix"].conj().T, op["targets"])
        elif op_type == "parameterized":
            mat = op["gate_fn"](params[op["param_idx"]])
            apply_gate(lam, mat.conj().T, op["targets"])
        elif op_type == "controlled":
            apply_controlled_gate(
                lam, op["matrix"].conj().T, op["controls"], op["targets"]
            )

    return grad
