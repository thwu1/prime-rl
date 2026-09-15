"""Quantum simulation utilities for ZNE shot allocation benchmarks.

Provides statevector-based quantum simulation with configurable
global depolarizing noise for benchmarking shot allocation strategies.

Noise model:
  For a circuit with `depth` noisy layers and per-layer depolarizing
  rate `noise_rate`, a Pauli observable P has noisy expectation:

      <P>_noisy(lambda) = (1 - noise_rate)^(lambda * depth) * <P>_ideal

  where lambda is the ZNE scale factor (>= 1). This models the global
  depolarizing channel D_alpha: rho -> alpha*rho + (1-alpha)*I/d
  with alpha = (1 - noise_rate)^(lambda * depth).
"""

import numpy as np
from typing import List, Optional


PAULI = {
    "I": np.eye(2, dtype=complex),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
}

# Basis rotations for Pauli measurements
_H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
_Y_ROT = np.array([[1, -1j], [1, 1j]], dtype=complex) / np.sqrt(2)  # HS-dagger


def pauli_matrix(pauli_str: str) -> np.ndarray:
    """Tensor product matrix for a Pauli string like 'XZIY'."""
    mat = PAULI[pauli_str[0]]
    for c in pauli_str[1:]:
        mat = np.kron(mat, PAULI[c])
    return mat


def exact_expectation(state: np.ndarray, pauli_str: str) -> float:
    """Exact expectation value <psi|P|psi> for a Pauli string P."""
    P = pauli_matrix(pauli_str)
    return float(np.real(state.conj() @ P @ state))


def noisy_expectation(
    state: np.ndarray,
    pauli_str: str,
    noise_rate: float,
    depth: int,
    scale_factor: float,
) -> float:
    """Expectation under global depolarizing noise."""
    ideal = exact_expectation(state, pauli_str)
    return (1 - noise_rate) ** (scale_factor * depth) * ideal


def sample_commuting_group(
    state: np.ndarray,
    paulis: List[str],
    noise_rate: float,
    depth: int,
    scale_factor: float,
    num_shots: int,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Sample joint +/-1 outcomes for qubitwise-commuting Pauli observables.

    Models global depolarizing noise on the joint measurement distribution.
    For qubitwise-commuting observables, the measurement can be performed
    in a single basis (determined per-qubit by the non-identity operators).
    The joint outcomes are correlated.

    Args:
        state: Complex state vector of length 2^n.
        paulis: List of qubitwise-commuting Pauli strings.
        noise_rate: Per-layer depolarizing rate in [0, 0.5).
        depth: Number of noisy circuit layers.
        scale_factor: ZNE noise amplification factor (>= 1).
        num_shots: Number of measurement shots.
        rng: Optional numpy random generator.

    Returns:
        Array of shape (num_shots, len(paulis)) with +/-1 outcomes.
    """
    if rng is None:
        rng = np.random.default_rng()

    n_qubits = len(paulis[0])
    n_terms = len(paulis)

    # Determine the measurement basis for each qubit
    meas_basis = ["I"] * n_qubits
    for ps in paulis:
        for q, p in enumerate(ps):
            if p != "I":
                meas_basis[q] = p

    # Build the tensor-product basis rotation
    rotation = np.array([1.0], dtype=complex)
    for q in range(n_qubits):
        if meas_basis[q] == "X":
            rotation = np.kron(rotation, _H_GATE)
        elif meas_basis[q] == "Y":
            rotation = np.kron(rotation, _Y_ROT)
        else:
            rotation = np.kron(rotation, np.eye(2, dtype=complex))

    # Compute noisy measurement probabilities
    rotated = rotation @ state
    ideal_probs = np.abs(rotated) ** 2

    alpha = (1 - noise_rate) ** (scale_factor * depth)
    n_states = 2**n_qubits
    noisy_probs = alpha * ideal_probs + (1 - alpha) / n_states
    noisy_probs = np.clip(noisy_probs, 0, None)
    noisy_probs /= noisy_probs.sum()

    # Sample computational basis states
    basis_states = rng.choice(n_states, size=num_shots, p=noisy_probs)

    # Convert to +/-1 outcomes per Pauli string
    results = np.ones((num_shots, n_terms), dtype=float)
    for t, ps in enumerate(paulis):
        for q, p in enumerate(ps):
            if p != "I":
                bit = (basis_states >> (n_qubits - 1 - q)) & 1
                results[:, t] *= 1 - 2 * bit

    return results


def create_product_state(angles: List[float]) -> np.ndarray:
    """Product state |psi> = tensor_i Ry(theta_i)|0>."""
    state = np.array([1.0], dtype=complex)
    for theta in angles:
        qubit = np.array([np.cos(theta / 2), np.sin(theta / 2)], dtype=complex)
        state = np.kron(state, qubit)
    return state


def create_uniform_superposition(n_qubits: int) -> np.ndarray:
    """Uniform superposition |+>^n."""
    dim = 2**n_qubits
    return np.ones(dim, dtype=complex) / np.sqrt(dim)
