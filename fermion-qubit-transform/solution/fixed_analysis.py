"""Spectral analysis and Hamiltonian reduction (fixed)."""

import numpy as np
from itertools import product as iter_product

PAULI = {
    "I": np.eye(2, dtype=complex),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
}


def _pauli_string_to_matrix(pstr):
    """Convert a Pauli string to its matrix representation."""
    result = np.array([[1.0 + 0j]])
    for ch in pstr:
        result = np.kron(result, PAULI[ch])
    return result


def diagonalize(hamiltonian_dict, n_qubits):
    """Exact diagonalization of a qubit Hamiltonian.

    Args:
        hamiltonian_dict: {pauli_string: coefficient}
        n_qubits: number of qubits

    Returns:
        Sorted array of real eigenvalues
    """
    dim = 2 ** n_qubits
    matrix = np.zeros((dim, dim), dtype=complex)

    for pstr, coeff in hamiltonian_dict.items():
        if abs(coeff) < 1e-14:
            continue
        op = np.array([[1.0 + 0j]])
        for ch in pstr:
            op = np.kron(op, PAULI[ch])
        matrix += coeff * op

    eigenvalues = np.sort(np.real(np.linalg.eigvalsh(matrix)))
    return eigenvalues


# =============================================================================
# Z2 symmetry detection via symplectic representation
# =============================================================================

def _pauli_to_symplectic(pstr):
    """Convert Pauli string to symplectic vector."""
    n = len(pstr)
    vec = np.zeros(2 * n, dtype=int)
    for i, ch in enumerate(pstr):
        if ch == "X":
            vec[i] = 1
        elif ch == "Y":
            vec[i] = 1
            vec[n + i] = 1
        elif ch == "Z":
            vec[n + i] = 1
    return vec


def _symplectic_to_pauli(vec):
    """Convert symplectic vector back to Pauli string."""
    n = len(vec) // 2
    chars = []
    for i in range(n):
        x, z = vec[i], vec[n + i]
        if x == 0 and z == 0:
            chars.append("I")
        elif x == 1 and z == 0:
            chars.append("X")
        elif x == 1 and z == 1:
            chars.append("Y")
        else:
            chars.append("Z")
    return "".join(chars)


def _commutes(pstr1, pstr2):
    """Check if two Pauli strings commute."""
    anti_count = sum(
        1 for c1, c2 in zip(pstr1, pstr2)
        if c1 != "I" and c2 != "I" and c1 != c2
    )
    return anti_count % 2 == 0


def _gf2_nullspace(matrix):
    """Compute the null space of a binary matrix over GF(2)."""
    if matrix.shape[0] == 0:
        return []
    m, n = matrix.shape
    aug = matrix.copy() % 2
    pivot_cols = []
    row = 0

    for col in range(n):
        found = False
        for r in range(row, m):
            if aug[r, col] % 2 == 1:
                aug[[row, r]] = aug[[r, row]]
                found = True
                break
        if not found:
            continue
        pivot_cols.append(col)
        for r in range(m):
            if r != row and aug[r, col] % 2 == 1:
                aug[r] = (aug[r] + aug[row]) % 2
        row += 1

    free_cols = [c for c in range(n) if c not in pivot_cols]
    null_vecs = []
    for fc in free_cols:
        vec = np.zeros(n, dtype=int)
        vec[fc] = 1
        for i, pc in enumerate(pivot_cols):
            vec[pc] = int(aug[i, fc]) % 2
        null_vecs.append(vec)
    return null_vecs


def _find_z2_symmetries(hamiltonian_dict, n_qubits):
    """Find independent Z2 symmetry operators of a qubit Hamiltonian.

    Symmetries are Pauli strings that commute with every term in the
    Hamiltonian. Found by computing the GF(2) null space of the
    symplectic commutation constraint matrix.
    """
    identity = "I" * n_qubits
    terms = [pstr for pstr, coeff in hamiltonian_dict.items()
             if abs(coeff) > 1e-10 and pstr != identity]
    if not terms:
        return []

    n = n_qubits
    rows = []
    seen = set()
    for pstr in terms:
        svec = _pauli_to_symplectic(pstr)
        # Symplectic inner product constraint: swap x and z parts
        constraint = np.concatenate([svec[n:], svec[:n]])
        key = tuple(constraint)
        if key not in seen and any(constraint):
            seen.add(key)
            rows.append(constraint)

    if not rows:
        return []

    mat = np.array(rows, dtype=int)
    null_vecs = _gf2_nullspace(mat)

    symmetries = []
    for vec in null_vecs:
        pstr = _symplectic_to_pauli(vec)
        if pstr != identity:
            symmetries.append(pstr)

    # Select mutually commuting subset
    selected = []
    for sym in symmetries:
        if all(_commutes(sym, s) for s in selected):
            selected.append(sym)

    return selected


# =============================================================================
# Qubit tapering via projector-based subspace restriction
# =============================================================================

def find_symmetry_reduction(hamiltonian_dict, n_qubits):
    """Find Z2 symmetries and taper qubits by projecting into symmetry sectors.

    Returns:
        dict with keys: n_symmetries, reduced_n_qubits, reduced_ground_energy
    """
    symmetries = _find_z2_symmetries(hamiltonian_dict, n_qubits)
    n_sym = len(symmetries)

    # Build full Hamiltonian matrix
    dim = 2 ** n_qubits
    ham_matrix = np.zeros((dim, dim), dtype=complex)
    for pstr, coeff in hamiltonian_dict.items():
        if abs(coeff) < 1e-14:
            continue
        ham_matrix += coeff * _pauli_string_to_matrix(pstr)

    if n_sym == 0:
        eigs = np.real(np.linalg.eigvalsh(ham_matrix))
        return {
            "n_symmetries": 0,
            "reduced_n_qubits": n_qubits,
            "reduced_ground_energy": float(np.min(eigs)),
        }

    sym_matrices = [_pauli_string_to_matrix(sym) for sym in symmetries]

    # Search all symmetry sectors for the minimum energy
    best_energy = float("inf")

    for sector in iter_product([1, -1], repeat=n_sym):
        # Build projector for this sector
        projector = np.eye(dim, dtype=complex)
        for k in range(n_sym):
            projector = projector @ (np.eye(dim) + sector[k] * sym_matrices[k]) / 2.0

        # Find active subspace
        p_eigvals, p_eigvecs = np.linalg.eigh(projector)
        active_mask = p_eigvals > 0.5
        active_vecs = p_eigvecs[:, active_mask]

        if active_vecs.shape[1] == 0:
            continue

        # Restrict Hamiltonian to this sector
        H_restricted = active_vecs.conj().T @ ham_matrix @ active_vecs
        restricted_eigs = np.real(np.linalg.eigvalsh(H_restricted))

        min_e = float(np.min(restricted_eigs))
        if min_e < best_energy:
            best_energy = min_e

    return {
        "n_symmetries": n_sym,
        "reduced_n_qubits": n_qubits - n_sym,
        "reduced_ground_energy": best_energy,
    }
