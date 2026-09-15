"""Permutation-based Monte Carlo sampler for marginal contribution estimation.

Implements MCMC sampling over random permutations to estimate the marginal
contribution of each data point at each coalition cardinality. Supports
truncation for efficiency and Gelman-Rubin convergence diagnostics.
"""

import numpy as np
from sklearn.utils import check_random_state


class PermutationSampler:
    """Samples random permutations to estimate marginal contributions.

    For each permutation, data points are added sequentially to a growing
    coalition. The change in utility when a point is added is its marginal
    contribution at that cardinality.

    Parameters
    ----------
    num_points : int
        Number of data points in the training set.
    mc_epochs : int
        Maximum number of permutation samples (outer MCMC iterations).
    min_cardinality : int
        Minimum coalition size before recording marginal contributions.
    gr_threshold : float
        Gelman-Rubin statistic threshold for MCMC convergence.
    min_samples : int
        Minimum number of permutation samples before checking convergence.
    random_state : int or RandomState or None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        num_points,
        mc_epochs=300,
        min_cardinality=5,
        gr_threshold=1.05,
        min_samples=100,
        random_state=None,
    ):
        self.num_points = num_points
        self.mc_epochs = mc_epochs
        self.min_cardinality = min_cardinality
        self.gr_threshold = gr_threshold
        self.min_samples = min_samples
        self.random_state = check_random_state(random_state)

        self.marginal_contrib_sum = np.zeros((num_points, num_points))
        self.marginal_count = np.zeros((num_points, num_points)) + 1e-8
        self.increment_stack = np.zeros((0, num_points))

    def set_utility(self, utility_func):
        """Set the utility function that scores a coalition of data points.

        Parameters
        ----------
        utility_func : callable
            Takes a list of integer indices, returns a float score.
        """
        self.compute_utility = utility_func

    def compute_marginal_contributions(self):
        """Run MCMC sampling and return average marginal contributions.

        Iterates through permutations, computing marginal contributions.
        Checks Gelman-Rubin convergence after every epoch once enough
        samples have been collected.

        Returns
        -------
        np.ndarray
            Array of shape (num_points, num_points) where entry (i, j) is
            the estimated average marginal contribution of point i when
            added to a coalition of cardinality j.
        """
        for epoch in range(self.mc_epochs):
            increment = self._sample_one_permutation()
            self.increment_stack = np.vstack([self.increment_stack, increment])

            if len(self.increment_stack) >= self.min_samples:
                gr = self._compute_gr_statistic()
                if gr < self.gr_threshold:
                    break

        return self.marginal_contrib_sum / self.marginal_count

    def _sample_one_permutation(self):
        """Sample one random permutation and record marginal contributions.

        Walks through the permutation from min_cardinality to n, adding
        each point and recording its marginal contribution. Implements
        truncation: if consecutive marginal contributions are negligible,
        stops early and accounts for zero contributions.

        Returns
        -------
        np.ndarray
            Increment vector of shape (1, num_points).
        """
        perm = self.random_state.permutation(self.num_points)
        marginal_increment = np.zeros(self.num_points) + 1e-8
        coalition = list(perm[: self.min_cardinality])
        truncation_counter = 0

        prev_perf = self.compute_utility(coalition)

        for cutoff, idx in enumerate(
            perm[self.min_cardinality :], start=self.min_cardinality
        ):
            coalition.append(idx)
            curr_perf = self.compute_utility(coalition)
            marginal_increment[idx] = curr_perf - prev_perf

            self.marginal_contrib_sum[idx, cutoff] += curr_perf - prev_perf
            self.marginal_count[idx, cutoff] += 1

            # Truncation: stop when marginal contributions become negligible
            relative_change = abs(curr_perf - prev_perf) / max(
                np.sum(np.abs(marginal_increment)), 1e-8
            )
            if relative_change < 1e-8:
                truncation_counter = 0
            else:
                truncation_counter += 1

            if truncation_counter == 10:
                remaining = perm[(cutoff + 1) :]
                remaining_positions = np.arange(cutoff + 1, len(perm))
                if len(remaining) > 0:
                    self.marginal_count[remaining, remaining_positions] += 1
                break

            prev_perf = curr_perf

        return marginal_increment.reshape(1, -1)

    def _compute_gr_statistic(self, num_chains=10):
        """Compute the Gelman-Rubin convergence diagnostic.

        Splits the accumulated MCMC samples into parallel chains and
        computes the multivariate potential scale reduction factor.

        Parameters
        ----------
        num_chains : int
            Number of chains to split samples into.

        Returns
        -------
        float
            Maximum GR statistic across all dimensions.

        References
        ----------
        Vats & Knudson (2018), "Revisiting the Gelman-Rubin Diagnostic",
        arXiv:1812.09384, Eq. 4.
        """
        samples = self.increment_stack
        num_samples, num_datapoints = samples.shape

        if num_samples < self.min_samples:
            return 100.0

        num_per_chain, offset = divmod(num_samples, num_chains)
        if num_per_chain < 2:
            return 100.0
        samples = samples[offset:]

        chains = samples.reshape(num_chains, num_per_chain, num_datapoints)

        # W: average within-chain variance
        W = np.mean(np.var(chains, axis=1, ddof=1), axis=0)

        # B: between-chain variance scaled by chain length
        chain_means = np.mean(chains, axis=1)
        B = num_per_chain * np.var(chain_means, axis=0, ddof=1)

        # Potential scale reduction factor
        gr_stats = np.sqrt(
            (num_per_chain - 1) / num_per_chain
            - (B / (W * num_per_chain + 1e-10))
        )

        return np.nanmax(np.abs(gr_stats))
