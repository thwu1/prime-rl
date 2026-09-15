#!/usr/bin/env python3
"""Generate the complete ZNEShotOptimizer implementation.

Derives the solution by implementing the mathematical framework for
variance-optimal shot allocation under Richardson ZNE, including
Lagrange coefficient computation, covariance-aware variance estimation,
constrained optimization via Cauchy-Schwarz, and adaptive allocation.
"""


import sys
import textwrap

SOLUTION_CODE = textwrap.dedent('''\
    """ZNE-aware shot allocation optimizer.

    Implements variance-optimal shot allocation for Richardson zero-noise
    extrapolation (ZNE) of quantum Hamiltonian expectation values.
    """

    import numpy as np
    from typing import Dict, List, Optional, Tuple

    from hamiltonian import Hamiltonian
    from simulator import sample_commuting_group


    class ZNEShotOptimizer:
        """Variance-optimal shot allocator for Richardson ZNE."""

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
            x = self.scale_factors
            n = len(x)
            gamma = np.ones(n, dtype=float)
            for j in range(n):
                for k in range(n):
                    if k != j:
                        gamma[j] *= x[k] / (x[k] - x[j])
            return gamma

        def estimate_group_variance(
            self, measurements: np.ndarray, group_idx: int
        ) -> float:
            indices = self.hamiltonian.groups[group_idx]
            coeffs = self.hamiltonian.coefficients[indices]
            # Weighted sum per shot: energy contribution from this group
            weighted = measurements @ coeffs
            # Sample variance (unbiased) of the per-shot energy contribution
            if measurements.shape[0] > 1:
                var = float(np.var(weighted, ddof=1))
            else:
                var = 0.0
            return max(var, 0.0)

        def optimal_allocation(
            self, variance_matrix: np.ndarray, total_budget: int
        ) -> np.ndarray:
            gamma = self.lagrange_coefficients()
            n_levels, n_groups = variance_matrix.shape
            n_cells = n_levels * n_groups

            # Start with minimum 1 shot per cell
            alloc = np.ones((n_levels, n_groups), dtype=int)
            remaining = total_budget - n_cells

            if remaining <= 0:
                # Not enough budget; distribute as evenly as possible
                alloc = np.ones((n_levels, n_groups), dtype=int)
                deficit = total_budget - n_cells
                # If budget < n_cells, we still need sum = total_budget
                if deficit < 0:
                    alloc = np.zeros((n_levels, n_groups), dtype=int)
                    for i in range(total_budget):
                        alloc.flat[i % n_cells] += 1
                return alloc

            # Compute weights: |gamma_j| * sqrt(V[j,k])
            weights = np.abs(gamma)[:, None] * np.sqrt(
                np.maximum(variance_matrix, 0.0)
            )
            total_weight = weights.sum()

            if total_weight < 1e-15:
                # All variances effectively zero; distribute uniformly
                extra_per = remaining // n_cells
                extra = np.full((n_levels, n_groups), extra_per, dtype=int)
                leftover = remaining - extra.sum()
                for i in range(leftover):
                    extra.flat[i] += 1
                return alloc + extra

            # Continuous optimal allocation of remaining budget
            continuous = remaining * weights / total_weight

            # Floor and distribute remainders by largest fractional part
            extra = np.floor(continuous).astype(int)
            alloc += extra
            leftover = total_budget - alloc.sum()
            if leftover > 0:
                fractional = continuous - np.floor(continuous)
                flat_order = np.argsort(fractional.ravel())[::-1]
                for i in range(int(leftover)):
                    alloc.flat[flat_order[i]] += 1

            return alloc

        def richardson_extrapolate(self, values_per_level: np.ndarray) -> float:
            gamma = self.lagrange_coefficients()
            return float(gamma @ values_per_level)

        def zne_variance(
            self, variance_matrix: np.ndarray, allocation: np.ndarray
        ) -> float:
            gamma = self.lagrange_coefficients()
            n_levels, n_groups = variance_matrix.shape
            total = 0.0
            for j in range(n_levels):
                for k in range(n_groups):
                    n = allocation[j, k]
                    if n > 0:
                        total += gamma[j] ** 2 * variance_matrix[j, k] / n
            return total

        def measure_and_estimate(
            self,
            state: np.ndarray,
            allocation: np.ndarray,
            rng: Optional[np.random.Generator] = None,
        ) -> Tuple[np.ndarray, np.ndarray]:
            if rng is None:
                rng = np.random.default_rng()

            energy_per_level = np.zeros(self.n_levels)
            variance_matrix = np.zeros((self.n_levels, self.n_groups))

            for j in range(self.n_levels):
                for k in range(self.n_groups):
                    n_shots = int(allocation[j, k])
                    if n_shots < 1:
                        continue

                    terms, coeffs = self.hamiltonian.group_terms(k)
                    measurements = sample_commuting_group(
                        state,
                        terms,
                        self.noise_rate,
                        self.depth,
                        self.scale_factors[j],
                        n_shots,
                        rng,
                    )

                    # Energy contribution: mean of weighted measurements
                    means = np.mean(measurements, axis=0)
                    energy_per_level[j] += float(means @ coeffs)

                    # Per-shot variance estimate
                    variance_matrix[j, k] = self.estimate_group_variance(
                        measurements, k
                    )

            return energy_per_level, variance_matrix

        def run_adaptive(
            self,
            state: np.ndarray,
            total_budget: int,
            num_rounds: int,
            rng: Optional[np.random.Generator] = None,
        ) -> Dict:
            if rng is None:
                rng = np.random.default_rng()

            shots_per_round = total_budget // num_rounds

            # Accumulators for all measurements
            all_measurements: Dict[Tuple[int, int], List[np.ndarray]] = {}
            cumulative_alloc = np.zeros(
                (self.n_levels, self.n_groups), dtype=int
            )
            cumulative_sums = np.zeros((self.n_levels, self.n_groups))
            cumulative_counts = np.zeros(
                (self.n_levels, self.n_groups), dtype=int
            )
            variance_matrix = np.ones((self.n_levels, self.n_groups))

            for round_idx in range(num_rounds):
                # Determine this round's budget
                if round_idx == num_rounds - 1:
                    round_budget = total_budget - int(cumulative_alloc.sum())
                else:
                    round_budget = shots_per_round

                if round_budget <= 0:
                    break

                # Compute allocation for this round
                if round_idx == 0:
                    n_cells = self.n_levels * self.n_groups
                    base = round_budget // n_cells
                    alloc = np.full(
                        (self.n_levels, self.n_groups), base, dtype=int
                    )
                    leftover = round_budget - alloc.sum()
                    for i in range(leftover):
                        alloc.flat[i] += 1
                else:
                    alloc = self.optimal_allocation(
                        variance_matrix, round_budget
                    )

                # Execute measurements
                for j in range(self.n_levels):
                    for k in range(self.n_groups):
                        n_shots = int(alloc[j, k])
                        if n_shots < 1:
                            continue

                        terms, coeffs = self.hamiltonian.group_terms(k)
                        meas = sample_commuting_group(
                            state,
                            terms,
                            self.noise_rate,
                            self.depth,
                            self.scale_factors[j],
                            n_shots,
                            rng,
                        )

                        key = (j, k)
                        if key not in all_measurements:
                            all_measurements[key] = []
                        all_measurements[key].append(meas)

                        cumulative_alloc[j, k] += n_shots
                        cumulative_sums[j, k] += float(
                            np.sum(meas, axis=0) @ coeffs
                        )
                        cumulative_counts[j, k] += n_shots

                # Update running variance estimates from all data
                for j in range(self.n_levels):
                    for k in range(self.n_groups):
                        key = (j, k)
                        if key in all_measurements:
                            combined = np.vstack(all_measurements[key])
                            variance_matrix[j, k] = (
                                self.estimate_group_variance(combined, k)
                            )

            # Compute final energy per level from accumulated measurements
            energy_per_level = np.zeros(self.n_levels)
            for j in range(self.n_levels):
                for k in range(self.n_groups):
                    if cumulative_counts[j, k] > 0:
                        energy_per_level[j] += (
                            cumulative_sums[j, k] / cumulative_counts[j, k]
                        )

            energy = self.richardson_extrapolate(energy_per_level)
            variance = self.zne_variance(variance_matrix, cumulative_alloc)

            return {
                "energy": float(energy),
                "variance": float(variance),
                "energy_per_level": energy_per_level,
                "allocation": cumulative_alloc,
            }
''')

# Write the solution to /app/optimizer.py
with open("/app/optimizer.py", "w") as f:
    f.write(SOLUTION_CODE)

# Verify the solution loads correctly
sys.path.insert(0, "/app")
import importlib

if "optimizer" in sys.modules:
    del sys.modules["optimizer"]
import optimizer  # noqa: E402

opt_cls = optimizer.ZNEShotOptimizer
# Quick sanity check: Lagrange coefficients for [1, 2, 3]
from hamiltonian import Hamiltonian  # noqa: E402

ham = Hamiltonian(["Z"], [1.0])
opt = opt_cls(ham, [1.0, 2.0, 3.0], 0.01, 10)
gamma = opt.lagrange_coefficients()
assert abs(gamma[0] - 3.0) < 1e-10
assert abs(gamma[1] + 3.0) < 1e-10
assert abs(gamma[2] - 1.0) < 1e-10
print("Solution written to /app/optimizer.py and verified successfully.")
