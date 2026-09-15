# --------------------------------------------------------------------------------------
# This file is part of qpe-toolbox.
#
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0.
#
# Reference implementation of the Hamiltonian class.
# NOT runnable in this environment — provided as reference for data format understanding.
# --------------------------------------------------------------------------------------

import numpy as np
import quimb as qu
import quimb.tensor as qtn
from quimb.operator import SparseOperatorBuilder


def heisenberg_hamiltonian(n_qubits, *, coupling_strength=1.0):
    """
    Construct a 1D nearest-neighbor spin 1/2 Heisenberg Hamiltonian with open boundaries.

    The Hamiltonian is given by

    .. math::
        H = \\sum_{i=0}^{N-2} \\frac{J}{4}
        (X_i X_{i+1} + Y_i Y_{i+1} + Z_i Z_{i+1})

    The normalization is chosen such that ``heisenberg_hamiltonian(2)`` is the standard
    S.S operator with eigenvalues (-3/4, 1/4, 1/4, 1/4).
    """
    terms = []
    for i in range(n_qubits - 1):
        for op in ["xx", "yy", "zz"]:
            # convention: S^a = sigma^a / 2
            # use Pauli matrices as terms and set coefficient to J/4
            terms.append((coupling_strength / 4, op, [i, i + 1]))
    return Hamiltonian(terms, n_qubits)


class Hamiltonian:
    """
    Qubit Hamiltonian represented as a sum of Pauli strings.

    Parameters
    ----------
    terms : sequence of tuple
        Hamiltonian terms in the form
        ``(coefficient, pauli_string, qubits)``, e.g. ``(0.5, "xy", [0, 1])``.
    n_qubits : int
        Total number of qubits.
    """

    def __init__(self, terms, n_qubits):
        self._terms = list(terms)
        self._n_qubits = int(n_qubits)

    @property
    def terms(self):
        return self._terms

    @property
    def n_terms(self):
        return len(self._terms)

    @property
    def n_qubits(self):
        return self._n_qubits

    @property
    def shape(self):
        return (2**self._n_qubits, 2**self._n_qubits)

    def to_dense(self):
        """
        Convert the Hamiltonian to a dense matrix representation.
        """
        h_dense = np.zeros([2**self.n_qubits, 2**self.n_qubits], dtype="complex")
        for coeff, paulis, qubits in self.terms:
            ops = [qu.identity(2)] * self.n_qubits
            for sigma, k in zip(paulis, qubits, strict=True):
                ops[k] = qu.pauli(sigma)
            h_dense += coeff * qu.kron(*ops)
        return qu.qarray(h_dense)
