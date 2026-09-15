"""Hamiltonian decomposition and Pauli term grouping utilities."""

from typing import List, Tuple
import numpy as np


def qw_commute(p1: str, p2: str) -> bool:
    """Check if two Pauli strings qubitwise commute.

    Two Pauli strings qubitwise commute iff at every qubit position,
    the single-qubit operators are the same or at least one is identity.
    """
    for a, b in zip(p1, p2):
        if a != "I" and b != "I" and a != b:
            return False
    return True


def find_commuting_groups(pauli_strings: List[str]) -> List[List[int]]:
    """Group Pauli strings into qubitwise-commuting families (greedy).

    Returns list of groups, each a list of indices into pauli_strings.
    """
    groups: List[List[int]] = []
    for idx, ps in enumerate(pauli_strings):
        placed = False
        for group in groups:
            if all(qw_commute(ps, pauli_strings[j]) for j in group):
                group.append(idx)
                placed = True
                break
        if not placed:
            groups.append([idx])
    return groups


class Hamiltonian:
    """Quantum Hamiltonian as a weighted sum of Pauli strings.

    H = sum_i coefficients[i] * terms[i]
    """

    def __init__(self, terms: List[str], coefficients: List[float]):
        assert len(terms) == len(coefficients)
        assert len(terms) > 0
        assert all(len(t) == len(terms[0]) for t in terms)
        self.terms = terms
        self.coefficients = np.array(coefficients, dtype=float)
        self.n_qubits = len(terms[0])
        self.n_terms = len(terms)
        self._groups = None

    @property
    def groups(self) -> List[List[int]]:
        """Cached qubitwise-commuting groups."""
        if self._groups is None:
            self._groups = find_commuting_groups(self.terms)
        return self._groups

    @property
    def n_groups(self) -> int:
        return len(self.groups)

    def group_terms(self, group_idx: int) -> Tuple[List[str], np.ndarray]:
        """Get Pauli strings and coefficients for a specific group."""
        indices = self.groups[group_idx]
        terms = [self.terms[i] for i in indices]
        coeffs = self.coefficients[indices]
        return terms, coeffs

    def exact_energy(self, state: np.ndarray) -> float:
        """Compute exact <psi|H|psi> via statevector simulation."""
        from simulator import exact_expectation

        energy = 0.0
        for term, coeff in zip(self.terms, self.coefficients):
            energy += coeff * exact_expectation(state, term)
        return energy
