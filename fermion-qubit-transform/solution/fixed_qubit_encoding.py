"""Fermion-to-qubit encoding implementations (fixed)."""

import numpy as np
from itertools import product as iter_product

# Pauli matrices
_I = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)

PAULI = {"I": _I, "X": _X, "Y": _Y, "Z": _Z}
PAULI_LIST = [_I, _X, _Y, _Z]
PAULI_LABELS = "IXYZ"

# Single-qubit Pauli multiplication table: (phase, result)
PAULI_MULT = {
    ("I", "I"): (1, "I"), ("I", "X"): (1, "X"),
    ("I", "Y"): (1, "Y"), ("I", "Z"): (1, "Z"),
    ("X", "I"): (1, "X"), ("X", "X"): (1, "I"),
    ("X", "Y"): (1j, "Z"), ("X", "Z"): (-1j, "Y"),
    ("Y", "I"): (1, "Y"), ("Y", "X"): (-1j, "Z"),
    ("Y", "Y"): (1, "I"), ("Y", "Z"): (1j, "X"),
    ("Z", "I"): (1, "Z"), ("Z", "X"): (1j, "Y"),
    ("Z", "Y"): (-1j, "X"), ("Z", "Z"): (1, "I"),
}


def _multiply_ops(op1, op2):
    """Multiply two Pauli operator dictionaries."""
    result = {}
    for p1, c1 in op1.items():
        for p2, c2 in op2.items():
            phase = c1 * c2
            chars = []
            for a, b in zip(p1, p2):
                ph, ch = PAULI_MULT[(a, b)]
                phase *= ph
                chars.append(ch)
            pstr = "".join(chars)
            result[pstr] = result.get(pstr, 0) + phase
    return {k: v for k, v in result.items() if abs(v) > 1e-14}


def _creation(p, n_qubits):
    """Ladder operator: excitation at site p with parity string."""
    terms = {}
    pstr_x = list("I" * n_qubits)
    pstr_y = list("I" * n_qubits)

    # Parity string for anticommutation: Z on qubits 0..p-1
    for j in range(p):
        pstr_x[j] = "Z"
        pstr_y[j] = "Z"

    pstr_x[p] = "X"
    pstr_y[p] = "Y"

    terms["".join(pstr_x)] = 0.5
    terms["".join(pstr_y)] = -0.5j
    return terms


def _annihilation(p, n_qubits):
    """Ladder operator: de-excitation at site p with parity string."""
    terms = {}
    pstr_x = list("I" * n_qubits)
    pstr_y = list("I" * n_qubits)

    for j in range(p):
        pstr_x[j] = "Z"
        pstr_y[j] = "Z"

    pstr_x[p] = "X"
    pstr_y[p] = "Y"

    terms["".join(pstr_x)] = 0.5
    terms["".join(pstr_y)] = 0.5j
    return terms


def primary_encoding(h_spin, g_spin, nuclear_repulsion, n_qubits):
    """Jordan-Wigner encoding of fermionic Hamiltonian to qubit Hamiltonian."""
    hamiltonian = {}

    # Nuclear repulsion (identity term)
    identity = "I" * n_qubits
    hamiltonian[identity] = nuclear_repulsion

    # One-body terms: h[p,q] * a_dag_p a_q
    for p in range(n_qubits):
        for q in range(n_qubits):
            if abs(h_spin[p, q]) < 1e-12:
                continue
            terms = _creation(p, n_qubits)
            terms = _multiply_ops(terms, _annihilation(q, n_qubits))
            for pstr, c in terms.items():
                if abs(c) > 1e-14:
                    hamiltonian[pstr] = hamiltonian.get(pstr, 0) + h_spin[p, q] * c

    # Two-body terms: 0.5 * g[p,q,r,s] * a_dag_p a_dag_q a_s a_r
    for p in range(n_qubits):
        for q in range(n_qubits):
            for r in range(n_qubits):
                for s in range(n_qubits):
                    coeff = 0.5 * g_spin[p, q, r, s]
                    if abs(coeff) < 1e-12:
                        continue
                    term = _creation(p, n_qubits)
                    term = _multiply_ops(term, _creation(q, n_qubits))
                    term = _multiply_ops(term, _annihilation(s, n_qubits))
                    term = _multiply_ops(term, _annihilation(r, n_qubits))
                    for pstr, c in term.items():
                        if abs(c) > 1e-14:
                            hamiltonian[pstr] = hamiltonian.get(pstr, 0) + coeff * c

    # Clean: remove negligible terms, take real part where imaginary is noise
    cleaned = {}
    for k, v in hamiltonian.items():
        if abs(v) > 1e-10:
            cleaned[k] = v.real if abs(v.imag) < 1e-10 else v
    return cleaned


