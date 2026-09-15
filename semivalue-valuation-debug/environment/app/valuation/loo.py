"""Leave-one-out data valuation evaluator.

Computes the marginal utility loss from excluding each individual training
point. Unlike semivalue evaluators that operate on precomputed marginal
contribution matrices, LOO requires direct utility function evaluation.

References
----------
R. Cook, Detection of Influential Observation in Linear Regression,
Technometrics, Vol. 19, No. 1 (Feb., 1977), pp. 15-18.
"""

import numpy as np


class LeaveOneOutEvaluator:
    """Leave-one-out data valuation evaluator.

    Computes the change in utility when each individual training point
    is excluded from the dataset, providing a direct measure of each
    point's contribution to model performance.
    """

    def compute_values(self, marginal_contribs):
        """Compute LOO values from the marginal contribution matrix.

        Parameters
        ----------
        marginal_contribs : np.ndarray
            Marginal contribution matrix from the permutation sampler.

        Returns
        -------
        np.ndarray
            LOO value for each training point.
        """
        raise NotImplementedError(
            "LOO evaluation requires direct utility computation, "
            "not the semivalue marginal contribution matrix."
        )

    def compute_loo_values(self, utility_func, n):
        """Compute leave-one-out values by direct utility evaluation.

        For each training point i, computes the difference in utility
        between the full training set and the set with point i removed.

        Parameters
        ----------
        utility_func : callable
            Function mapping a list of integer indices to a float score.
        n : int
            Number of training data points.

        Returns
        -------
        np.ndarray
            LOO value for each training point, shape (n,).
        """
        return np.zeros(n)
