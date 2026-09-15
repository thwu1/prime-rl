
"""Phase polynomial representation and optimization for quantum circuits.

A {CNOT, Rz} circuit on *n* qubits implements the unitary

    |x> --> exp(i pi  sum_k  theta_k (f_k . x))  |P x>

where
  - each (f_k, theta_k) is a *phase term*:
        f_k in F_2^n  is a binary parity vector,
        theta_k in R   is a rotation angle in multiples of pi
  - P in GL(n, F_2) is the output *parity matrix*
  - (f_k . x) = XOR of x_i for every i where f_k[i]=1   (inner product mod 2)

Key insight: when two Rz gates act on the same parity (i.e. the qubit
holds the same linear combination of input bits), their angles add.
If the sum is a multiple of 2 (equivalently 2 pi in radians), the term
vanishes -- producing a net reduction in gate count.
"""

from typing import Dict, List, Tuple
from circuit import Circuit, Gate


class PhasePolynomial:
    """Phase polynomial representation of a {CNOT, Rz} circuit.

    Attributes
    ----------
    n_qubits : int
        Number of qubits.
    terms : dict[tuple[int,...], float]
        Mapping  parity_vector -> accumulated_angle.
        A parity vector is a tuple of n ints in {0,1}.
        The angle is in multiples of pi.
    parity_matrix : list[list[int]]
        n x n binary matrix.  Row i is the output parity of qubit i,
        expressed as a linear combination of input bits over F_2.
        Initialised to the identity.
    """

    def __init__(self, n_qubits: int):
        self.n_qubits = n_qubits
        self.terms: Dict[tuple, float] = {}
        self.parity_matrix: List[List[int]] = [
            [1 if i == j else 0 for j in range(n_qubits)]
            for i in range(n_qubits)
        ]

    def add_term(self, parity: tuple, angle: float):
        """Add a phase term, merging with any existing term on the same parity."""
        if parity in self.terms:
            self.terms[parity] += angle
        else:
            self.terms[parity] = angle

    def remove_trivial_terms(self):
        """Drop terms whose angle is effectively 0 mod 2 (i.e. 0 mod 2pi)."""
        to_remove = []
        for p, a in self.terms.items():
            norm = a % 2.0
            if abs(norm) < 1e-10 or abs(norm - 2.0) < 1e-10:
                to_remove.append(p)
        for p in to_remove:
            del self.terms[p]

    def term_count(self) -> int:
        return len(self.terms)


# ---------------------------------------------------------------------------
# Functions to implement
# ---------------------------------------------------------------------------

def extract_phase_polynomial(circuit: Circuit) -> PhasePolynomial:
    """Extract the phase polynomial from a *{CNOT, Rz}-only* circuit.

    Raise ``ValueError`` if the circuit contains any other gate type.

    Algorithm sketch
    ~~~~~~~~~~~~~~~~
    Maintain a *parity label* for each qubit -- a binary vector in F_2^n
    that records which input bits XOR together to form the qubit's current
    value.  Labels start as standard basis vectors e_0 ... e_{n-1}.

    * CNOT(c, t):  label[t]  ^=  label[c]      (no phase contribution)
    * Rz(theta, q): record phase term (label[q], theta)

    After processing every gate, the final labels form the rows of the
    output parity matrix.

    Returns
    -------
    PhasePolynomial
        The extracted representation with merged terms and the final
        parity matrix.
    """
    raise NotImplementedError("TODO: implement extraction")


def optimize_phase_polynomial(pp: PhasePolynomial) -> PhasePolynomial:
    """Return an optimized copy of *pp*.

    * Angles should be normalized into the half-open interval (-1, 1]
      (in multiples of pi).
    * Terms whose normalized angle is effectively zero should be removed.
    * The parity matrix must be preserved unchanged.

    Returns
    -------
    PhasePolynomial
        A new object; the original is not modified.
    """
    raise NotImplementedError("TODO: implement optimization")


def synthesize_circuit(pp: PhasePolynomial) -> Circuit:
    """Synthesize a {CNOT, Rz} circuit that realises *pp*.

    The returned circuit must implement the same unitary as the phase
    polynomial, including the output parity matrix.

    A correct (not necessarily optimal) strategy:

    1. For each phase term (f, theta):
       - use CNOT gates to compute the parity f into one qubit
       - apply Rz(theta) on that qubit
       - undo the CNOTs so the parity state returns to identity

    2. Append CNOT gates that implement the linear transformation
       described by ``pp.parity_matrix`` (decompose the invertible
       binary matrix into elementary row operations via Gaussian
       elimination over GF(2)).

    Returns
    -------
    Circuit
    """
    raise NotImplementedError("TODO: implement synthesis")


def optimize_circuit(circuit: Circuit) -> Circuit:
    """Optimize an arbitrary {H, CNOT, Rz} circuit via phase polynomials.

    General strategy:

    1. Partition the gate list at every Hadamard gate, producing a
       sequence of {CNOT, Rz} blocks separated by single-qubit H gates.
    2. For each block: extract -> optimize -> synthesize.
    3. Re-assemble the full circuit by interleaving the optimized blocks
       with the original H gates.

    The returned circuit must be unitarily equivalent to the input.

    Returns
    -------
    Circuit
    """
    raise NotImplementedError("TODO: implement full pipeline")
