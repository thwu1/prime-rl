"""
OpenQASM 2.0 parser.

"""
from qcsim.circuit import Circuit


def parse_qasm(filepath):
    """
    Parse an OpenQASM 2.0 file and return a Circuit object.

    Must handle: qreg declarations, standard gates (h, x, y, z, cx),
    and parameterized rotation gates (rx, ry, rz) with literal angle values.

    Args:
        filepath: path to a .qasm file.

    Returns:
        A Circuit object with the parsed gates applied.
    """
    raise NotImplementedError
