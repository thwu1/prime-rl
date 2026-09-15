"""Target 3-qubit unitary matrix for quantum circuit synthesis."""
import numpy as np


def get_target_unitary():
    """
    Returns a non-trivial 8x8 unitary matrix (3-qubit operation).

    Constructed as a diagonal phase matrix applied to the 3-qubit
    Quantum Fourier Transform, producing a dense unitary with no
    exploitable symmetries for trivial decomposition.
    """
    N = 8
    omega = np.exp(2j * np.pi / N)

    # 3-qubit QFT matrix
    QFT = np.array(
        [[omega ** (j * k) for k in range(N)] for j in range(N)],
        dtype=np.complex128,
    ) / np.sqrt(N)

    # Diagonal phase twists (irrational multiples to break symmetries)
    phases = [0.0, 0.3, 0.7, 1.1, 1.5, 1.9, 2.3, 2.7]
    D = np.diag([np.exp(1j * p) for p in phases])

    return D @ QFT


if __name__ == "__main__":
    U = get_target_unitary()
    print(f"Shape: {U.shape}")
    print(f"Unitary check: {np.allclose(U @ U.conj().T, np.eye(8))}")
    print(f"Determinant magnitude: {abs(np.linalg.det(U)):.10f}")
