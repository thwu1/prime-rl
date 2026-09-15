"""Spectral analysis and Hamiltonian reduction."""
import numpy as np

PAULI = {
    "I": np.eye(2, dtype=complex),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
}


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


def find_symmetry_reduction(hamiltonian_dict, n_qubits):
    """Reduce the Hamiltonian by exploiting conserved quantities.

    Should identify independent operators that commute with every
    term in the Hamiltonian and use them to project into a smaller
    subspace, preserving the ground state energy.

    Returns:
        dict with keys: n_symmetries, reduced_n_qubits, reduced_ground_energy
    """
    raise NotImplementedError(
        "Symmetry-based Hamiltonian reduction not yet implemented"
    )
