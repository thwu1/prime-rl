"""Quantum LDPC Code Framework

Provides CSS code construction via hypergraph product of classical codes,
GF(2) linear algebra, and depolarizing noise simulation.

"""

import numpy as np
from typing import Tuple


# ========== GF(2) Linear Algebra ==========

def gf2_rank(matrix: np.ndarray) -> int:
    """Compute rank of a binary matrix over GF(2) via row reduction."""
    if matrix.size == 0:
        return 0
    m = matrix.copy().astype(int) % 2
    rows, cols = m.shape
    rank = 0
    for col in range(cols):
        pivot = None
        for r in range(rank, rows):
            if m[r, col]:
                pivot = r
                break
        if pivot is None:
            continue
        if pivot != rank:
            m[[rank, pivot]] = m[[pivot, rank]]
        for r in range(rows):
            if r != rank and m[r, col]:
                m[r] = (m[r] + m[rank]) % 2
        rank += 1
    return rank


def gf2_row_reduce(matrix: np.ndarray, syndrome: np.ndarray = None):
    """Row reduce a binary matrix over GF(2) to RREF.

    Optionally co-transforms a syndrome vector using the same row operations.

    Returns:
        (rref, pivot_cols) if syndrome is None
        (rref, pivot_cols, transformed_syndrome) if syndrome is provided
    """
    m = matrix.copy().astype(int) % 2
    rows, cols = m.shape
    s = None
    if syndrome is not None:
        s = syndrome.copy().astype(int) % 2

    pivots = []
    row_idx = 0
    for col in range(cols):
        pivot = None
        for r in range(row_idx, rows):
            if m[r, col]:
                pivot = r
                break
        if pivot is None:
            continue
        if pivot != row_idx:
            m[[row_idx, pivot]] = m[[pivot, row_idx]]
            if s is not None:
                s[[row_idx, pivot]] = s[[pivot, row_idx]]
        for r in range(rows):
            if r != row_idx and m[r, col]:
                m[r] = (m[r] + m[row_idx]) % 2
                if s is not None:
                    s[r] = (s[r] + s[row_idx]) % 2
        pivots.append(col)
        row_idx += 1

    if s is not None:
        return m, pivots, s
    return m, pivots


# ========== Classical Codes ==========

def hamming_parity_check() -> np.ndarray:
    """Parity check matrix of the [7, 4, 3] Hamming code."""
    return np.array([
        [1, 0, 0, 1, 0, 1, 1],
        [0, 1, 0, 1, 1, 0, 1],
        [0, 0, 1, 0, 1, 1, 1]
    ], dtype=int)


# ========== Hypergraph Product Construction ==========

