"""ZNE-aware shot allocation optimizer.

Implements shot allocation for zero-noise extrapolation (ZNE)
of quantum Hamiltonian expectation values.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple

from hamiltonian import Hamiltonian
from simulator import sample_commuting_group


class ZNEShotOptimizer:
    """Shot allocator for zero-noise extrapolation."""

    def __init__(
        self,
        hamiltonian: Hamiltonian,
        scale_factors: List[float],
        noise_rate: float,
        depth: int,
    ):
        self.hamiltonian = hamiltonian
        self.scale_factors = np.array(scale_factors, dtype=float)
        self.noise_rate = noise_rate
        self.depth = depth
        self.n_levels = len(scale_factors)
        self.n_groups = hamiltonian.n_groups

    def lagrange_coefficients(self) -> np.ndarray:
        """Compute extrapolation coefficients for the configured scale factors.

        Returns:
            np.ndarray of shape (n_levels,)
        """
        raise NotImplementedError

    def estimate_group_variance(
        self, measurements: np.ndarray, group_idx: int
    ) -> float:
        """Estimate per-shot energy variance for a commuting group.

        Args:
            measurements: shape (num_shots, num_terms_in_group), +/-1 values
            group_idx: index into self.hamiltonian.groups

        Returns:
            float >= 0
        """
        raise NotImplementedError

    def optimal_allocation(
        self, variance_matrix: np.ndarray, total_budget: int
    ) -> np.ndarray:
        """Compute variance-minimizing integer shot allocation.

        Args:
            variance_matrix: shape (n_levels, n_groups), values >= 0
            total_budget: total shots to distribute

        Returns:
            np.ndarray of shape (n_levels, n_groups), integer,
            sum = total_budget, all entries >= 1
        """
        raise NotImplementedError

    def richardson_extrapolate(self, values_per_level: np.ndarray) -> float:
        """Extrapolate to zero noise.

        Args:
            values_per_level: shape (n_levels,)

        Returns:
            float
        """
        raise NotImplementedError

    def zne_variance(
        self, variance_matrix: np.ndarray, allocation: np.ndarray
    ) -> float:
        """Variance of the extrapolated estimate.

        Args:
            variance_matrix: shape (n_levels, n_groups)
            allocation: shape (n_levels, n_groups), integer, all > 0

        Returns:
            float >= 0
        """
        raise NotImplementedError

    def measure_and_estimate(
        self,
        state: np.ndarray,
        allocation: np.ndarray,
        rng: Optional[np.random.Generator] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Execute measurements and compute energy/variance estimates.

        Args:
            state: quantum state vector
            allocation: shape (n_levels, n_groups), integer shot counts
            rng: random number generator

        Returns:
            Tuple of:
            - energy_per_level: shape (n_levels,)
            - variance_matrix: shape (n_levels, n_groups)
        """
        raise NotImplementedError

    def run_adaptive(
        self,
        state: np.ndarray,
        total_budget: int,
        num_rounds: int,
        rng: Optional[np.random.Generator] = None,
    ) -> Dict:
        """Run adaptive multi-round shot allocation.

        Returns:
            Dict with keys: 'energy', 'variance', 'energy_per_level', 'allocation'
        """
        raise NotImplementedError
