"""
Hamiltonian generator for multi-chain tight-binding molecular system.

Generates a sparse symmetric Hamiltonian with intra-chain nearest/next-nearest
neighbor hopping and random inter-chain couplings, producing a matrix with both
banded structure and long-range off-diagonal entries.
"""
import numpy as np
from scipy.sparse import lil_matrix, csr_matrix


def generate_hamiltonian(n_atoms, seed=42, n_chains=5, chain_coupling=0.15):
    """
    Generate a sparse symmetric Hamiltonian for a multi-chain tight-binding system.

    Args:
        n_atoms: Total number of atoms
        seed: Random seed for reproducibility
        n_chains: Number of atomic chains
        chain_coupling: Fraction of atoms per chain that have inter-chain bonds

    Returns:
        H: scipy.sparse.csr_matrix, symmetric Hamiltonian matrix
    """
    rng = np.random.RandomState(seed)
    n = n_atoms
    H = lil_matrix((n, n))

    chain_len = n // n_chains

    for c in range(n_chains):
        start = c * chain_len
        end = start + chain_len if c < n_chains - 1 else n

        # On-site energies
        for i in range(start, end):
            H[i, i] = rng.uniform(-2.0, 2.0)

        # Nearest-neighbor hopping
        for i in range(start, end - 1):
            t = rng.uniform(-1.0, -0.3)
            H[i, i + 1] = t
            H[i + 1, i] = t

        # Next-nearest-neighbor hopping
        for i in range(start, end - 2):
            t = rng.uniform(-0.3, 0.3)
            H[i, i + 2] = t
            H[i + 2, i] = t

    # Inter-chain couplings (long-range connections)
    for c1 in range(n_chains):
        for c2 in range(c1 + 1, n_chains):
            start1 = c1 * chain_len
            start2 = c2 * chain_len
            end2 = start2 + chain_len if c2 < n_chains - 1 else n
            n_couplings = max(1, int(chain_len * chain_coupling))
            for _ in range(n_couplings):
                i = start1 + rng.randint(0, chain_len)
                j = start2 + rng.randint(0, end2 - start2)
                if i < n and j < n and i != j:
                    t = rng.uniform(-0.2, 0.2)
                    H[i, j] = t
                    H[j, i] = t

    H_csr = csr_matrix(H)
    # Ensure perfect symmetry
    H_csr = (H_csr + H_csr.T) / 2.0
    H_csr.eliminate_zeros()

    return H_csr
