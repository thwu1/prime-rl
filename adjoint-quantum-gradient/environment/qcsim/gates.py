"""
Quantum gate matrices and their parameter derivatives.

"""
import numpy as np

# Fixed single-qubit gates
I_GATE = np.eye(2, dtype=complex)
X_GATE = np.array([[0, 1], [1, 0]], dtype=complex)
Y_GATE = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z_GATE = np.array([[1, 0], [0, -1]], dtype=complex)
H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
S_GATE = np.array([[1, 0], [0, 1j]], dtype=complex)
T_GATE = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex)


# Parameterized rotation gates
def rx_gate(theta):
    """Rotation around X axis by angle theta."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def ry_gate(theta):
    """Rotation around Y axis by angle theta."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def rz_gate(theta):
    """Rotation around Z axis by angle theta."""
    return np.array(
        [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex
    )


# Analytic derivatives of rotation gates w.r.t. theta
def drx_gate(theta):
    """d/dtheta RX(theta)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[-s / 2, -1j * c / 2], [-1j * c / 2, -s / 2]], dtype=complex)


def dry_gate(theta):
    """d/dtheta RY(theta)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[-s / 2, -c / 2], [c / 2, -s / 2]], dtype=complex)


def drz_gate(theta):
    """d/dtheta RZ(theta)."""
    return np.array(
        [[-1j * np.exp(-1j * theta / 2) / 2, 0], [0, 1j * np.exp(1j * theta / 2) / 2]],
        dtype=complex,
    )
