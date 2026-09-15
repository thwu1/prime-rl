"""Quantum gate matrices and parameterized rotation gates."""
import numpy as np

# Pauli matrices and common single-qubit gates
I2 = np.eye(2, dtype=complex)
X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.array([[1, 0], [0, -1]], dtype=complex)
H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
S = np.array([[1, 0], [0, 1j]], dtype=complex)
T_gate = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex)

# Two-qubit gates
CNOT_matrix = np.array([
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 0, 1],
    [0, 0, 1, 0]
], dtype=complex)

SWAP_matrix = np.array([
    [1, 0, 0, 0],
    [0, 0, 1, 0],
    [0, 1, 0, 0],
    [0, 0, 0, 1]
], dtype=complex)


def Rx(theta):
    """Rotation around X: Rx(theta) = exp(-i * theta * X / 2)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def Ry(theta):
    """Rotation around Y: Ry(theta) = exp(-i * theta * Y / 2)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def Rz(theta):
    """Rotation around Z: Rz(theta) = exp(-i * theta * Z / 2)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c - 1j * s, 0], [0, c + 1j * s]], dtype=complex)


def dRx(theta):
    """d/dtheta of Rx(theta)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[-s / 2, -1j * c / 2], [-1j * c / 2, -s / 2]], dtype=complex)


def dRy(theta):
    """d/dtheta of Ry(theta)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[-s / 2, -c / 2], [c / 2, -s / 2]], dtype=complex)


def dRz(theta):
    """d/dtheta of Rz(theta)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[-s / 2 - 1j * c / 2, 0], [0, -s / 2 + 1j * c / 2]], dtype=complex)
