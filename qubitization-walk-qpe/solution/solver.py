"""
Complete implementation of the qubitization-based QPE framework.
"""

import numpy as np
import json
import math
from typing import List, Dict, Tuple

# ── Pauli matrices ──────────────────────────────────────────────────────────

_I2 = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)
_PAULI = {"I": _I2, "X": _X, "Y": _Y, "Z": _Z}


def pauli_to_matrix(char: str) -> np.ndarray:
    """Convert a single Pauli character ('I', 'X', 'Y', 'Z') to its 2x2 matrix."""
    return _PAULI[char].copy()


def pauli_string_to_matrix(pauli_str: str) -> np.ndarray:
    """Convert a Pauli string (e.g. 'XXYZI') to its full matrix via tensor product."""
    mat = pauli_to_matrix(pauli_str[0])
    for c in pauli_str[1:]:
        mat = np.kron(mat, pauli_to_matrix(c))
    return mat


# ── Hamiltonian construction ────────────────────────────────────────────────

def build_hamiltonian(terms: List[Dict], n_qubits: int) -> np.ndarray:
    """
    Build dense Hamiltonian matrix from a Pauli decomposition.

    Args:
        terms: list of {"coeff": float, "paulis": str}
        n_qubits: number of qubits
    Returns:
        2^n x 2^n complex Hermitian matrix
    """
    dim = 2 ** n_qubits
    H = np.zeros((dim, dim), dtype=complex)
    for term in terms:
        H += term["coeff"] * pauli_string_to_matrix(term["paulis"])
    return H


# ── LCU decomposition ──────────────────────────────────────────────────────

def lcu_decompose(terms: List[Dict]) -> Tuple[np.ndarray, np.ndarray, float, int, int]:
    """
    LCU decomposition of Hamiltonian terms.

    Returns:
        weights: 1-D array of |coeff_l|, zero-padded to length 2^m_L
        signs:   1-D array of sign(coeff_l), padded with +1
        lambda_val: 1-norm (sum of weights)
        L:       original number of terms
        m_L:     number of ancilla qubits = ceil(log2(L))
    """
    L = len(terms)
    m_L = max(1, math.ceil(math.log2(L))) if L > 1 else 1
    padded = 2 ** m_L

    weights = np.zeros(padded)
    signs = np.ones(padded)
    for i, t in enumerate(terms):
        weights[i] = abs(t["coeff"])
        signs[i] = 1.0 if t["coeff"] >= 0 else -1.0

    lambda_val = float(np.sum(weights))
    return weights, signs, lambda_val, L, m_L


# ── PREPARE oracle ──────────────────────────────────────────────────────────

def build_prepare_unitary(weights: np.ndarray, lambda_val: float) -> np.ndarray:
    """
    Build the PREPARE unitary V such that V|0> = |L>.

    |L> = sum_l sqrt(w_l / lambda) |l>

    Uses a Householder reflection: V = I - 2 v v^dag / ||v||^2
    with v = |0> - |L>.

    Returns:
        2^m_L x 2^m_L unitary matrix
    """
    dim = len(weights)
    target = np.sqrt(weights / lambda_val).astype(complex)  # |L>

    e0 = np.zeros(dim, dtype=complex)
    e0[0] = 1.0

    v = e0 - target
    vnorm2 = np.real(np.dot(v.conj(), v))

    if vnorm2 < 1e-15:
        return np.eye(dim, dtype=complex)

    V = np.eye(dim, dtype=complex) - 2.0 * np.outer(v, v.conj()) / vnorm2
    return V


# ── SELECT oracle ──────────────────────────────────────────────────────────

def build_select_operator(terms: List[Dict], n_qubits: int, m_L: int) -> np.ndarray:
    """
    Build the SELECT operator.

    SELECT = sum_l |l><l| tensor (sign_l * P_l)
    Blocks for padded entries (l >= L) are identity.

    Returns:
        2^(m_L + n_qubits) x 2^(m_L + n_qubits) unitary matrix
    """
    padded = 2 ** m_L
    dim_sys = 2 ** n_qubits
    dim_total = padded * dim_sys

    SELECT = np.zeros((dim_total, dim_total), dtype=complex)

    for l in range(padded):
        if l < len(terms):
            sign = 1.0 if terms[l]["coeff"] >= 0 else -1.0
            block = sign * pauli_string_to_matrix(terms[l]["paulis"])
        else:
            block = np.eye(dim_sys, dtype=complex)

        r = l * dim_sys
        SELECT[r : r + dim_sys, r : r + dim_sys] = block

    return SELECT


# ── Reflection operator ────────────────────────────────────────────────────

def build_reflection_operator(prepare: np.ndarray, n_qubits: int) -> np.ndarray:
    """
    Build the reflection operator R = 2 |L><L| tensor I_sys - I.

    Args:
        prepare: PREPARE unitary V (2^m_L x 2^m_L)
        n_qubits: number of system qubits
    Returns:
        2^(m_L + n_qubits) x 2^(m_L + n_qubits) Hermitian unitary
    """
    dim_anc = prepare.shape[0]
    dim_sys = 2 ** n_qubits
    dim_total = dim_anc * dim_sys

    e0 = np.zeros(dim_anc, dtype=complex)
    e0[0] = 1.0
    L_state = prepare @ e0  # |L> in ancilla space

    # |L><L| tensor I_sys  =  (|L><L|) kron I
    L_proj = np.outer(L_state, L_state.conj())
    projection = np.kron(L_proj, np.eye(dim_sys, dtype=complex))

    return 2.0 * projection - np.eye(dim_total, dtype=complex)


