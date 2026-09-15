"""Quantum gate application engine using bit-manipulation subspace iteration
with C kernel acceleration via ctypes for single-qubit gates."""
import numpy as np
import ctypes
import os

# Load C kernel shared library
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libqsim.so')
_lib = ctypes.CDLL(_lib_path)

_lib.apply_single_qubit_gate.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int
]
_lib.apply_single_qubit_gate.restype = None

_lib.apply_controlled_single_qubit_gate.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_int, ctypes.c_int, ctypes.c_int
]
_lib.apply_controlled_single_qubit_gate.restype = None


def _call_single_gate(state, gate_matrix, target, n_qubits):
    """Apply a 2x2 gate via the C kernel."""
    gate_flat = np.ascontiguousarray(gate_matrix.ravel(), dtype=np.complex128)
    _lib.apply_single_qubit_gate(
        state.ctypes.data, gate_flat.ctypes.data, target, n_qubits
    )


def _call_controlled_single_gate(state, gate_matrix, control, target, n_qubits):
    """Apply a controlled 2x2 gate via the C kernel."""
    gate_flat = np.ascontiguousarray(gate_matrix.ravel(), dtype=np.complex128)
    _lib.apply_controlled_single_qubit_gate(
        state.ctypes.data, gate_flat.ctypes.data, control, target, n_qubits
    )


def _target_offsets(targets):
    """Compute state vector index offsets for all 2^m target qubit configurations."""
    m = len(targets)
    offsets = np.zeros(1 << m, dtype=np.intp)
    for j in range(1 << m):
        for k, t in enumerate(targets):
            if (j >> k) & 1:
                offsets[j] |= (1 << t)
    return offsets


def _complement_indices(n_qubits, fixed_positions):
    """Generate all state indices where non-fixed qubits vary freely and fixed
    qubits are zero."""
    free_positions = sorted(set(range(n_qubits)) - set(fixed_positions))
    n_free = len(free_positions)
    indices = np.zeros(1 << n_free, dtype=np.intp)
    for i in range(1 << n_free):
        idx = 0
        for k, pos in enumerate(free_positions):
            if (i >> k) & 1:
                idx |= (1 << pos)
        indices[i] = idx
    return indices


def apply_gate(state, gate_matrix, targets, n_qubits):
    """Apply a gate matrix to the specified target qubits of a state vector.

    Uses the C kernel for single-qubit gates; falls back to Python subspace
    iteration for multi-qubit gates.
    """
    if gate_matrix.shape == (2, 2) and len(targets) == 1:
        _call_single_gate(state, gate_matrix, targets[0], n_qubits)
        return state

    targets = tuple(sorted(targets))
    offsets = _target_offsets(targets)
    complement = _complement_indices(n_qubits, set(targets))

    for comp_idx in complement:
        indices = comp_idx + offsets
        state[indices] = gate_matrix @ state[indices]

    return state


def apply_controlled_gate(state, gate_matrix, controls, targets, n_qubits):
    """Apply a controlled gate. Uses the C kernel for single-control
    single-target cases; falls back to Python for multi-control or
    multi-target gates."""
    if gate_matrix.shape == (2, 2) and len(targets) == 1 and len(controls) == 1:
        _call_controlled_single_gate(
            state, gate_matrix, controls[0], targets[0], n_qubits
        )
        return state

    targets = tuple(sorted(targets))
    controls = tuple(sorted(controls))
    control_mask = sum(1 << c for c in controls)
    offsets = _target_offsets(targets)

    fixed = set(targets) | set(controls)
    complement = _complement_indices(n_qubits, fixed)

    for comp_idx in complement:
        base = comp_idx | control_mask
        indices = base + offsets
        state[indices] = gate_matrix @ state[indices]

    return state