# =============================================================================
# Bravyi-Kitaev encoding
# =============================================================================

def _pauli_string_to_matrix(pstr):
    """Convert a Pauli string to its matrix representation."""
    result = np.array([[1.0 + 0j]])
    for ch in pstr:
        result = np.kron(result, PAULI[ch])
    return result


def _hamiltonian_to_matrix(ham_dict, n_qubits):
    """Convert Pauli dict to full matrix."""
    dim = 2 ** n_qubits
    matrix = np.zeros((dim, dim), dtype=complex)
    for pstr, coeff in ham_dict.items():
        if abs(coeff) < 1e-14:
            continue
        matrix += coeff * _pauli_string_to_matrix(pstr)
    return matrix


def _matrix_to_pauli_dict(matrix, n_qubits, tol=1e-10):
    """Decompose a matrix into Pauli string coefficients."""
    dim = 2 ** n_qubits
    result = {}
    for indices in iter_product(range(4), repeat=n_qubits):
        trace_val = 0.0 + 0j
        for j in range(dim):
            phase = 1.0 + 0j
            i_val = 0
            for k in range(n_qubits):
                jk = (j >> k) & 1
                p = PAULI_LIST[indices[k]]
                if abs(p[0, jk]) > 0.5:
                    ik = 0
                    phase *= p[0, jk]
                else:
                    ik = 1
                    phase *= p[1, jk]
                i_val |= (ik << k)
            trace_val += phase * matrix[i_val, j]
        coeff = trace_val / dim
        if abs(coeff) > tol:
            pstr = "".join(PAULI_LABELS[idx] for idx in indices)
            result[pstr] = complex(coeff)
    return result


def _build_bk_matrix(n):
    """Build the Bravyi-Kitaev beta matrix (binary indexed tree structure)."""
    beta = np.zeros((n, n), dtype=int)
    for i in range(n):
        k = i + 1
        lowbit = k & (-k)
        start = k - lowbit
        for j in range(start, k):
            beta[i][j] = 1
    return beta


def _build_bk_basis_change(n):
    """Build the BK basis change unitary from the beta matrix."""
    beta = _build_bk_matrix(n)
    dim = 2 ** n
    V = np.zeros((dim, dim), dtype=float)
    for f_int in range(dim):
        f_bits = np.array([(f_int >> k) & 1 for k in range(n)], dtype=int)
        b_bits = beta @ f_bits % 2
        b_int = sum(int(b_bits[k]) * (1 << k) for k in range(n))
        V[b_int, f_int] = 1.0
    return V


def secondary_encoding(h_spin, g_spin, nuclear_repulsion, n_qubits):
    """Bravyi-Kitaev encoding via basis change of Jordan-Wigner Hamiltonian.

    Computes the JW Hamiltonian, applies the BK basis change matrix,
    and decomposes the result back into Pauli terms.
    """
    # First compute JW Hamiltonian
    jw_ham = primary_encoding(h_spin, g_spin, nuclear_repulsion, n_qubits)

    # Convert to matrix, apply BK basis change
    H_JW = _hamiltonian_to_matrix(jw_ham, n_qubits)
    V = _build_bk_basis_change(n_qubits)
    H_BK = V @ H_JW @ V.T

    # Decompose back to Pauli dict
    bk_ham = _matrix_to_pauli_dict(H_BK, n_qubits)

    # Clean
    cleaned = {}
    for k, v in bk_ham.items():
        if abs(v) > 1e-10:
            cleaned[k] = v.real if abs(v.imag) < 1e-10 else v
    return cleaned
