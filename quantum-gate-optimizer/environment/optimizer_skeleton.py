"""Quantum circuit optimizer — implement the optimize() method.

Your optimizer must reduce the gate count of a quantum circuit while
preserving its unitary matrix up to global phase.

The Circuit and Operation classes are defined in circuit.py.
Gate matrices and classifications are in gates.py.
"""

from circuit import Circuit


class CircuitOptimizer:
    """Quantum circuit optimizer.

    Implement the optimize() method below. It should return a new Circuit
    with fewer gates that computes the same unitary (up to global phase)
    as the input circuit.
    """

    def optimize(self, circuit: Circuit) -> Circuit:
        """Return an optimized version of the given circuit.

        The optimized circuit must satisfy:
        1. Same number of qubits as the input.
        2. Same unitary matrix up to a global phase factor.
        3. Fewer (or equal) gates than the input.

        Parameters
        ----------
        circuit : Circuit
            The input quantum circuit.

        Returns
        -------
        Circuit
            An optimized circuit with the same unitary and fewer gates.
        """
        raise NotImplementedError("Implement circuit optimization")
