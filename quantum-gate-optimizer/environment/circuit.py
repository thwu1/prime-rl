"""Quantum circuit representation and unitary computation.

Provides the Circuit class for building quantum circuits as sequences
of gate operations and computing their full unitary matrices.
"""

import numpy as np
from typing import List
from gates import gate_matrix, gate_num_qubits


class Operation:
    """A single gate operation applied to specific qubits."""

    def __init__(self, name: str, params: List[float], qubits: List[int]):
        self.name = name
        self.params = list(params)
        self.qubits = list(qubits)
        expected = gate_num_qubits(name)
        if len(qubits) != expected:
            raise ValueError(
                f"Gate {name} expects {expected} qubits, got {len(qubits)}"
            )

    def matrix(self) -> np.ndarray:
        """Return the gate's unitary matrix."""
        return gate_matrix(self.name, self.params)

    def __repr__(self):
        if self.params:
            pstr = ', '.join(f'{p:.6f}' for p in self.params)
            return f"{self.name}({pstr})[{','.join(str(q) for q in self.qubits)}]"
        return f"{self.name}[{','.join(str(q) for q in self.qubits)}]"


class Circuit:
    """Quantum circuit as a sequence of gate operations.

    Supports computing the full unitary matrix via Kronecker product
    expansion of individual gates to the full Hilbert space.

    Parameters
    ----------
    num_qubits : int
        Number of qubits in the circuit.
    """

    def __init__(self, num_qubits: int):
        self.num_qubits = num_qubits
        self.operations: List[Operation] = []

    def add(self, name: str, params: List[float], qubits: List[int]) -> 'Circuit':
        """Add a gate operation. Returns self for chaining."""
        op = Operation(name, params, qubits)
        for q in qubits:
            if q < 0 or q >= self.num_qubits:
                raise ValueError(f"Qubit index {q} out of range [0, {self.num_qubits})")
        self.operations.append(op)
        return self

    def gate_count(self) -> int:
        """Return the number of gates in the circuit."""
        return len(self.operations)

    def copy(self) -> 'Circuit':
        """Return a deep copy of this circuit."""
        c = Circuit(self.num_qubits)
        for op in self.operations:
            c.add(op.name, list(op.params), list(op.qubits))
        return c

    def unitary(self) -> np.ndarray:
        """Compute the full unitary matrix of the circuit.

        Gates are applied in list order: operations[0] first, then
        operations[1], etc. The unitary is U = U_n @ ... @ U_1.
        """
        dim = 2 ** self.num_qubits
        U = np.eye(dim, dtype=complex)
        for op in self.operations:
            U_expanded = self._expand_gate(op)
            U = U_expanded @ U
        return U

    def _expand_gate(self, op: Operation) -> np.ndarray:
        """Expand a gate to the full Hilbert space."""
        if len(op.qubits) == 1:
            return self._expand_single(op.matrix(), op.qubits[0])
        elif len(op.qubits) == 2:
            return self._expand_two(op.matrix(), op.qubits[0], op.qubits[1])
        else:
            raise ValueError(f"Gates on {len(op.qubits)} qubits not supported")

    def _expand_single(self, mat: np.ndarray, qubit: int) -> np.ndarray:
        """Expand a single-qubit gate via Kronecker product.

        Qubit ordering: qubit 0 is MSB (leftmost).
        """
        n = self.num_qubits
        I2 = np.eye(2, dtype=complex)
        parts = []
        for i in range(n):
            parts.append(mat if i == qubit else I2)
        result = parts[0]
        for p in parts[1:]:
            result = np.kron(result, p)
        return result

    def _expand_two(self, mat: np.ndarray, q0: int, q1: int) -> np.ndarray:
        """Expand a two-qubit gate to the full Hilbert space.

        Uses bit-level indexing to place the 4x4 gate matrix into the
        correct positions of the 2^n x 2^n full matrix.

        Qubit ordering: qubit 0 is MSB (leftmost).
        """
        n = self.num_qubits
        dim = 2 ** n
        result = np.zeros((dim, dim), dtype=complex)

        shift0 = n - 1 - q0
        shift1 = n - 1 - q1
        mask = ~((1 << shift0) | (1 << shift1)) & ((1 << n) - 1)

        for i in range(dim):
            for j in range(dim):
                if (i & mask) != (j & mask):
                    continue
                bi0 = (i >> shift0) & 1
                bi1 = (i >> shift1) & 1
                bj0 = (j >> shift0) & 1
                bj1 = (j >> shift1) & 1
                row = bi0 * 2 + bi1
                col = bj0 * 2 + bj1
                result[i, j] = mat[row, col]

        return result

    def __repr__(self):
        return f"Circuit({self.num_qubits}q, {self.gate_count()} gates)"
