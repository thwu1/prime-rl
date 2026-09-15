"""OpenQASM 2.0 parser and writer for the circuit framework.

Bridge between the standard OpenQASM 2.0 circuit description format
and the internal Circuit representation defined in circuit.py.

Gate names in QASM differ from internal names (e.g., 'cx' vs 'CNOT').
See the benchmark files in /app/benchmarks/ for QASM format examples.
"""

from circuit import Circuit


def parse_qasm(qasm_str: str) -> Circuit:
    """Parse an OpenQASM 2.0 string into a Circuit.

    Parameters
    ----------
    qasm_str : str
        A valid OpenQASM 2.0 program string.

    Returns
    -------
    Circuit
        The parsed quantum circuit using internal gate names.
    """
    raise NotImplementedError("Implement QASM parser")


def write_qasm(circuit: Circuit) -> str:
    """Write a Circuit object to an OpenQASM 2.0 format string.

    Parameters
    ----------
    circuit : Circuit
        The quantum circuit to serialize.

    Returns
    -------
    str
        A valid OpenQASM 2.0 program string.
    """
    raise NotImplementedError("Implement QASM writer")
