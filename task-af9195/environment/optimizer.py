"""Dynamic optimizer skeleton — implement this class.

The Moving Peaks Benchmark is implemented as a C shared library (libgmpb.so).
The evaluation runner loads it via ctypes and calls this optimizer through the
ask/tell interface.  Instance configurations are in config.db (SQLite).

Build the library:   make
Inspect the C API:   cat /app/src/gmpb.h
Query instances:     sqlite3 /app/config.db "SELECT * FROM instances"
View thresholds:     sqlite3 /app/config.db "SELECT * FROM thresholds"
Evaluate:            python3 /app/runner.py
See also:            /app/spec.md
"""


import numpy as np
from typing import List


class Optimizer:
    """Dynamic optimizer for the Moving Peaks Benchmark.

    Parameters
    ----------
    dimension : int
        Number of decision variables.
    bounds : tuple of (float, float)
        (lower_bound, upper_bound) shared by all variables.
    num_peaks : int
        Number of peaks in the landscape (informational hint).
    seed : int
        Random seed for reproducibility.
    """

    def __init__(self, dimension: int, bounds: tuple,
                 num_peaks: int, seed: int = 42):
        self.dimension = dimension
        self.bounds = bounds
        self.num_peaks = num_peaks
        self.seed = seed
        # TODO: implement
        raise NotImplementedError("Implement the Optimizer class")

    def ask(self) -> List[np.ndarray]:
        """Return candidate solutions to evaluate.

        Returns
        -------
        list of np.ndarray
            Each array has shape ``(dimension,)`` with values in
            ``[bounds[0], bounds[1]]``.
        """
        raise NotImplementedError

    def tell(self, solutions: List[np.ndarray], values: List[float],
             environment_changed: bool) -> None:
        """Receive evaluation results.

        Parameters
        ----------
        solutions : list of np.ndarray
            The solutions returned by the most recent ``ask()`` call.
        values : list of float
            Fitness value for each solution (higher is better).
        environment_changed : bool
            ``True`` on the first ``tell()`` after an environment change.
        """
        raise NotImplementedError
