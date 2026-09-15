"""Fermion-to-qubit encoding implementations."""
import numpy as np

# Pauli matrices
_I = np.eye(2, dtype=complex)
_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
_Z = np.array([[1, 0], [0, -1]], dtype=complex)

PAULI = {"I": _I, "X": _X, "Y": _Y, "Z": _Z}

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

    # Parity string for anticommutation
    for j in range(1, p):
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

    for j in range(1, p):
        pstr_x[j] = "Z"
        pstr_y[j] = "Z"

    pstr_x[p] = "X"
    pstr_y[p] = "Y"

    terms["".join(pstr_x)] = 0.5
    terms["".join(pstr_y)] = 0.5j
    return terms


def primary_encoding(h_spin, g_spin, nuclear_repulsion, n_qubits):
    """Encode fermionic Hamiltonian to qubit Hamiltonian.

    Maps each fermionic ladder operator to a product of Pauli
    operators using parity-string encoding.
    """
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


def secondary_encoding(h_spin, g_spin, nuclear_repulsion, n_qubits):
    """Second independent fermion-to-qubit encoding for cross-validation.

    TODO: Implement an alternative encoding that produces a qubit
    Hamiltonian with an identical eigenspectrum but different Pauli
    term structure compared to the primary encoding.
    """
    raise NotImplementedError("Secondary encoding not yet implemented")
