
"""Quantum circuit representation for the {H, CNOT, Rz} gate set.

Gate conventions:
  - Rz(angle) = diag(1, exp(i * angle * pi)), angle in multiples of pi
  - T = Rz(0.25),  S = Rz(0.5),  Z = Rz(1.0)
  - T† = Rz(-0.25), S† = Rz(-0.5)
  - CNOT(c, t): |x_c, x_t> -> |x_c, x_c XOR x_t>
  - H: Hadamard gate

Qubit ordering: qubit 0 is the most significant bit.
  For state index i in a 2^n-dimensional vector,
  bit q = (i >> (n-1-q)) & 1.
"""

import numpy as np
from typing import List, Optional


class Gate:
    """A single quantum gate."""

    def __init__(self, name: str, qubits: List[int], angle: Optional[float] = None):
        self.name = name
        self.qubits = list(qubits)
        self.angle = angle

    def __repr__(self):
        if self.angle is not None:
            return f"Rz({self.angle}pi) q{self.qubits}"
        return f"{self.name} q{self.qubits}"


class Circuit:
    """A quantum circuit on *n_qubits* qubits."""

    def __init__(self, n_qubits: int):
        self.n_qubits = n_qubits
        self.gates: List[Gate] = []

    # ---- builder helpers (all return self for chaining) ----

    def h(self, q: int) -> "Circuit":
        self.gates.append(Gate("H", [q]))
        return self

    def cnot(self, control: int, target: int) -> "Circuit":
        self.gates.append(Gate("CNOT", [control, target]))
        return self

    def rz(self, q: int, angle: float) -> "Circuit":
        """Rz gate.  *angle* is in multiples of pi."""
        self.gates.append(Gate("Rz", [q], angle))
        return self

    def t(self, q: int) -> "Circuit":
        return self.rz(q, 0.25)

    def tdg(self, q: int) -> "Circuit":
        return self.rz(q, -0.25)

    def s(self, q: int) -> "Circuit":
        return self.rz(q, 0.5)

    def sdg(self, q: int) -> "Circuit":
        return self.rz(q, -0.5)

    def z(self, q: int) -> "Circuit":
        return self.rz(q, 1.0)

    # ---- metrics ----

    def t_count(self) -> int:
        """Number of non-Clifford Rz gates (angle not a multiple of pi/2)."""
        clifford_angles = {0.0, 0.5, 1.0, 1.5}
        count = 0
        for g in self.gates:
            if g.name == "Rz" and g.angle is not None:
                a = g.angle % 2.0
                if not any(abs(a - c) < 1e-10 for c in clifford_angles):
                    count += 1
        return count

    def cnot_count(self) -> int:
        return sum(1 for g in self.gates if g.name == "CNOT")

    def rz_count(self) -> int:
        return sum(1 for g in self.gates if g.name == "Rz")

    # ---- simulation ----

    def to_unitary(self) -> np.ndarray:
        """Return the 2^n x 2^n unitary matrix of the circuit."""
        n = self.n_qubits
        dim = 2 ** n
        U = np.eye(dim, dtype=complex)
        for gate in self.gates:
            M = _gate_matrix(gate, n)
            U = M @ U
        return U


# ---- internal helpers ----

def _single_qubit_matrix(gate_2x2: np.ndarray, qubit: int, n_qubits: int) -> np.ndarray:
    """Lift a 2x2 gate into the full 2^n Hilbert space."""
    dim = 2 ** n_qubits
    M = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        bit = (i >> (n_qubits - 1 - qubit)) & 1
        for b in range(2):
            coeff = gate_2x2[b, bit]
            if abs(coeff) > 1e-15:
                j = (i & ~(1 << (n_qubits - 1 - qubit))) | (b << (n_qubits - 1 - qubit))
                M[j, i] += coeff
    return M


def _gate_matrix(gate: Gate, n_qubits: int) -> np.ndarray:
    """Full 2^n matrix for one gate."""
    dim = 2 ** n_qubits

    if gate.name == "H":
        H2 = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
        return _single_qubit_matrix(H2, gate.qubits[0], n_qubits)

    if gate.name == "Rz":
        phase = np.exp(1j * gate.angle * np.pi)
        Rz2 = np.array([[1, 0], [0, phase]], dtype=complex)
        return _single_qubit_matrix(Rz2, gate.qubits[0], n_qubits)

    if gate.name == "CNOT":
        c, t = gate.qubits
        M = np.zeros((dim, dim), dtype=complex)
        for i in range(dim):
            ctrl = (i >> (n_qubits - 1 - c)) & 1
            if ctrl:
                j = i ^ (1 << (n_qubits - 1 - t))
                M[j, i] = 1.0
            else:
                M[i, i] = 1.0
        return M

    raise ValueError(f"Unknown gate: {gate.name}")
