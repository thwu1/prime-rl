"""
Quantum circuit simulation engine -- complete implementation.

Uses bit manipulation to build complement-subspace and target-subspace
index arrays, then applies gate matrices via vectorised NumPy operations.

"""
import numpy as np


def _build_indices(qubits):
    """Return an array of all index patterns formed by toggling *qubits*.

    Starting from [0], for each qubit q the array is doubled by appending
    copies with bit q set.  The result has 2**len(qubits) entries.
    """
    indices = np.array([0], dtype=np.intp)
    for q in qubits:
        indices = np.concatenate([indices, indices | (1 << q)])
    return indices


def apply_gate(state, matrix, targets):
    """Apply a k-qubit gate to the specified target qubits (in-place)."""
    n_qubits = int(np.log2(len(state)))
    targets = tuple(targets)

    complement_qubits = sorted(set(range(n_qubits)) - set(targets))

    # Complement-subspace base indices (target bits all zero)
    comp_indices = _build_indices(complement_qubits)

    # Target-subspace offsets (one per matrix row/column)
    targ_offsets = _build_indices(targets)

    # Full index grid: shape (n_complement_states, n_target_states)
    all_idx = comp_indices[:, np.newaxis] + targ_offsets[np.newaxis, :]

    # Vectorised gate application
    sub = state[all_idx]                      # (M, K)
    state[all_idx] = sub @ matrix.T           # each row multiplied by gate
    return state


def apply_controlled_gate(state, matrix, controls, targets):
    """Apply a gate conditioned on all *controls* being |1>."""
    n_qubits = int(np.log2(len(state)))
    controls = tuple(controls)
    targets = tuple(targets)

    used = set(controls) | set(targets)
    complement_qubits = sorted(set(range(n_qubits)) - used)

    # Base offset: all control bits set to 1
    control_mask = 0
    for c in controls:
        control_mask |= 1 << c

    comp_indices = _build_indices(complement_qubits)
    comp_indices += control_mask

    targ_offsets = _build_indices(targets)

    all_idx = comp_indices[:, np.newaxis] + targ_offsets[np.newaxis, :]

    sub = state[all_idx]
    state[all_idx] = sub @ matrix.T
    return state


def simulate(circuit, params=None):
    """Run a circuit from |0...0> and return the final state vector."""
    n = circuit.n_qubits
    state = np.zeros(1 << n, dtype=complex)
    state[0] = 1.0

    for op in circuit.operations:
        op_type = op["type"]
        if op_type == "fixed":
            apply_gate(state, op["matrix"], op["targets"])
        elif op_type == "parameterized":
            mat = op["gate_fn"](params[op["param_idx"]])
            apply_gate(state, mat, op["targets"])
        elif op_type == "controlled":
            apply_controlled_gate(state, op["matrix"], op["controls"], op["targets"])

    return state
