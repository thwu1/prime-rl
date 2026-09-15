"""Utility distributions for coupled MCMC experiments."""
import numpy as np
import scipy.stats as st
from scipy.special import logsumexp

__all__ = ["mixture_of_gaussians"]


class mixture_of_gaussians:
    """Mixture of 1D Gaussians with given parameters and probabilities."""

    def __init__(self, params, probs):
        """Construct mixture distribution.

        Parameters
        ----------
        params : list of tuples
            (loc, scale) for each component, passed to scipy.stats.norm.
        probs : list of floats
            Probability of each mixture component. Must sum to 1.
        """
        self._probs = np.array(probs)
        self._logp = np.log(self._probs).reshape((1, len(self._probs)))
        self._rvs = [st.norm(*param) for param in params]

    def rvs(self, size=1):
        """Draw samples from the mixture."""
        vals = np.concatenate([
            rv.rvs(size=size_)
            for rv, size_ in zip(self._rvs, np.random.multinomial(size, self._probs))
        ])
        np.random.shuffle(vals)
        return vals

    def pdf(self, point):
        """Evaluate the probability density function."""
        return self._probs.dot([rv.pdf(point) for rv in self._rvs])

    def logpdf(self, point):
        """Evaluate the log probability density function."""
        point = np.array(point)
        if point.size > 1:
            point = point.reshape((len(self._rvs), -1))
            parts = self._logp.T + np.reshape(
                [rv.logpdf(point) for rv in self._rvs],
                (len(self._rvs), -1),
            )
            return logsumexp(parts, axis=0)
        parts = self._logp + np.array([rv.logpdf(point) for rv in self._rvs])
        return logsumexp(parts)