# ── Walk operator ──────────────────────────────────────────────────────────

def build_walk_operator(terms: List[Dict], n_qubits: int) -> Tuple[np.ndarray, float, int]:
    """
    Build the complete walk operator W = R . SELECT.

    Returns:
        walk_op:    unitary walk operator matrix
        lambda_val: LCU 1-norm
        m_L:        number of ancilla qubits
    """
    weights, _, lambda_val, _, m_L = lcu_decompose(terms)
    prepare = build_prepare_unitary(weights, lambda_val)
    select = build_select_operator(terms, n_qubits, m_L)
    reflection = build_reflection_operator(prepare, n_qubits)
    walk = reflection @ select
    return walk, lambda_val, m_L


# ── Energy extraction ──────────────────────────────────────────────────────

def eigenphase_to_energy(phase: float, lambda_val: float) -> float:
    """Convert a walk operator eigenphase to energy: E = lambda * cos(2*pi*phase)."""
    return lambda_val * np.cos(2.0 * np.pi * phase)


# ── QPE simulation ─────────────────────────────────────────────────────────

def simulate_qpe(walk_op: np.ndarray, initial_state: np.ndarray,
                 n_phase: int) -> np.ndarray:
    """
    Simulate quantum phase estimation on the walk operator.

    Uses eigendecomposition of the walk operator and the standard QPE
    probability kernel:

        P(m) = sum_k |c_k|^2  *  sin^2(pi delta N) / (N^2 sin^2(pi delta))

    where delta = theta_k - m/N and c_k are the coefficients of the initial
    state in the eigenbasis.

    Args:
        walk_op:       unitary walk operator
        initial_state: state vector for the walk register (ancilla + system)
        n_phase:       number of phase qubits
    Returns:
        1-D array of probabilities over the 2^n_phase phase-register outcomes
    """
    eigenvalues, eigenvectors = np.linalg.eig(walk_op)
    coeffs = np.linalg.solve(eigenvectors, initial_state)

    N = 2 ** n_phase
    probs = np.zeros(N)

    for m in range(N):
        p = 0.0
        for k in range(len(eigenvalues)):
            ck2 = abs(coeffs[k]) ** 2
            if ck2 < 1e-30:
                continue
            theta_k = np.angle(eigenvalues[k]) / (2.0 * np.pi)
            delta = theta_k - m / N
            # reduce to [-0.5, 0.5) for numerical stability
            delta_r = delta - round(delta)
            if abs(delta_r) < 1e-12:
                amp2 = 1.0
            else:
                amp2 = (np.sin(np.pi * delta_r * N)) ** 2 / (
                    N ** 2 * (np.sin(np.pi * delta_r)) ** 2
                )
            p += ck2 * amp2
        probs[m] = max(0.0, p)

    total = np.sum(probs)
    if total > 0:
        probs /= total
    return probs


# ── Resource estimation ────────────────────────────────────────────────────

def compute_min_phase_bits(ground_energy: float, lambda_val: float,
                           tolerance: float) -> int:
    """
    Minimum phase qubits to resolve the ground energy within tolerance.

    Uses delta_E = lambda * sqrt(1 - (E0/lambda)^2) * 2*pi / 2^m <= tolerance.
    """
    ratio = np.clip(ground_energy / lambda_val, -1.0, 1.0)
    sin_factor = np.sqrt(1.0 - ratio ** 2)

    if sin_factor < 1e-15:
        return 1  # eigenphase exactly representable in binary

    required = lambda_val * sin_factor * 2.0 * np.pi / tolerance
    return max(1, math.ceil(math.log2(max(1.0, required))))


# ── Full analysis pipeline ─────────────────────────────────────────────────

def run_analysis(systems_file: str, output_file: str):
    """Run the full analysis pipeline on all systems and write results to JSON."""
    with open(systems_file) as f:
        systems = json.load(f)

    results = {}
    for sys_name, sys_def in systems.items():
        terms = sys_def["terms"]
        n_qubits = sys_def["n_qubits"]

        # LCU decomposition
        weights, _, lambda_val, L, m_L = lcu_decompose(terms)

        # Exact diagonalisation
        H = build_hamiltonian(terms, n_qubits)
        evals, evecs = np.linalg.eigh(H)
        E0 = float(evals[0])
        psi0 = evecs[:, 0]

        # Walk operator
        walk, _, _ = build_walk_operator(terms, n_qubits)

        # Initial state |L>|psi_0>
        prepare = build_prepare_unitary(weights, lambda_val)
        e0_anc = np.zeros(2 ** m_L, dtype=complex)
        e0_anc[0] = 1.0
        L_state = prepare @ e0_anc
        initial_state = np.kron(L_state, psi0)

        # QPE with 6 phase qubits
        n_phase = 6
        probs = simulate_qpe(walk, initial_state, n_phase)
        best_m = int(np.argmax(probs))
        theta = best_m / 2 ** n_phase
        E_qpe = float(eigenphase_to_energy(theta, lambda_val))

        # Minimum phase bits for 0.01 tolerance
        min_bits = compute_min_phase_bits(E0, lambda_val, 0.01)

        results[sys_name] = {
            "lambda": lambda_val,
            "L": L,
            "m_L": m_L,
            "ground_energy_exact": E0,
            "qpe_ground_energy": E_qpe,
            "n_phase_qubits": n_phase,
            "min_phase_bits": min_bits,
            "hamiltonian_eigenvalues": [float(e) for e in evals],
        }

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_analysis("/app/systems.json", "/app/results.json")
