"""Semivalue evaluators that compute data values from marginal contributions.

Each evaluator applies a different weighting scheme to marginal contributions
at different coalition cardinalities, producing a scalar data value per point.
"""

import numpy as np
from math import comb
from scipy.special import beta as beta_func


class ShapleyEvaluator:
    """Data Shapley evaluator with uniform semivalue weights.

    Shapley values weight all coalition cardinalities equally, giving each
    cardinality the same importance in the final data value.
    """

    def compute_weights(self, n):
        """Compute uniform Shapley weights.

        Parameters
        ----------
        n : int
            Number of data points.

        Returns
        -------
        np.ndarray
            Weight vector of length n, all entries equal to 1/n.
        """
        return np.ones(n) / n

    def compute_values(self, marginal_contribs):
        """Compute data values as weighted sum of marginal contributions.

        Parameters
        ----------
        marginal_contribs : np.ndarray
            Array of shape (n, n) with average marginal contributions.

        Returns
        -------
        np.ndarray
            Data value for each of the n training points.
        """
        n = marginal_contribs.shape[0]
        weights = self.compute_weights(n)
        return np.sum(marginal_contribs * weights[np.newaxis, :], axis=1)


class BetaShapleyEvaluator:
    """Beta Shapley evaluator using Beta-function semivalue weights.

    Generalizes Shapley values by weighting cardinalities according to a
    Beta distribution, controlled by parameters alpha and beta.

    Parameters
    ----------
    alpha : float
        Alpha parameter of the Beta distribution.
    beta : float
        Beta parameter of the Beta distribution.

    References
    ----------
    Y. Kwon and J. Zou, "Beta Shapley: a Unified and Noise-reduced Data
    Valuation Framework for Machine Learning", arXiv:2110.14049, 2021.
    """

    def __init__(self, alpha=4, beta=1):
        self.alpha = alpha
        self.beta = beta

    def compute_weights(self, n):
        """Compute Beta Shapley weights.

        Parameters
        ----------
        n : int
            Number of data points.

        Returns
        -------
        np.ndarray
            Normalized weight vector of length n.
        """
        weight_list = [
            beta_func(j + self.alpha, n - (j + 1) + self.beta)
            / beta_func(j + 1, n - j)
            for j in range(n)
        ]
        return np.array(weight_list) / np.sum(weight_list)

    def compute_values(self, marginal_contribs):
        """Compute data values as weighted sum of marginal contributions.

        Parameters
        ----------
        marginal_contribs : np.ndarray
            Array of shape (n, n) with average marginal contributions.

        Returns
        -------
        np.ndarray
            Data value for each of the n training points.
        """
        n = marginal_contribs.shape[0]
        weights = self.compute_weights(n)
        return np.sum(marginal_contribs * weights[np.newaxis, :], axis=1)


class BanzhafEvaluator:
    """Data Banzhaf evaluator using binomial coefficient weights.

    Banzhaf values weight coalitions uniformly (each coalition of any size
    is equally likely), which translates to binomial coefficient weights
    across cardinalities.

    References
    ----------
    J. T. Wang and R. Jia, "Data Banzhaf: A Robust Data Valuation
    Framework for Machine Learning", arXiv:2205.15466, 2022.
    """

    def compute_weights(self, n):
        """Compute Banzhaf weights proportional to binomial coefficients.

        Parameters
        ----------
        n : int
            Number of data points.

        Returns
        -------
        np.ndarray
            Normalized weight vector of length n.
        """
        weights = np.array([comb(n, j) for j in range(n)], dtype=float)
        return weights / weights.sum()

    def compute_values(self, marginal_contribs):
        """Compute data values as weighted sum of marginal contributions.

        Parameters
        ----------
        marginal_contribs : np.ndarray
            Array of shape (n, n) with average marginal contributions.

        Returns
        -------
        np.ndarray
            Data value for each of the n training points.
        """
        n = marginal_contribs.shape[0]
        weights = self.compute_weights(n)
        return np.sum(marginal_contribs * weights[np.newaxis, :], axis=1)