def hypergraph_product(H1: np.ndarray, H2: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Construct a CSS code via the hypergraph product of two classical codes.

    Given parity check matrices H1 (r1 x n1) and H2 (r2 x n2), constructs:
        H_X = [H1 (x) I_{n2}  |  I_{r1} (x) H2^T]
        H_Z = [I_{n1} (x) H2  |  H1^T (x) I_{r2}]

    Total physical qubits: n1*n2 + r1*r2

    The CSS orthogonality condition H_X H_Z^T = 0 (mod 2) is guaranteed
    by the algebraic structure of the Kronecker products.

    Returns:
        (H_X, H_Z): X-check and Z-check parity matrices over GF(2).
    """
    r1, n1 = H1.shape
    r2, n2 = H2.shape

    H_X = np.hstack([
        np.kron(H1, np.eye(n2, dtype=int)),
        np.kron(np.eye(r1, dtype=int), H2.T)
    ]) % 2

    H_Z = np.hstack([
        np.kron(np.eye(n1, dtype=int), H2),
        np.kron(H1.T, np.eye(r2, dtype=int))
    ]) % 2

    return H_X.astype(int), H_Z.astype(int)


# ========== CSS Code Class ==========

class CSSCode:
    """A CSS quantum error correcting code defined by X and Z check matrices.

    Attributes:
        H_X: X-type stabilizer parity check matrix (m_x x n).
        H_Z: Z-type stabilizer parity check matrix (m_z x n).
        n:   Number of physical qubits.
        k:   Number of logical qubits.
    """

    def __init__(self, H_X: np.ndarray, H_Z: np.ndarray):
        self.H_X = H_X.astype(int) % 2
        self.H_Z = H_Z.astype(int) % 2

        assert H_X.shape[1] == H_Z.shape[1], \
            "H_X and H_Z must act on the same number of qubits"

        # Verify CSS orthogonality: H_X @ H_Z^T = 0 mod 2
        product = (self.H_X @ self.H_Z.T) % 2
        assert np.all(product == 0), \
            "CSS condition violated: H_X @ H_Z^T != 0 mod 2"

        self.n = H_X.shape[1]
        self._rank_hx = gf2_rank(self.H_X)
        self._rank_hz = gf2_rank(self.H_Z)
        self.k = self.n - self._rank_hx - self._rank_hz

    def x_syndrome(self, z_error: np.ndarray) -> np.ndarray:
        """Compute X-syndrome from a Z-type error: s_x = H_X @ e_z mod 2."""
        return (self.H_X @ z_error.astype(int)) % 2

    def z_syndrome(self, x_error: np.ndarray) -> np.ndarray:
        """Compute Z-syndrome from an X-type error: s_z = H_Z @ e_x mod 2."""
        return (self.H_Z @ x_error.astype(int)) % 2

    def is_x_logical_error(self, x_residual: np.ndarray) -> bool:
        """Check if an X-type residual (correction XOR true error) is a
        non-trivial X logical operator.

        True iff x_residual is in ker(H_Z) but NOT in rowspace(H_X).
        """
        if np.all(x_residual == 0):
            return False
        if not np.all((self.H_Z @ x_residual) % 2 == 0):
            return False
        aug = np.vstack([self.H_X, x_residual.reshape(1, -1)])
        return gf2_rank(aug) > self._rank_hx

    def is_z_logical_error(self, z_residual: np.ndarray) -> bool:
        """Check if a Z-type residual is a non-trivial Z logical operator.

        True iff z_residual is in ker(H_X) but NOT in rowspace(H_Z).
        """
        if np.all(z_residual == 0):
            return False
        if not np.all((self.H_X @ z_residual) % 2 == 0):
            return False
        aug = np.vstack([self.H_Z, z_residual.reshape(1, -1)])
        return gf2_rank(aug) > self._rank_hz

    def __repr__(self):
        return f"CSSCode([[{self.n}, {self.k}]])"


# ========== Code Builders ==========

def build_default_code() -> CSSCode:
    """Build the default test code: hypergraph product of [7,4,3] Hamming
    code with itself, yielding a [[58, 16]] CSS code."""
    H = hamming_parity_check()
    H_X, H_Z = hypergraph_product(H, H)
    return CSSCode(H_X, H_Z)


# ========== Noise Model ==========

def generate_depolarizing_errors(
    n: int, p: float, num_samples: int, seed: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Generate independent depolarizing noise samples.

    Each qubit independently experiences:
        I with probability 1 - p
        X with probability p/3
        Y with probability p/3  (both X and Z)
        Z with probability p/3

    Args:
        n:           Number of qubits.
        p:           Total per-qubit error probability.
        num_samples: Number of noise samples to generate.
        seed:        Random seed for reproducibility.

    Returns:
        (x_errors, z_errors): Integer arrays of shape (num_samples, n).
            x_errors[i, j] = 1 iff qubit j has an X or Y error in sample i.
            z_errors[i, j] = 1 iff qubit j has a Z or Y error in sample i.
    """
    rng = np.random.default_rng(seed)
    rand = rng.random((num_samples, n))

    # Partition [0, 1):
    #   [0,     p/3)   -> X only
    #   [p/3,   2p/3)  -> Y (X + Z)
    #   [2p/3,  p)     -> Z only
    #   [p,     1)     -> I (no error)
    x_errors = (rand < 2 * p / 3).astype(int)           # X or Y
    z_errors = ((rand >= p / 3) & (rand < p)).astype(int)  # Y or Z

    return x_errors, z_errors
