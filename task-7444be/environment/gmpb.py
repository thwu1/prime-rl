"""
Generalized Moving Peaks Benchmark (GMPB) for Dynamic Optimization.

Based on: D. Yazdani et al., "Benchmarking continuous dynamic optimization:
Survey and generalized test suite," IEEE Transactions on Cybernetics, 2020.

Generates dynamic fitness landscapes composed of cone-shaped peaks with
controllable characteristics. The landscape changes periodically, requiring
optimizers to track the moving optimum across environment transitions.

The fitness function is:
    f(x) = max_{i=1..m} { h_i - w_i * ||x - c_i|| }

where h_i, w_i, c_i are the height, width, and center of peak i.

After every `change_frequency` evaluations, peak positions shift by
`shift_severity` in a correlated random direction, and heights/widths
undergo bounded random perturbations.
"""

import numpy as np


class GMPB:
    """Generalized Moving Peaks Benchmark.

    Attributes:
        num_peaks (int): Number of peaks in the landscape.
        dimension (int): Dimensionality of the search space.
        change_frequency (int): Evaluations between environment changes.
        shift_severity (float): Magnitude of peak position shifts per change.
        num_environments (int): Total number of environments.
        min_coord (float): Lower bound of search space (-25.0).
        max_coord (float): Upper bound of search space (25.0).
        height_severity (float): Std dev of height perturbation per change.
        width_severity (float): Std dev of width perturbation per change.
    """

    def __init__(self, num_peaks=10, dimension=5, change_frequency=5000,
                 shift_severity=1.0, num_environments=30, seed=42,
                 height_severity=7.0, width_severity=1.0):
        self.num_peaks = num_peaks
        self.dimension = dimension
        self.change_frequency = change_frequency
        self.shift_severity = shift_severity
        self.num_environments = num_environments
        self.height_severity = height_severity
        self.width_severity = width_severity
        self.min_coord = -25.0
        self.max_coord = 25.0

        self._rng = np.random.RandomState(seed)
        self._total_evals = change_frequency * num_environments
        self._eval_count = 0
        self._current_env = 0
        self._current_errors = []
        self._best_found = -np.inf

        # Initialize peak parameters
        self._positions = self._rng.uniform(
            self.min_coord, self.max_coord, (num_peaks, dimension))
        self._heights = self._rng.uniform(30.0, 70.0, num_peaks)
        self._widths = self._rng.uniform(1.0, 12.0, num_peaks)
        self._prev_shifts = np.zeros((num_peaks, dimension))

    @property
    def optimum(self):
        """Current global optimum fitness value."""
        return float(np.max(self._heights))

    @property
    def optimum_position(self):
        """Position of the current global optimum peak."""
        return self._positions[np.argmax(self._heights)].copy()

    def evaluate(self, x):
        """Evaluate the fitness of a candidate solution.

        Computes the maximum over all cone-shaped peak contributions,
        updates the best-found tracking, records the current error,
        and triggers an environment change if the evaluation count
        reaches a multiple of change_frequency.

        Args:
            x: Array-like of shape (dimension,) within [min_coord, max_coord].

        Returns:
            float: The fitness value at x.

        Raises:
            RuntimeError: If the evaluation budget is exhausted.
            ValueError: If x has the wrong dimensionality.
        """
        if self._eval_count >= self._total_evals:
            raise RuntimeError("Evaluation budget exhausted")

        x = np.asarray(x, dtype=np.float64).ravel()
        if x.shape[0] != self.dimension:
            raise ValueError(
                f"Expected {self.dimension}-d vector, got {x.shape[0]}-d")

        # Vectorized fitness: f(x) = max_i { h_i - w_i * ||x - c_i|| }
        diffs = self._positions - x[np.newaxis, :]
        dists = np.sqrt(np.sum(diffs ** 2, axis=1))
        peaks = self._heights - self._widths * dists
        fitness = float(np.max(peaks))

        # Update best-found and record current error
        self._best_found = max(self._best_found, fitness)
        error = max(0.0, self.optimum - self._best_found)
        self._current_errors.append(error)
        self._eval_count += 1

        # Trigger environment change at boundary
        if (self._eval_count % self.change_frequency == 0 and
                self._eval_count < self._total_evals):
            self._change_environment()

        return fitness

    def _change_environment(self):
        """Apply stochastic perturbations to create a new environment."""
        self._current_env += 1
        self._best_found = -np.inf

        for i in range(self.num_peaks):
            # Correlated random shift direction
            rand_vec = self._rng.randn(self.dimension)
            rand_vec /= (np.linalg.norm(rand_vec) + 1e-15)
            combined = self._prev_shifts[i] + rand_vec
            norm = np.linalg.norm(combined)
            if norm > 1e-15:
                shift = combined / norm * self.shift_severity
            else:
                shift = rand_vec * self.shift_severity
            self._prev_shifts[i] = shift

            # Update position with boundary clamping
            self._positions[i] += shift
            self._positions[i] = np.clip(
                self._positions[i], self.min_coord, self.max_coord)

            # Perturb height within [10, 100]
            self._heights[i] += self.height_severity * self._rng.randn()
            self._heights[i] = np.clip(self._heights[i], 10.0, 100.0)

            # Perturb width within [0.5, 15]
            self._widths[i] += self.width_severity * self._rng.randn()
            self._widths[i] = np.clip(self._widths[i], 0.5, 15.0)

    def get_offline_error(self):
        """Compute offline error: mean current error over all evaluations.

        Returns:
            float: The offline error, or inf if no evaluations performed.
        """
        if not self._current_errors:
            return float('inf')
        return float(np.mean(self._current_errors))

    def is_finished(self):
        """Check if the evaluation budget is exhausted.

        Returns:
            bool: True if eval_count >= change_frequency * num_environments.
        """
        return self._eval_count >= self._total_evals

    def get_environment(self):
        """Get the current environment index (0-based).

        Returns:
            int: Current environment number.
        """
        return self._current_env

    def get_eval_count(self):
        """Get the total number of evaluations performed so far.

        Returns:
            int: Evaluation count.
        """
        return self._eval_count

    def get_remaining_evals(self):
        """Get the remaining evaluation budget.

        Returns:
            int: Remaining evaluations.
        """
        return self._total_evals - self._eval_count
