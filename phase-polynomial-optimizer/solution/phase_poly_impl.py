
"""Phase polynomial optimizer -- full implementation.

Provides extraction, optimization, synthesis, and full-pipeline functions
for reducing T-gate count in quantum circuits using the phase polynomial
representation over GF(2).
"""

from typing import Dict, List, Tuple, Optional
from circuit import Circuit, Gate


class PhasePolynomial:
    """Phase polynomial representation of a {CNOT, Rz} circuit."""

    def __init__(self, n_qubits: int):
        self.n_qubits = n_qubits
        self.terms: Dict[tuple, float] = {}
        self.parity_matrix: List[List[int]] = [
            [1 if i == j else 0 for j in range(n_qubits)]
            for i in range(n_qubits)
        ]

    def add_term(self, parity: tuple, angle: float):
        if parity in self.terms:
            self.terms[parity] += angle
        else:
            self.terms[parity] = angle

    def remove_trivial_terms(self):
        to_remove = []
        for p, a in self.terms.items():
            norm = a % 2.0
            if abs(norm) < 1e-10 or abs(norm - 2.0) < 1e-10:
                to_remove.append(p)
        for p in to_remove:
            del self.terms[p]

    def term_count(self) -> int:
        return len(self.terms)


# =========================================================================
# 1. Extraction
# =========================================================================

def extract_phase_polynomial(circuit: Circuit) -> PhasePolynomial:
    """Extract the phase polynomial from a {CNOT, Rz} circuit."""
    n = circuit.n_qubits
    pp = PhasePolynomial(n)

    # Parity labels -- label[q] tracks which input bits XOR to form qubit q
    labels = [[1 if i == j else 0 for j in range(n)] for i in range(n)]

    for gate in circuit.gates:
        if gate.name == "CNOT":
            c, t = gate.qubits
            for j in range(n):
                labels[t][j] ^= labels[c][j]
        elif gate.name == "Rz":
            q = gate.qubits[0]
            parity = tuple(labels[q])
            pp.add_term(parity, gate.angle)
        else:
            raise ValueError(
                f"Expected only CNOT and Rz gates, got: {gate.name}"
            )

    pp.parity_matrix = [list(row) for row in labels]
    return pp


# =========================================================================
# 2. Optimization
# =========================================================================

def optimize_phase_polynomial(pp: PhasePolynomial) -> PhasePolynomial:
    """Return an optimised copy: normalise angles, drop zero terms."""
    result = PhasePolynomial(pp.n_qubits)
    result.parity_matrix = [list(row) for row in pp.parity_matrix]

    for parity, angle in pp.terms.items():
        # Normalise into (-1, 1]
        a = angle % 2.0
        if a > 1.0:
            a -= 2.0
        if abs(a) > 1e-10:
            result.terms[parity] = a

    return result


# =========================================================================
# 3. Synthesis
# =========================================================================

def synthesize_circuit(pp: PhasePolynomial) -> Circuit:
    """Build a {CNOT, Rz} circuit that realises *pp*."""
    n = pp.n_qubits
    circ = Circuit(n)

    # --- phase terms ---
    for parity_tuple, angle in pp.terms.items():
        f = list(parity_tuple)

        # All-zero parity => global phase, skip
        if 1 not in f:
            continue

        target_q = f.index(1)

        # CNOT other set bits into target_q to build the parity
        cnots: List[int] = []
        for q in range(n):
            if q != target_q and f[q]:
                circ.cnot(q, target_q)
                cnots.append(q)

        # Rotate
        circ.rz(target_q, angle)

        # Undo CNOTs to restore identity parities
        for q in reversed(cnots):
            circ.cnot(q, target_q)

    # --- output parity matrix ---
    _synthesize_linear_reversible(circ, pp.parity_matrix, n)

    return circ


def _synthesize_linear_reversible(
    circ: Circuit, target: List[List[int]], n: int
) -> None:
    """Decompose an invertible n x n binary matrix into CNOT gates.

    Uses Gaussian elimination over GF(2).  The recorded row-addition
    operations are replayed in reverse to build the circuit.
    """
    # Quick identity check
    if all(
        target[i][j] == (1 if i == j else 0)
        for i in range(n)
        for j in range(n)
    ):
        return

    M = [list(row) for row in target]
    ops: List[Tuple[int, int]] = []          # (control_row, target_row)

    # Forward elimination
    for col in range(n):
        pivot = None
        for row in range(col, n):
            if M[row][col]:
                pivot = row
                break
        if pivot is None:
            raise ValueError("Parity matrix is singular")

        if pivot != col:
            # Swap via three row additions
            ops.append((pivot, col))
            for j in range(n):
                M[col][j] ^= M[pivot][j]
            ops.append((col, pivot))
            for j in range(n):
                M[pivot][j] ^= M[col][j]
            ops.append((pivot, col))
            for j in range(n):
                M[col][j] ^= M[pivot][j]

        for row in range(col + 1, n):
            if M[row][col]:
                ops.append((col, row))
                for j in range(n):
                    M[row][j] ^= M[col][j]

    # Back substitution
    for col in range(n - 1, -1, -1):
        for row in range(col):
            if M[row][col]:
                ops.append((col, row))
                for j in range(n):
                    M[row][j] ^= M[col][j]

    # Apply in reverse as circuit gates
    for c, t in reversed(ops):
        circ.cnot(c, t)


# =========================================================================
# 4. Full pipeline
# =========================================================================

def optimize_circuit(circuit: Circuit) -> Circuit:
    """Optimise an {H, CNOT, Rz} circuit using phase polynomials."""
    n = circuit.n_qubits

    # Partition at Hadamard gates
    blocks: list = []                    # ('block', Circuit) | ('h', int)
    current = Circuit(n)

    for gate in circuit.gates:
        if gate.name == "H":
            blocks.append(("block", current))
            blocks.append(("h", gate.qubits[0]))
            current = Circuit(n)
        else:
            current.gates.append(
                Gate(gate.name, list(gate.qubits), gate.angle)
            )
    blocks.append(("block", current))

    # Optimise each {CNOT, Rz} block and reassemble
    result = Circuit(n)
    for kind, data in blocks:
        if kind == "h":
            result.h(data)
        else:
            blk: Circuit = data
            if not blk.gates:
                continue
            pp = extract_phase_polynomial(blk)
            pp_opt = optimize_phase_polynomial(pp)
            opt_blk = synthesize_circuit(pp_opt)
            result.gates.extend(opt_blk.gates)

    return result
