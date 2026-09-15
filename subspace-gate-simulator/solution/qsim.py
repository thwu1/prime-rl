
"""
Quantum circuit simulator using bit-mask subspace iteration.

Implements the core algorithm: for each gate, iterate over all configurations
of non-target qubits, extract the sub-vector at the target qubit subspace,
multiply by the gate matrix, and write back.
"""

import numpy as np
import cmath


def apply_gate(state, matrix, target_qubits):
    """
    Apply a unitary gate to specified target qubits using subspace iteration.

    Args:
        state: numpy 1D complex array of length 2^n (modified in-place)
        matrix: numpy 2D complex array of shape (2^k, 2^k)
        target_qubits: list of k qubit indices the gate acts on

    Returns:
        The modified state array.
    """
    n_qubits = int(np.log2(len(state)))
    k = len(target_qubits)
    other_qubits = sorted(q for q in range(n_qubits) if q not in target_qubits)
    n_other = len(other_qubits)

    # Precompute complement offsets: one per target-qubit combination
    offsets = _complement_offsets(target_qubits)

    # Iterate over every configuration of the non-target qubits
    for sub_idx in range(1 << n_other):
        # Map sub_idx bits to the non-target qubit positions
        base = 0
        for bit_pos, qubit in enumerate(other_qubits):
            if sub_idx & (1 << bit_pos):
                base |= (1 << qubit)

        # Gather the 2^k indices in the target subspace
        indices = [base | off for off in offsets]

        # Extract, multiply, scatter
        sub_vec = state[indices].copy()
        state[indices] = matrix @ sub_vec

    return state


def apply_controlled_gate(state, matrix, target_qubits, control_qubits,
                          control_values):
    """
    Apply a controlled gate using subspace iteration.

    The gate matrix is applied to the target qubits only when each control
    qubit matches its corresponding value in control_values (0 or 1).

    Args:
        state: numpy 1D complex array of length 2^n (modified in-place)
        matrix: numpy 2D complex array of shape (2^k, 2^k)
        target_qubits: list of k target qubit indices
        control_qubits: list of m control qubit indices
        control_values: list of m values (0 or 1) for each control

    Returns:
        The modified state array.
    """
    n_qubits = int(np.log2(len(state)))
    k = len(target_qubits)

    # All qubits that are "fixed" (not iterated freely)
    all_fixed = sorted(set(list(target_qubits) + list(control_qubits)))
    other_qubits = sorted(q for q in range(n_qubits) if q not in all_fixed)
    n_other = len(other_qubits)

    # Control offset: pre-set bits for control qubits with value 1
    ctrl_offset = 0
    for q, v in zip(control_qubits, control_values):
        if v == 1:
            ctrl_offset |= (1 << q)

    # Complement offsets for target qubits only
    offsets = _complement_offsets(target_qubits)

    for sub_idx in range(1 << n_other):
        base = ctrl_offset
        for bit_pos, qubit in enumerate(other_qubits):
            if sub_idx & (1 << bit_pos):
                base |= (1 << qubit)

        indices = [base | off for off in offsets]
        sub_vec = state[indices].copy()
        state[indices] = matrix @ sub_vec

    return state


def _complement_offsets(target_qubits):
    """
    Compute the 2^k offsets for all combinations of target qubit bits.

    For target qubits [q0, q1, ...], offset j has bit q_b set iff
    bit b of j is 1. This maps matrix column/row j to the corresponding
    full-space bit pattern.
    """
    k = len(target_qubits)
    offsets = []
    for j in range(1 << k):
        off = 0
        for b in range(k):
            if j & (1 << b):
                off |= (1 << target_qubits[b])
        offsets.append(off)
    return offsets
